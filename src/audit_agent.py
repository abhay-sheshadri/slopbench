"""Audit-agent runner: run a read-only ``pi`` agent over a finished run and have
it produce artifacts (a write-up, figures, …) in a fresh writable working dir.

Shared infrastructure for the experiments that audit a completed run
(``experiments/04_blogpost_gen``, ``experiments/05_figures_gen``, …):

  - the source run is bind-mounted READ-ONLY at ``/source`` (the agent can read
    every file — code, transcripts, results — but physically cannot modify it),
  - a fresh writable working dir is the agent's CWD at ``/workspace``,
  - matplotlib / pandas / numpy from the project venv are on PATH so it can plot.

Each experiment supplies its own task PROMPT and decides which artifacts to keep.
``generate()`` is generic: it stages the two reference docs into the CWD, runs the
agent to completion, and returns the work dir + the path to the agent's own session
transcript (so the trajectory can be audited).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from src import DEFAULT_GPT_MODEL, oversight, sandbox

ROOT = Path(__file__).resolve().parents[1]

# Write-ups and figures are writing/design tasks, so default to a GPT model.
DEFAULT_MODEL = DEFAULT_GPT_MODEL
THINKING_DEFAULT = "high"
DEFAULT_TIMEOUT = None  # no timeout by default: the agent runs to completion

# Run-dir detection lives in the shared oversight module (re-exported for callers).
is_run_dir = oversight.is_run_dir


# --------------------------------------------------------------------------- #
# Reference docs staged into the agent's CWD
# --------------------------------------------------------------------------- #
def structure_doc() -> str:
    """RUN_DIR_STRUCTURE.md — the general layout, staged into the CWD.

    The text is the shared source of truth in :mod:`src.oversight`.
    """
    return oversight.run_layout_doc()


def trace_index(run_dir: Path) -> str:
    """TRACE_INDEX.md — concrete /source paths that exist for THIS run.

    Built from the shared :func:`src.oversight.key_locations`.
    """
    return oversight.trace_index(run_dir)


# --------------------------------------------------------------------------- #
# Run the agent
# --------------------------------------------------------------------------- #
def _env(env_text: str | None) -> dict[str, str]:
    # HOME=/workspace/.home: the writable CWD, so ~/.pi sub-agent sessions land
    # in the run dir automatically.
    return oversight.oversight_env(sandbox.HOME, env_text)


def list_plots(work_dir: str | Path) -> list[str]:
    """The .png/.pdf figures the agent produced under ``work_dir/final_plots``."""
    p = Path(work_dir) / "final_plots"
    if not p.is_dir():
        return []
    return sorted(f.name for f in p.glob("*") if f.suffix.lower() in (".png", ".pdf"))


def stage_reference_docs(work_dir: str | Path, run_dir: str | Path) -> None:
    """Write the two reference docs (RUN_DIR_STRUCTURE.md / TRACE_INDEX.md) and
    create the output dirs the agent writes into. Call once before the first
    ``run_pi`` so every later turn (e.g. a resume) sees the same docs."""
    work = Path(work_dir).resolve()
    run_dir = Path(run_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    (work / "final_plots").mkdir(parents=True, exist_ok=True)
    (work / "RUN_DIR_STRUCTURE.md").write_text(structure_doc())
    (work / "TRACE_INDEX.md").write_text(trace_index(run_dir))


def run_pi(
    run_dir: str | Path,
    work_dir: str | Path,
    prompt: str,
    *,
    session: str = "session.jsonl",
    log_name: str | None = None,
    model: str | None = None,
    thinking: str = THINKING_DEFAULT,
    timeout: int | None = DEFAULT_TIMEOUT,
    env_text: str | None = None,
    on_log=None,
) -> dict:
    """Run one ``pi`` turn (source mounted read-only at /source, CWD = ``work_dir``)
    with the given ``prompt``. Returns ``{returncode, timed_out, session, work_dir}``.

    ``session`` is the session file (relative to the CWD). Reusing an existing
    session file resumes that conversation with ``prompt`` as the next user turn —
    this is how a reviewer's findings are fed back to the author. Use a fresh name
    for an independent agent (e.g. the reviewer).
    """
    run_dir = Path(run_dir).resolve()
    work = Path(work_dir).resolve()
    if sandbox.available() is None:
        raise RuntimeError("bubblewrap (bwrap) is not installed")
    if not is_run_dir(run_dir):
        raise ValueError(
            f"{run_dir} is not a run/project dir (no .pi_transcripts/ found)"
        )
    work.mkdir(parents=True, exist_ok=True)
    (work / "final_plots").mkdir(parents=True, exist_ok=True)

    inner = oversight.pi_inner_argv(
        f"{sandbox.WORKSPACE}/{session}", model or DEFAULT_MODEL, thinking, prompt
    )
    argv = sandbox.build_argv(
        work, inner, extra_ro_dest_binds=((str(run_dir), "/source"),)
    )
    log_name = log_name or f"agent_stdout_{Path(session).stem}.log"
    timed_out = False
    with (work / log_name).open("wb") as log:
        proc = subprocess.Popen(
            argv,
            env=_env(env_text),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        deadline = (time.time() + timeout) if timeout and timeout > 0 else None
        while proc.poll() is None:
            if deadline is not None and time.time() > deadline:
                proc.kill()
                timed_out = True
                break
            if on_log:
                on_log(_progress(work))
            time.sleep(5)
    return {
        "returncode": proc.poll(),
        "timed_out": timed_out,
        "session": str(work / session),
        "work_dir": str(work),
    }


def generate(
    run_dir: str | Path,
    work_dir: str | Path,
    prompt: str,
    *,
    model: str | None = None,
    thinking: str = THINKING_DEFAULT,
    timeout: int | None = DEFAULT_TIMEOUT,
    env_text: str | None = None,
    on_log=None,
) -> dict:
    """Stage the reference docs and run a single audit-agent turn to completion.

    Convenience wrapper around :func:`stage_reference_docs` + :func:`run_pi` for
    callers that only need one turn (e.g. ``experiments/05_figures_gen``).
    """
    stage_reference_docs(work_dir, run_dir)
    return run_pi(
        run_dir,
        work_dir,
        prompt,
        session="session.jsonl",
        log_name="agent_stdout.log",
        model=model,
        thinking=thinking,
        timeout=timeout,
        env_text=env_text,
        on_log=on_log,
    )


def _progress(work: Path) -> str:
    sess = work / "session.jsonl"
    size = sess.stat().st_size if sess.exists() else 0
    return f"  …agent working: session={size}B plots={len(list_plots(work))}"
