"""Interactive blogpost studio: co-write a blogpost with a ``pi`` agent.

This is the conversational counterpart to ``experiments/04_blogpost_gen`` (the
batch author -> reviewer -> fix pipeline). Instead of running the author to
completion in one shot, a :class:`StudioSession` drives the *same* agent
primitive one turn at a time, resuming a single ``pi`` session, so a human can
chat with it on the side and jointly write ``final_writeup.md`` piece by piece
(or have it run the automatic writeup pipeline via the ``/draft`` chat command).

It reuses the audit-agent infrastructure directly:

  - the source run is bind-mounted READ-ONLY at ``/source`` (via
    :mod:`src.sandbox`), exactly as the batch author sees it,
  - a *persistent* working dir is the agent's CWD at ``/workspace`` — it holds
    the shared ``final_writeup.md``, the ``final_plots/`` figures, and the
    ``session.jsonl`` transcript, so a studio can be closed and resumed later,
  - each user chat message resumes ``session.jsonl`` with that message as the
    next user turn; a constant collaboration + writing-standards system prompt is
    appended on every turn.

**Execution model — detached, resumable jobs.** An agent turn is NOT run as a
child of the web server. ``start_turn`` launches a small *supervisor* process
(:mod:`src.studio_job`) detached into its own session; that supervisor runs the
turn (or the whole ``/draft`` chain) inside the bwrap sandbox and records its
progress to ``turn_status.json`` in the workspace. Because the agent's sandbox is
``--die-with-parent`` to the *supervisor* (not the web server), restarting or
crashing the web server leaves running writeups untouched: they reparent to init
and keep going, and any viewer re-adopts them by reading the workspace off disk
(``turn_status.json`` + a ``/proc`` liveness scan). A crashed supervisor is
resumable from ``session.jsonl`` (``--resume``). This is the same decoupling that
lets ``03_run_agents`` survive viewer restarts.

The web UI lives in ``experiments/06_blogpost_studio/app.py``; this module is the
headless engine it talks to (start/stop a turn, read/save the document, list
figures, parse the transcript) and the per-turn executor the supervisor calls.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from src import DEFAULT_MODEL, audit_agent, sandbox
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

# Blog writing is a judgment-heavy synthesis task; default to the shared Claude
# model unless explicitly overridden.
DEFAULT_STUDIO_MODEL = os.environ.get("BLOGPOST_STUDIO_MODEL", DEFAULT_MODEL)
DEFAULT_THINKING = "high"

DOC_NAME = "final_writeup.md"
SESSION_NAME = "session.jsonl"


def render(template: str, **ctx: object) -> str:
    """Render a prompt template from ``prompts/`` (or the shared rubric dir)."""
    return _JINJA.get_template(template).render(**ctx)


# Chat commands: a message whose first word is a known /command expands into a
# full prompt template. Expansion happens at execution time (in the supervisor),
# so the session transcript records the real prompt the agent received.
COMMANDS = {
    "/draft": "draft.md.j2",  # inventory first; chained into /compose below
    "/compose": "compose.md.j2",  # write the complete post from the inventory
    "/review": "review.md.j2",  # skeptical self-review + concrete fixes
    "/polish": "polish.md.j2",  # final anti-slop pass after review
    "/kickoff": "kickoff.md.j2",  # investigate the run, reply "ready"
}

# After a turn for the keyed /command finishes successfully, the pipeline
# automatically runs the mapped follow-up /command as the next step. This is how
# a /draft is always followed by compose -> review -> polish.
CHAIN_AFTER = {
    "/draft": "/compose",
    "/compose": "/review",
    "/review": "/polish",
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


# All studio workspaces live here, one dir per run.
STUDIO_ROOT = ROOT / "outputs" / "06_blogpost_studio"

# Workspace files written by the supervisor and read by any viewer off disk.
TURN_OFFSET_NAME = "turn.offset"  # byte offset of the running turn in the json log
TURN_STATUS_NAME = "turn_status.json"  # authoritative job state (see JobStatus)
JOB_SPEC_NAME = "job_spec.json"  # how to reconstruct the session for --resume

# Liveness: a running supervisor rewrites turn_status.json's heartbeat on this
# cadence. If the recorded pid is dead or the heartbeat is older than the stale
# threshold, the supervisor crashed and the turn is eligible for resume.
HEARTBEAT_INTERVAL = 8.0
HEARTBEAT_STALE_S = 40.0
# Grace window after launch before the supervisor has written its first
# heartbeat: a freshly launched job is "running" even though pid is not yet on
# disk, so a second concurrent start can't slip in and is_running doesn't flap.
LAUNCH_GRACE_S = 45.0
# How many times the supervisor retries a single step on a transient failure
# (a kill/crash mid-turn, or a recoverable API error) before giving up on it.
MAX_STEP_ATTEMPTS = max(1, int(os.environ.get("STUDIO_STEP_ATTEMPTS", "3")))


def live_sandbox_workspaces() -> set[str]:
    """Workspace paths of every live bwrap sandbox on the host (one /proc scan).

    Ground truth for "is an agent working on X?", independent of process
    ancestry: a writeup's sandbox can outlive the web server that launched it
    (it is parented to its supervisor, not the server), so neither a Popen
    handle nor parent/child relationships can be trusted for liveness.
    """
    found: set[str] = set()
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            argv = (Path("/proc") / p / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if not argv or not argv[0].endswith(b"bwrap"):
            continue
        for i in range(len(argv) - 2):
            if argv[i] == b"--bind" and argv[i + 2] == b"/workspace":
                raw = argv[i + 1].decode("utf-8", "replace")
                found.add(os.path.abspath(raw))  # normalize: binds may be relative
                break
    return found


def default_work_dir(run_dir: str | Path) -> Path:
    """Persistent studio workspace for a run: ``outputs/06_blogpost_studio/<run>``.

    Unlike the batch pipeline (which uses a throwaway tmp dir), the studio keeps
    its workspace so the conversation, document, and figures survive restarts and
    a session can be resumed.
    """
    return STUDIO_ROOT / Path(run_dir).resolve().name


def _pid_alive(pid: int | None) -> bool:
    """Whether a host pid currently exists (signal 0 probe)."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by someone else
    return True


# --- Workspace-level state, readable without constructing a session ---------- #
# The web layer polls many runs and the pump scans every workspace; building a
# StudioSession per run is expensive (it stages reference docs), so liveness and
# status are computed straight from the workspace's turn_status.json + a /proc
# scan. The session methods below delegate here so there is one definition.


def workspace_status(work: str | Path) -> dict | None:
    """The job status last written for a workspace (or None / malformed)."""
    try:
        status = json.loads((Path(work) / TURN_STATUS_NAME).read_text())
    except (OSError, ValueError, TypeError):
        return None
    return status if isinstance(status, dict) else None


def workspace_running(work: str | Path, live_ws: set[str] | None = None) -> bool:
    """Whether a turn is in flight for a workspace, by ground truth off disk.

    A ``running`` status counts as live while its supervisor pid is alive with a
    fresh heartbeat, or (just after launch, before the first heartbeat) within a
    boot grace window. Failing that, a bwrap still bound to the workspace counts.
    """
    st = workspace_status(work)
    if st and st.get("state") == "running":
        pid = st.get("pid")
        hb = st.get("heartbeat") or 0
        if (
            _pid_alive(pid if isinstance(pid, int) else None)
            and (time.time() - hb) < HEARTBEAT_STALE_S
        ):
            return True
        if pid is None and (time.time() - (st.get("launched") or 0)) < LAUNCH_GRACE_S:
            return True
    if live_ws is None:
        live_ws = live_sandbox_workspaces()
    return os.path.abspath(str(work)) in live_ws


def workspace_resumable(work: str | Path, live_ws: set[str] | None = None) -> bool:
    """A turn that was ``running`` but whose supervisor died without recording a
    terminal state — safe to relaunch with --resume."""
    st = workspace_status(work)
    if not st or st.get("state") != "running" or st.get("terminal"):
        return False
    if not (Path(work) / JOB_SPEC_NAME).exists():
        return False  # no recipe to reconstruct the session (e.g. a pre-upgrade turn)
    if workspace_running(work, live_ws):
        return False
    pid = st.get("pid")
    if pid is None and (time.time() - (st.get("launched") or 0)) < LAUNCH_GRACE_S:
        return False  # still booting; give it a chance before resuming
    return True


class DocAgentSession:
    """Generic human+agent co-editing session: one sandboxed ``pi`` conversation
    that edits one document, with chat and document streamed off disk.

    Subclasses say which document (:attr:`doc_path`), how to build the agent
    command (:meth:`_argv`), how slash-commands expand (:meth:`_expand`), what
    chains after a step (:meth:`_next_chain`), and how to reconstruct themselves
    in the supervisor process (:meth:`job_spec`). Used per-window/per-target:
    callers keep one session per edited thing, so any number can run in parallel.

    A turn runs in a *detached supervisor* process, not as a child of this
    process, so it survives a web-server restart. State is read back off disk
    (``turn_status.json`` + a ``/proc`` liveness scan), so a restarted server
    re-adopts in-flight turns transparently.
    """

    def __init__(
        self,
        work_dir: str | Path,
        *,
        model: str = DEFAULT_STUDIO_MODEL,
        thinking: str = DEFAULT_THINKING,
        env_text: str | None = None,
        system_prompt: str = "",
    ) -> None:
        if sandbox.available() is None:
            raise RuntimeError("bubblewrap (bwrap) is not installed")
        self.work = Path(work_dir).resolve()
        self.model = model
        self.thinking = thinking
        self._env_text = env_text
        # The system prompt is constant across the whole session: rendered once,
        # appended on every turn.
        self.system_prompt = system_prompt

        self._lock = threading.Lock()
        # Handle to the supervisor WE launched (None after a server restart that
        # adopts an already-running turn — liveness then comes from disk/proc).
        self._job_proc: subprocess.Popen | None = None
        self._log = self.work / "studio_agent.log"
        self._turn_log_offset: int | None = (
            None  # where the running turn's json stream starts
        )
        self._tx_cache: tuple | None = None  # ((mtime, size), parsed transcript)
        self._live_cache: dict | None = None  # incremental live_turns parse state
        self.work.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------- subclass surface --
    @property
    def doc_path(self) -> Path:
        raise NotImplementedError

    def _argv(self, prompt: str) -> list[str]:
        raise NotImplementedError

    def _expand(self, message: str) -> str:
        """Expand canned slash-commands into full prompts (default: none)."""
        return message

    def _next_chain(self, message: str) -> str | None:
        """The follow-up /command to auto-run after ``message``'s turn succeeds
        (default: none)."""
        return None

    def job_spec(self) -> dict:
        """How the supervisor reconstructs this exact session (module + class +
        constructor kwargs). Must be JSON-serializable."""
        raise NotImplementedError

    # ----------------------------------------------------------------- paths --

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
        if self.is_running():
            raise RuntimeError(
                "the agent is writing; save is disabled until it finishes"
            )
        self.doc_path.write_text(content, encoding="utf-8")
        st = self.doc_path.stat()
        return {"mtime": st.st_mtime, "size": st.st_size}

    def _clear_session_state(self) -> None:
        """Forget the cached conversation state and on-disk job markers."""
        self._tx_cache = None
        self._turn_log_offset = None
        self._live_cache = None
        self._job_proc = None
        for name in (TURN_OFFSET_NAME, TURN_STATUS_NAME, JOB_SPEC_NAME):
            (self.work / name).unlink(missing_ok=True)

    # ----------------------------------------------------------- job status ---
    def _status_path(self) -> Path:
        return self.work / TURN_STATUS_NAME

    def read_status(self) -> dict | None:
        """Raw job status as last written by the supervisor (or None)."""
        return workspace_status(self.work)

    def write_status(self, **fields: object) -> dict:
        """Atomically merge ``fields`` into turn_status.json, stamping ``time``.

        Merge (not overwrite) so a heartbeat-only update from one writer doesn't
        drop the step/state another writer set. Atomic via tmp + rename so a
        reader never sees a torn file.
        """
        with self._lock:
            base = self.read_status() or {}
            base.update(fields)
            base["time"] = time.time()
            tmp = self._status_path().with_suffix(".json.tmp")
            try:
                tmp.write_text(json.dumps(base, indent=2))
                tmp.replace(self._status_path())
            except OSError:
                pass
            return base

    # ----------------------------------------------------------------- live ---
    def transcript(self) -> dict:
        """Parsed chat: ``{turns, cost, ...}`` (empty turns before the first message).

        Cached on the session file's (mtime, size) so re-reading and re-parsing a
        large, unchanged transcript is skipped — the file only changes at message
        boundaries, not on every poll.
        """
        try:
            st = self.session_path.stat()
        except OSError:
            return {"turns": [], "header": {}, "cost": 0.0}
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
        if offset is None:
            # Adopt an in-flight turn we didn't start (server restarted, or the
            # supervisor wrote the offset): it was persisted at turn start.
            try:
                offset = int((self.work / TURN_OFFSET_NAME).read_text())
            except (OSError, ValueError):
                return []
            self._turn_log_offset = offset
        if not self.is_running():
            return []
        # Incremental: the stream is poll-read every SSE tick and can grow to
        # many MB within one turn, so keep a cursor and only parse new bytes.
        # The last (possibly torn, mid-append) line stays buffered until its
        # newline arrives. Guarded by the lock — two pages may stream at once.
        with self._lock:
            cache = self._live_cache
            if cache is None or cache["start"] != offset:
                cache = self._live_cache = {
                    "start": offset,
                    "pos": offset,
                    "tail": b"",
                    "messages": [],
                    "partial": None,
                }
            try:
                with self._log.open("rb") as f:
                    f.seek(cache["pos"])
                    data = f.read()
            except OSError:
                return []
            cache["pos"] += len(data)
            lines = (cache["tail"] + data).split(b"\n")
            cache["tail"] = lines.pop()
            for raw in lines:
                line = raw.decode("utf-8", "replace")
                # Cheap prefix filters: update lines are huge (each repeats the
                # whole partial message), so only the last one — the current
                # streaming state — ever gets json-parsed.
                if line.startswith('{"type":"message_update"'):
                    cache["partial"] = line
                elif line.startswith('{"type":"message_end"'):
                    try:
                        cache["messages"].append(json.loads(line).get("message") or {})
                    except json.JSONDecodeError:
                        continue
                    cache["partial"] = None  # that partial completed; drop it
            messages = list(cache["messages"])
            partial_line = cache["partial"]
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
    def _sandbox_pids(self) -> list[int]:
        """Host pids of bwrap processes sandboxing THIS workspace."""
        target = os.path.abspath(str(self.work))
        pids = []
        for p in os.listdir("/proc"):
            if not p.isdigit():
                continue
            try:
                argv = (Path("/proc") / p / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if not argv or not argv[0].endswith(b"bwrap"):
                continue
            for i in range(len(argv) - 2):
                if (
                    argv[i] == b"--bind"
                    and argv[i + 2] == b"/workspace"
                    and os.path.abspath(argv[i + 1].decode("utf-8", "replace"))
                    == target
                ):
                    pids.append(int(p))
                    break
        return pids

    def _supervisor_pid(self) -> int | None:
        st = self.read_status()
        pid = (st or {}).get("pid")
        return int(pid) if isinstance(pid, int) else None

    def is_running(self) -> bool:
        """Whether an agent turn is in flight — by ground truth, not ancestry.

        Layers, cheapest first: a supervisor we launched and still hold; a fresh
        ``running`` status whose supervisor pid is alive with a recent heartbeat
        (this is what a restarted server re-adopts); a just-launched job inside
        its boot grace window; finally a live sandbox bound to this workspace.
        """
        if self._job_proc is not None and self._job_proc.poll() is None:
            return True
        return workspace_running(self.work)

    def is_resumable(self) -> bool:
        """A turn that was running but whose supervisor died (crash / kill while
        not stopping) — safe to relaunch with --resume to finish the pipeline."""
        return workspace_resumable(self.work)

    def _env(self) -> dict[str, str]:
        if self._env_text is not None:
            overrides = parse_env_text(self._env_text)
        else:
            env_path = ROOT / ".env"
            overrides = (
                parse_env_text(env_path.read_text()) if env_path.exists() else {}
            )
        return sandbox.default_env(overrides)

    def _inner_argv(self, prompt: str) -> list[str]:
        """The pi invocation shared by every doc-agent flavor."""
        return [
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

    def command_chain(self, message: str) -> list[str]:
        """The ordered steps a fresh turn for ``message`` runs: the message
        itself, then each chained follow-up command (compose -> review -> ...).
        The first step keeps any extra instructions; later steps are bare
        commands."""
        steps = [message]
        nxt = self._next_chain(message)
        while nxt:
            steps.append(nxt)
            nxt = self._next_chain(nxt)
        return steps

    # ------------------------------------------------- supervisor: execute ---
    def run_turn_sync(self, prompt: str) -> int:
        """Run ONE pi turn synchronously and return its exit code.

        Called by the supervisor process (:mod:`src.studio_job`), NOT by the web
        server. Appends the agent's ``--mode json`` stream to ``studio_agent.log``
        and records the turn's byte offset so a viewer can stream it live. The
        sandbox is ``--die-with-parent`` to the supervisor, so killing the
        supervisor (a stop) cleanly tears the agent down with it.
        """
        argv = self._argv(prompt)
        with self._log.open("ab") as log:
            log.write(f"\n\n===== turn: {prompt[:200]!r} =====\n".encode())
            log.flush()
            (self.work / TURN_OFFSET_NAME).write_text(str(self._log.stat().st_size))
            proc = subprocess.run(
                argv,
                env=self._env(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        return proc.returncode

    def last_stop_reason(self) -> str | None:
        """The ``stopReason`` of the last assistant message in the session.

        Used by the supervisor to classify a turn that exited 0: ``stop`` /
        ``toolUse`` / ``length`` are success; ``refusal`` is a terminal decline;
        ``error`` is a (usually transient) API failure worth retrying. pi exits 0
        even on a refusal in json mode, so the exit code alone is not enough.
        """
        try:
            text = self.session_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        reason = None
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = entry.get("message") if entry.get("type") == "message" else entry
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                reason = msg.get("stopReason") or reason
        return reason

    def last_error_message(self) -> str | None:
        """The ``errorMessage`` of the last assistant message, if any (the human
        reason behind a refusal or API error)."""
        try:
            text = self.session_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        err = None
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = entry.get("message") if entry.get("type") == "message" else entry
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                em = msg.get("errorMessage")
                err = em if isinstance(em, str) and em.strip() else err
        return err

    # --------------------------------------------------- web server: drive ---
    def start_turn(self, message: str) -> None:
        """Launch a detached supervisor to run ``message`` (and its chain).

        Returns immediately; poll :meth:`is_running` / stream :meth:`transcript`
        and :meth:`read_doc` off disk to follow progress. Raises if a turn is
        already running or the message is empty. The supervisor is detached
        (``start_new_session``) and is NOT tied to this process's lifetime, so a
        server restart leaves it running.
        """
        raw = (message or "").strip()
        if not raw:
            raise ValueError("empty message")
        if self.is_running():
            raise RuntimeError("the agent is already working on the previous message")
        steps = self.command_chain(raw)
        # Persist how to rebuild this session so the supervisor (and any later
        # --resume) can reconstruct it without the web server's in-memory state.
        (self.work / JOB_SPEC_NAME).write_text(json.dumps(self.job_spec(), indent=2))
        # Seed status so the UI flips to "running" instantly, before the
        # supervisor has booted and written its pid/heartbeat.
        self.write_status(
            state="running",
            terminal=False,
            steps=steps,
            step_index=0,
            current_step=steps[0],
            attempts=0,
            message=raw[:240],
            pid=None,
            heartbeat=time.time(),
            launched=time.time(),
            started=time.time(),
            error=None,
            reason=None,
        )
        self._turn_log_offset = None
        self._live_cache = None
        self._job_proc = self._spawn_supervisor()

    def _spawn_supervisor(self, resume: bool = False) -> subprocess.Popen:
        argv = [sys.executable, "-m", "src.studio_job", "--work", str(self.work)]
        if resume:
            argv.append("--resume")
        log = (self.work / "studio_job.log").open("ab")
        try:
            return subprocess.Popen(
                argv,
                cwd=str(ROOT),
                env={**os.environ, **self._env()},
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                # Detach: NOT --die-with-parent, NOT in our process group — a
                # server restart must leave this supervisor (and its agent)
                # running; they reparent to init and a new server re-adopts them.
                start_new_session=True,
            )
        finally:
            log.close()

    def resume(self) -> bool:
        """Relaunch the supervisor to finish a crashed turn's pipeline. Returns
        whether a resume was started."""
        if not self.is_resumable():
            return False
        st = self.read_status() or {}
        self.write_status(
            relaunches=int(st.get("relaunches") or 0) + 1,
            pid=None,
            heartbeat=time.time(),
            launched=time.time(),
        )
        self._turn_log_offset = None
        self._live_cache = None
        self._job_proc = self._spawn_supervisor(resume=True)
        return True

    def stop(self) -> bool:
        """Kill the running turn, if any, and record it as a deliberate stop.

        Kills the supervisor (its sandbox is ``--die-with-parent``, so the agent
        dies with it) plus, belt-and-suspenders, any sandbox still bound to this
        workspace. SIGKILLing a bwrap takes its whole PID namespace with it. The
        status is marked ``stopped`` (terminal) so the pump won't resume it and
        the UI doesn't read a deliberate cancel as a crash."""
        killed = False
        if self._job_proc is not None and self._job_proc.poll() is None:
            try:
                self._job_proc.kill()
                killed = True
            except OSError:
                pass
        for pid in {self._supervisor_pid(), *self._sandbox_pids()}:
            if not pid or not _pid_alive(pid):
                continue
            try:
                os.kill(pid, signal.SIGKILL)
                killed = True
            except (OSError, ProcessLookupError):
                pass
        self._job_proc = None
        if self.read_status() is not None:
            self.write_status(
                state="stopped", terminal=True, error=None, finished=time.time()
            )
        return killed

    def turn_status(self) -> dict | None:
        """Status snapshot for the UI, reconciled against live ground truth.

        A ``running`` status whose supervisor has died without recording an exit
        is reported as ``unknown`` (it will be resumed by the pump); everything
        else passes through as written.
        """
        st = self.read_status()
        if not st:
            return None
        if st.get("state") == "running" and not self.is_running():
            return {
                **st,
                "state": "unknown",
                "error": (
                    "the writeup turn is no longer running but did not record an "
                    "exit; it will be resumed automatically."
                ),
            }
        return st

    def state(self) -> dict:
        """Snapshot for the UI header / polling."""
        return {
            "work_dir": str(self.work),
            "model": self.model,
            "thinking": self.thinking,
            "running": self.is_running(),
            "turn_status": self.turn_status(),
        }


class StudioSession(DocAgentSession):
    """One human+agent co-writing session over a single completed run.

    The run is mounted read-only at ``/source``; the agent edits
    ``final_writeup.md`` in a persistent workspace under
    ``outputs/06_blogpost_studio/<run>/``.
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
        super().__init__(
            work_dir or default_work_dir(self.run_dir),
            model=model,
            thinking=thinking,
            env_text=env_text,
            # collaboration + writing-standards prompt, constant for the session
            system_prompt=render("studio_system.md.j2"),
        )
        audit_agent.stage_reference_docs(self.work, self.run_dir)

    @property
    def doc_path(self) -> Path:
        return self.work / DOC_NAME

    def _expand(self, message: str) -> str:
        return expand_command(message)

    def _next_chain(self, message: str) -> str | None:
        head = message.partition(" ")[0].lower()
        return CHAIN_AFTER.get(head)

    def job_spec(self) -> dict:
        return {
            "module": "src.blogpost_studio",
            "cls": "StudioSession",
            "kwargs": {"run_dir": str(self.run_dir), "work_dir": str(self.work)},
            "model": self.model,
            "thinking": self.thinking,
        }

    def _argv(self, prompt: str) -> list[str]:
        return sandbox.build_argv(
            self.work,
            self._inner_argv(prompt),
            extra_ro_dest_binds=((str(self.run_dir), "/source"),),
        )

    def plots(self) -> list[str]:
        """Figure files (.png/.pdf) the agent has produced under final_plots/."""
        return audit_agent.list_plots(self.work)

    def reset(self) -> None:
        """Delete this run's draft: the document, conversation, figures, and
        anything else the agent created — the workspace is re-staged fresh.
        Refuses while a turn is running."""
        if self.is_running():
            raise RuntimeError("stop the running turn before deleting the draft")
        shutil.rmtree(self.work, ignore_errors=True)
        self._clear_session_state()
        audit_agent.stage_reference_docs(self.work, self.run_dir)

    def state(self) -> dict:
        return {
            **super().state(),
            "run_dir": str(self.run_dir),
            "run_name": self.run_dir.name,
        }
