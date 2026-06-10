"""Interactive blogpost studio: co-write a blogpost with a ``pi`` agent.

This is the conversational counterpart to ``experiments/04_blogpost_gen`` (the
batch author -> reviewer -> fix pipeline). Instead of running the author to
completion in one shot, a :class:`StudioSession` drives the *same* agent
primitive one turn at a time, resuming a single ``pi`` session, so a human can
chat with it on the side and jointly write ``final_writeup.md`` piece by piece
(or have it write the whole draft in one turn via the ``/draft`` chat command).

It reuses the audit-agent infrastructure directly:

  - the source run is bind-mounted READ-ONLY at ``/source`` (via
    :mod:`src.sandbox`), exactly as the batch author sees it,
  - a *persistent* working dir is the agent's CWD at ``/workspace`` — it holds
    the shared ``final_writeup.md``, the ``final_plots/`` figures, and the
    ``session.jsonl`` transcript, so a studio can be closed and resumed later,
  - each user chat message resumes ``session.jsonl`` with that message as the
    next user turn; a constant collaboration + writing-standards system prompt is
    appended on every turn.

The web UI lives in ``experiments/06_blogpost_studio/app.py``; this module is the
headless engine it talks to (start/stop a turn, read/save the document, list
figures, parse the transcript) and can also be driven from a script or a test.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from src import audit_agent, sandbox
from src.agent_viewer import parse_session
from src.runner_utils import parse_env_text

ROOT = Path(__file__).resolve().parents[1]

# Prompt templates: this experiment's own templates, plus the shared writing
# rubric from 04_blogpost_gen (single source of truth — the studio system prompt
# ``{% include %}``s ``_writing_instructions.md.j2`` from there).
_PROMPTS = ROOT / "experiments" / "06_blogpost_studio" / "prompts"
_WRITING_RUBRIC = ROOT / "experiments" / "04_blogpost_gen" / "prompts"

_JINJA = Environment(
    loader=FileSystemLoader([str(_PROMPTS), str(_WRITING_RUBRIC)]),
    autoescape=False,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)

# Interactive editing wants responsiveness, so default to Claude Fable 5 (same
# author model as 04_blogpost_gen). Override with --model / BLOGPOST_STUDIO_MODEL.
DEFAULT_STUDIO_MODEL = os.environ.get(
    "BLOGPOST_STUDIO_MODEL", "anthropic/claude-fable-5"
)
DEFAULT_THINKING = "high"

DOC_NAME = "final_writeup.md"
SESSION_NAME = "session.jsonl"


def render(template: str, **ctx: object) -> str:
    """Render a prompt template from ``prompts/`` (or the shared rubric dir)."""
    return _JINJA.get_template(template).render(**ctx)


# Chat commands: a message whose first word is a known /command expands into a
# full prompt template. Expansion happens server-side, in start_turn, so the
# session transcript records the real prompt the agent received.
COMMANDS = {
    "/draft": "draft.md.j2",  # write the complete post in one turn (the 04 author behavior)
    "/kickoff": "kickoff.md.j2",  # investigate the run, reply "ready"
}


def expand_command(message: str) -> str:
    """Expand a leading /command; any text after it rides along as extra
    instructions. Non-command messages pass through unchanged."""
    head, _, rest = message.partition(" ")
    template = COMMANDS.get(head.lower())
    if template is None:
        return message
    prompt = render(template)
    rest = rest.strip()
    if rest:
        prompt += f"\n\nAdditional instructions from your collaborator:\n{rest}"
    return prompt


def default_work_dir(run_dir: str | Path) -> Path:
    """Persistent studio workspace for a run: ``outputs/06_blogpost_studio/<run>``.

    Unlike the batch pipeline (which uses a throwaway tmp dir), the studio keeps
    its workspace so the conversation, document, and figures survive restarts and
    a session can be resumed.
    """
    return ROOT / "outputs" / "06_blogpost_studio" / Path(run_dir).resolve().name


class StudioSession:
    """One human+agent co-writing session over a single completed run.

    Thread-safety: at most one agent turn runs at a time. :meth:`start_turn`
    refuses to start a second concurrent turn; the turn runs in a background
    thread so the web server stays responsive and can stream the transcript and
    document off disk while the agent works.
    """

    def __init__(
        self,
        run_dir: str | Path,
        work_dir: str | Path | None = None,
        *,
        model: str = DEFAULT_STUDIO_MODEL,
        thinking: str = DEFAULT_THINKING,
        env_text: str | None = None,
    ) -> None:
        self.run_dir = Path(run_dir).resolve()
        if not audit_agent.is_run_dir(self.run_dir):
            raise ValueError(
                f"{self.run_dir} is not a run/project dir (no .pi_transcripts/ found)"
            )
        if sandbox.available() is None:
            raise RuntimeError("bubblewrap (bwrap) is not installed")
        self.work = Path(work_dir or default_work_dir(self.run_dir)).resolve()
        self.model = model
        self.thinking = thinking
        self._env_text = env_text
        # The collaboration + writing-standards system prompt is constant across
        # the whole session, so render it once and append it on every turn.
        self.system_prompt = render("studio_system.md.j2")

        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._last_rc: int | None = None
        self._log = self.work / "studio_agent.log"
        self._turn_log_offset: int | None = (
            None  # where the running turn's json stream starts
        )
        self._tx_cache: tuple | None = None  # ((mtime, size), parsed transcript)

        audit_agent.stage_reference_docs(self.work, self.run_dir)

    # ----------------------------------------------------------------- paths --
    @property
    def doc_path(self) -> Path:
        return self.work / DOC_NAME

    @property
    def session_path(self) -> Path:
        return self.work / SESSION_NAME

    @property
    def log_path(self) -> Path:
        return self._log

    # -------------------------------------------------------------- document --
    def read_doc(self) -> dict:
        """Current document content + mtime/size (empty string if not started)."""
        p = self.doc_path
        if not p.exists():
            return {"content": "", "mtime": 0.0, "size": 0}
        st = p.stat()
        return {
            "content": p.read_text(encoding="utf-8", errors="replace"),
            "mtime": st.st_mtime,
            "size": st.st_size,
        }

    def write_doc(self, content: str) -> dict:
        """Save the human's edits to the document. Refuses while a turn runs.

        Locking the document during an agent turn keeps the human and the agent
        from clobbering each other: the agent owns the file mid-turn, the human
        owns it between turns.
        """
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise RuntimeError(
                    "the agent is writing; save is disabled until it finishes"
                )
            self.doc_path.write_text(content, encoding="utf-8")
            st = self.doc_path.stat()
        return {"mtime": st.st_mtime, "size": st.st_size}

    def plots(self) -> list[str]:
        """Figure files (.png/.pdf) the agent has produced under final_plots/."""
        return audit_agent.list_plots(self.work)

    def reset(self) -> None:
        """Delete this run's draft: the document, conversation, figures, and
        anything else the agent created — the workspace is re-staged fresh.
        Refuses while a turn is running."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise RuntimeError("stop the running turn before deleting the draft")
            shutil.rmtree(self.work, ignore_errors=True)
            self._tx_cache = None
            self._last_rc = None
            self._turn_log_offset = None
        audit_agent.stage_reference_docs(self.work, self.run_dir)

    # ------------------------------------------------------------ transcript --
    def transcript(self) -> dict:
        """Parsed chat: ``{turns, cost, ...}`` (empty turns before the first message).

        Cached on the session file's (mtime, size) so re-reading and re-parsing a
        large, unchanged transcript is skipped — the file only changes at message
        boundaries, not on every poll.
        """
        try:
            st = self.session_path.stat()
        except OSError:
            return {"turns": [], "goal": None, "header": {}, "cost": 0.0}
        sig = (st.st_mtime, st.st_size)
        if self._tx_cache and self._tx_cache[0] == sig:
            return self._tx_cache[1]
        text = self.session_path.read_text(encoding="utf-8", errors="replace")
        parsed = parse_session(text)
        self._tx_cache = (sig, parsed)
        return parsed

    def live_turns(self, after_ts: float = 0) -> list[dict]:
        """Turns of the in-flight pi turn, parsed from the live json stream.

        ``session.jsonl`` is only written at message boundaries, so a long
        assistant message (minutes of thinking) is invisible in
        :meth:`transcript` until it completes. The agent's ``--mode json``
        stdout (``studio_agent.log``) does stream: every ``message_update``
        line carries the full cumulative partial message. Parse the running
        turn's slice of the log and return its turns newer than ``after_ts``
        (the session's last message timestamp, for dedup against whatever pi
        has already flushed) — i.e. completed-but-unflushed messages plus the
        currently streaming partial one.
        """
        offset = self._turn_log_offset
        if offset is None or not self.is_running():
            return []
        try:
            with self._log.open("rb") as f:
                f.seek(offset)
                data = f.read()
        except OSError:
            return []
        messages: list[dict] = []
        partial_line: str | None = None
        for line in data.decode("utf-8", "replace").splitlines():
            # Cheap prefix filters: update lines are huge (each repeats the
            # whole partial message), so only the last one — the current
            # streaming state — ever gets json-parsed.
            if line.startswith('{"type":"message_update"'):
                partial_line = line
            elif line.startswith('{"type":"message_end"'):
                try:
                    msg = json.loads(line).get("message") or {}
                except json.JSONDecodeError:  # torn write: pi is mid-append
                    continue
                messages.append(msg)
                partial_line = None  # that partial completed; drop it
        if partial_line is not None:
            try:
                messages.append(json.loads(partial_line).get("message") or {})
            except json.JSONDecodeError:
                pass
        if not messages:
            return []
        # Reuse the session parser (turn building + tool-result attachment) by
        # presenting the messages as session entries.
        fake = "\n".join(
            json.dumps({"type": "message", "message": m}) for m in messages
        )
        turns = parse_session(fake)["turns"]
        return [t for t in turns if (t.get("ts") or 0) > after_ts]

    # ---------------------------------------------------------------- turns ---
    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def _env(self) -> dict[str, str]:
        if self._env_text is not None:
            overrides = parse_env_text(self._env_text)
        else:
            env_path = ROOT / ".env"
            overrides = (
                parse_env_text(env_path.read_text()) if env_path.exists() else {}
            )
        return sandbox.default_env(overrides)

    def _argv(self, prompt: str) -> list[str]:
        inner = [
            "pi",
            "-p",
            "--session",
            f"{sandbox.WORKSPACE}/{SESSION_NAME}",
            "--append-system-prompt",
            self.system_prompt,
            "--model",
            self.model,
            "--thinking",
            self.thinking,
            "--mode",
            "json",
            prompt,
        ]
        return sandbox.build_argv(
            self.work, inner, extra_ro_dest_binds=((str(self.run_dir), "/source"),)
        )

    def start_turn(self, message: str) -> None:
        """Resume the session with ``message`` as the next user turn (background).

        Returns immediately; poll :meth:`is_running` / stream :meth:`transcript`
        and :meth:`read_doc` off disk to follow progress. Raises if a turn is
        already running or the message is empty.
        """
        message = expand_command((message or "").strip())
        if not message:
            raise ValueError("empty message")
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise RuntimeError(
                    "the agent is already working on the previous message"
                )
            argv = self._argv(message)
            log = self._log.open("ab")
            try:
                log.write(f"\n\n===== turn: {message[:200]!r} =====\n".encode())
                log.flush()
                self._turn_log_offset = self._log.stat().st_size
                proc = subprocess.Popen(
                    argv,
                    env=self._env(),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            except Exception:
                log.close()
                raise
            self._proc = proc
        threading.Thread(target=self._reap, args=(proc, log), daemon=True).start()

    def _reap(self, proc: subprocess.Popen, log) -> None:
        try:
            proc.wait()
        finally:
            with self._lock:
                self._last_rc = proc.poll()
                if self._proc is proc:
                    self._proc = None
            try:
                log.close()
            except OSError:
                pass

    def stop(self) -> bool:
        """Kill the running turn, if any. Returns whether something was killed."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.kill()
                return True
        return False

    def state(self) -> dict:
        """Snapshot for the UI header / polling."""
        return {
            "run_dir": str(self.run_dir),
            "run_name": self.run_dir.name,
            "work_dir": str(self.work),
            "model": self.model,
            "thinking": self.thinking,
            "running": self.is_running(),
            "last_rc": self._last_rc,
        }
