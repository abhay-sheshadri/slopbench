#!/usr/bin/env python3
"""Run the pi coding agent in lightweight bubblewrap sandboxes — no Docker.

One sandbox per run. The run's output directory *is* the agent's ``/workspace``
(bind-mounted read-write), so there is no image to build, no container to manage,
and no snapshot/copy-out step — artifacts land directly in the browsable run dir.
We seed the proposal + planner instructions there, inject secrets as environment
variables, run the agent (``goal`` or ``multi_phase`` mode), and write a manifest
when it finishes. See ``src/sandbox.py`` for the isolation details (GPU hidden,
host filesystem hidden, automatic process-tree teardown).

While a run is in flight its directory carries a ``.pi_transcripts/RUNNING``
marker and the agent appends to ``session.jsonl`` live, so ``src/agent_viewer.py``
can stream it straight off disk; when it finishes the marker is removed and the
manifest is the record. Concurrency is an asyncio semaphore.

Both modes start by building a plan (``/init-planner``); they differ in how the
plan is executed:
  - ``goal``        : a single persistent ``/goal`` on planner/OVERALL_PLAN.md
  - ``multi_phase`` : the ``/run-loop`` worker/reviewer/phase-planner loop

Runs are also resumable (``RunSpec.resume`` / ``--resume``). Because the run dir
*is* ``/workspace`` (and HOME is ``/workspace/.home``), all durable state already
lives in the run dir between sandbox invocations: ``planner/RUN_LOOP_STATE.json``
(segment/phase/stage + sub-agent session pointers) for ``multi_phase``, and the
persisted ``/goal`` state inside the execution session for ``goal``. Resuming
keeps the dir, skips ``/init-planner``, and continues the execution session
(``/run-loop resume`` or ``/goal resume``) where it left off.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from src import sandbox
from src.runner_utils import parse_env_text

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = sandbox.WORKSPACE
RUNNING_MARKER = ".pi_transcripts/RUNNING"
MODES = ("goal", "multi_phase")

# Each run is two separate pi sessions, written to distinct transcripts in the run
# dir: the planner runs first and hands the plan off via files in planner/
# (OVERALL_PLAN.md, ...); the execution session then starts clean and reads that
# plan off disk rather than inheriting the planner's conversation context.
PLANNER_SESSION = f"{WORKSPACE}/.pi_transcripts/planner.session.jsonl"
PLANNER_HTML = f"{WORKSPACE}/.pi_transcripts/planner.session.html"
SESSION = f"{WORKSPACE}/.pi_transcripts/session.jsonl"
HTML = f"{WORKSPACE}/.pi_transcripts/session.html"
PLANNER_COMMAND = "/init-planner"

# Written into each workspace so the agent never commits the injected secrets or
# our harness scratch dirs. The task tells agents not to override an existing
# .gitignore, so seeding it here makes this the canonical one.
WORKSPACE_GITIGNORE = """\
# Injected secrets - never commit.
.env
.env.*

# Harness scratch (agent HOME + transcripts), not part of the project's work.
.home/
.pi_transcripts/

# Caches / large artifacts.
__pycache__/
*.pyc
.cache/
huggingface/
*.safetensors
*.bin
*.gguf
"""


# --------------------------------------------------------------------------- #
# Prompts + per-phase commands
# --------------------------------------------------------------------------- #
def default_goal_prompt(proposal_file: str) -> str:
    return (
        "/goal Execute the plan in planner/OVERALL_PLAN.md to completion. The planner has already "
        "decomposed this project into segments and phases; treat planner/OVERALL_PLAN.md as the "
        "authoritative plan and work through every segment and phase it defines, in order, starting "
        "from planner/INSTRUCTIONS_SEGMENT_0_PHASE_0.md. Implement each phase's work, produce useful "
        "reviewable artifacts under writeups/, and verify results as you go. Do not stop after the "
        "first phase or declare success early. Keep iterating autonomously until the entire plan is "
        f"executed and the project objective (originally described in {proposal_file}) is fully "
        "satisfied, then verify the end state before marking the goal complete."
    )


def planner_initial_instructions(proposal_file: str) -> str:
    return (
        "# Initial Instructions\n\n"
        f"Read {proposal_file}. Create a concrete execution plan for completing the project. "
        "The plan should identify the core objective, decompose the work into useful segments/phases, "
        "call out risks and likely failure modes, and produce a strong first phase that makes real progress "
        "without trying to complete the entire project shallowly.\n"
    )


def execution_command(mode: str, run_loop_args: str = "") -> str:
    """The single command for the execution session (after planning)."""
    if mode == "goal":
        return default_goal_prompt("proposal.md")
    if mode == "multi_phase":
        return f"/run-loop {run_loop_args}".strip()
    raise ValueError(f"unknown mode {mode!r} (expected one of {MODES})")


def resume_command(mode: str, run_loop_args: str = "") -> str:
    """The command for resuming an execution session that already has progress."""
    if mode == "goal":
        return "/goal resume"
    if mode == "multi_phase":
        return f"/run-loop resume {run_loop_args}".strip()
    raise ValueError(f"unknown mode {mode!r} (expected one of {MODES})")


def sanitize_run_loop_state_for_resume(workspace: Path) -> bool:
    """Make a multi_phase ``RUN_LOOP_STATE.json`` resumable after a hard kill.

    The run-loop records the agent's PID for its liveness check, but the agent
    runs inside a ``--unshare-pid`` sandbox, so the recorded ``parentPid`` /
    ``activeChildPid`` are *namespaced* low numbers (e.g. 14). In a fresh resume
    sandbox those same low PIDs always belong to live kernel threads/init, so
    ``/run-loop resume`` sees the loop as "already running" and refuses to
    continue. Clear those PIDs and flip a ``running`` status to ``stopped`` so
    the resume actually proceeds. Returns True if the file was changed.
    """
    state_path = workspace / "planner" / "RUN_LOOP_STATE.json"
    if not state_path.exists():
        return False
    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    changed = False
    if state.get("status") == "running":
        state["status"] = "stopped"
        changed = True
    for key in ("parentPid", "activeChildPid"):
        if state.get(key) is not None:
            state[key] = None
            changed = True
    if changed:
        state_path.write_text(json.dumps(state, indent=2))
    return changed


def _write_manifest(
    workspace: Path, spec, status: str, runs: list, rls: int, resuming: bool
) -> None:
    """Write/overwrite the run manifest. Called at the START (status='running',
    so a resume immediately clears a stale terminal status from a prior run) and
    again at the END with the final status."""
    (workspace / ".pi_transcripts" / "manifest.json").write_text(
        json.dumps(
            {
                "mode": spec.mode,
                "model": spec.model,
                "proposal": spec.proposal,
                "status": status,
                "resumed": resuming,
                "runs": runs,
                "run_loop_sessions": rls,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _multiphase_final_status(workspace: Path, exit_status: str) -> str:
    """Final status for a multi_phase run, preferring the run-loop's own state so
    a run that exits WITHOUT completing the loop (killed, interrupted, or a
    resume that no-ops) is not mislabelled 'completed'."""
    if exit_status == "failed":
        return "failed"
    try:
        st = json.loads(
            (workspace / "planner" / "RUN_LOOP_STATE.json").read_text()
        ).get("status")
    except (OSError, json.JSONDecodeError, ValueError):
        return exit_status
    return {
        "complete": "completed",
        "error": "failed",
        "budget_exceeded": "budget_exceeded",
        "running": "stopped",
        "stopped": "stopped",
        "idle": "stopped",
    }.get(st, exit_status)


def is_resumable(workspace: Path, mode: str) -> bool:
    """Whether ``workspace`` holds enough state to resume a run of ``mode``.

    ``multi_phase`` resumes from ``planner/RUN_LOOP_STATE.json`` (current
    segment/phase/stage plus the sub-agent session pointers); ``goal`` resumes
    from the execution session file, which carries the persisted ``/goal`` state.
    """
    if not workspace.exists():
        return False
    if mode == "multi_phase":
        return (workspace / "planner" / "RUN_LOOP_STATE.json").exists()
    if mode == "goal":
        return (workspace / ".pi_transcripts" / "session.jsonl").exists()
    return False


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "run"


def run_name(mode: str, proposal: str) -> str:
    """Short human label for logging (the run dir is the real identity)."""
    return f"pi.{mode}.{slug(proposal)}.{uuid.uuid4().hex[:6]}"


# --------------------------------------------------------------------------- #
# Subprocess + sandbox helpers
# --------------------------------------------------------------------------- #
async def _run(
    argv: list[str], timeout: float | None = None, env: dict[str, str] | None = None
):
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", "host-timeout"
    return (
        proc.returncode,
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
    )


async def _sandbox_run(
    workspace: Path,
    inner: list[str],
    env: dict[str, str],
    *,
    command_timeout: int | None = None,
):
    """Run ``inner`` inside a bwrap sandbox over ``workspace``.

    The timeout is enforced *inside* the sandbox with coreutils ``timeout`` so the
    whole agent process tree is signalled; when that command exits, the sandbox's
    PID-namespace init (bwrap) exits too and the kernel reaps any stragglers. A
    slightly longer host-side timeout is a backstop that kills bwrap directly."""
    if command_timeout:
        inner = ["timeout", "-k", "5s", f"{command_timeout}s", *inner]
        host_timeout: float | None = command_timeout + 60
    else:
        host_timeout = None
    # The env is passed to the bwrap process (which forwards it into the sandbox),
    # never as --setenv args, so secrets don't appear in ps/proc on the host.
    argv = sandbox.build_argv(workspace, inner)
    return await _run(argv, timeout=host_timeout, env=env)


def fold_run_loop_sessions(workspace: Path) -> int:
    """Copy the run-loop sub-agent sessions (main-planner/worker/reviewer/
    phase-planner) into ``.pi_transcripts/run_loop_sessions`` so finished runs
    have them in one place. They already live in the run dir (under
    ``.home/.pi``); this just gives them stable, browsable names. Returns count."""
    state_path = workspace / "planner" / "RUN_LOOP_STATE.json"
    if not state_path.exists():
        return 0
    try:
        state = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0
    sessions = state.get("sessions") or {}
    targets: list[tuple[str, str]] = []
    if isinstance(sessions.get("mainPlanner"), str):
        targets.append(("main_planner", sessions["mainPlanner"]))
    for kind, label in (
        ("workers", "worker"),
        ("reviewers", "reviewer"),
        ("phasePlanners", "phase_planner"),
    ):
        mapping = sessions.get(kind) or {}
        if isinstance(mapping, dict):
            for key, path in mapping.items():
                if isinstance(path, str):
                    targets.append((f"{label}_{key.replace(':', '_')}", path))
    if not targets:
        return 0
    dest = workspace / ".pi_transcripts" / "run_loop_sessions"
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name, container_path in targets:
        src = sandbox.session_host_path(container_path, workspace)
        if src and src.exists():
            try:
                shutil.copyfile(src, dest / f"{name}.jsonl")
                copied += 1
            except OSError:
                pass
    return copied


# --------------------------------------------------------------------------- #
# Run orchestration
# --------------------------------------------------------------------------- #
@dataclass
class RunSpec:
    proposal: str
    proposal_text: str
    mode: str
    model: str
    out_dir: Path
    thinking: str = "xhigh"
    command_timeout: int | None = None
    run_loop_args: str = ""
    env_contents: str | None = None
    resume: bool = False


@dataclass
class RunResult:
    spec: RunSpec
    name: str
    status: str
    runs: list = field(default_factory=list)
    run_loop_sessions: int = 0
    agent_dir: str | None = None
    error: str | None = None


def _log(on_event, name: str, msg: str) -> None:
    if on_event:
        on_event(name, msg)
    else:
        print(f"[{name}] {msg}", flush=True)


async def run_one(spec: RunSpec, *, sem: asyncio.Semaphore, on_event=None) -> RunResult:
    name = run_name(spec.mode, spec.proposal)
    ws = spec.out_dir
    async with sem:
        runs: list = []
        status = "completed"
        marker = ws / RUNNING_MARKER
        try:
            resuming = spec.resume and is_resumable(ws, spec.mode)
            if spec.resume and not resuming:
                _log(
                    on_event,
                    name,
                    "resume requested but no resumable state found; starting fresh",
                )

            if resuming:
                # Keep the existing run dir intact: planner/RUN_LOOP_STATE.json,
                # the completed phase_segment_*/ dirs and the sub-agent sessions
                # under .home/.pi all live here and are the resume's source of
                # truth. Only (re)create harness scaffolding that may be missing.
                for sub in ("planner", ".pi_transcripts", ".home"):
                    (ws / sub).mkdir(parents=True, exist_ok=True)
                if not (ws / "proposal.md").exists():
                    (ws / "proposal.md").write_text(spec.proposal_text)
                if not (ws / "planner" / "INITIAL_INSTRUCTIONS.md").exists():
                    (ws / "planner" / "INITIAL_INSTRUCTIONS.md").write_text(
                        planner_initial_instructions("proposal.md")
                    )
                if not (ws / ".gitignore").exists():
                    (ws / ".gitignore").write_text(WORKSPACE_GITIGNORE)
                if spec.mode == "multi_phase" and sanitize_run_loop_state_for_resume(
                    ws
                ):
                    _log(
                        on_event,
                        name,
                        "sanitized RUN_LOOP_STATE for resume (cleared stale namespaced PIDs)",
                    )
            else:
                # Fresh run dir == fresh sandbox (mirrors a fresh container).
                if ws.exists():
                    shutil.rmtree(ws)
                for sub in ("planner", ".pi_transcripts", ".home"):
                    (ws / sub).mkdir(parents=True, exist_ok=True)
                (ws / "proposal.md").write_text(spec.proposal_text)
                (ws / "planner" / "INITIAL_INSTRUCTIONS.md").write_text(
                    planner_initial_instructions("proposal.md")
                )
                (ws / ".gitignore").write_text(WORKSPACE_GITIGNORE)

            marker.write_text("")  # live marker (removed when the run ends)
            # Replace any stale terminal status from a prior run immediately, so
            # the viewer reflects an in-progress (re)start even before it ends.
            _write_manifest(ws, spec, "running", runs, 0, resuming)

            overrides = parse_env_text(spec.env_contents) if spec.env_contents else {}
            env = sandbox.default_env(overrides)
            # Provide credentials BOTH as environment variables (forwarded into the
            # sandbox by bwrap) and as a .env file in the workspace: research code
            # commonly loads one via python-dotenv, and it makes credential
            # presence unambiguous to the agent. The .gitignore keeps it out of
            # commits, and outputs/ is gitignored at the repo root. Re-injected on
            # resume too (secrets are never written to the manifest).
            if spec.env_contents:
                (ws / ".env").write_text(spec.env_contents)

            _log(
                on_event,
                name,
                f"{'resume' if resuming else 'start'} mode={spec.mode} "
                f"proposal={spec.proposal} -> {ws}",
            )
            if resuming:
                # The plan already exists; skip /init-planner and continue the
                # execution session from where it stopped (segment/phase/stage
                # for multi_phase, persisted /goal state for goal).
                phases = [
                    (
                        "execution",
                        SESSION,
                        resume_command(spec.mode, spec.run_loop_args),
                    ),
                ]
            else:
                # Two separate sessions: plan first, then execute from a clean session.
                phases = [
                    ("planner", PLANNER_SESSION, PLANNER_COMMAND),
                    (
                        "execution",
                        SESSION,
                        execution_command(spec.mode, spec.run_loop_args),
                    ),
                ]
            for index, (phase, session, cmd) in enumerate(phases):
                _log(on_event, name, f"{phase}: {cmd.split(chr(10))[0][:48]}")
                inner = [
                    "pi",
                    "-p",
                    "--session",
                    session,
                    "--model",
                    spec.model,
                    "--thinking",
                    spec.thinking,
                    "--mode",
                    "json",
                    cmd,
                ]
                rc, _, cerr = await _sandbox_run(
                    ws, inner, env, command_timeout=spec.command_timeout
                )
                runs.append(
                    {"index": index, "phase": phase, "prompt": cmd, "returncode": rc}
                )
                if rc != 0:
                    status = "failed"
                    _log(
                        on_event, name, f"{phase} failed rc={rc}: {cerr.strip()[-200:]}"
                    )
                    break

            # Finalize: export each transcript that exists, gather sub-agent sessions.
            for session, html in ((PLANNER_SESSION, PLANNER_HTML), (SESSION, HTML)):
                host_session = ws / ".pi_transcripts" / Path(session).name
                if host_session.exists():
                    await _sandbox_run(ws, ["pi", "--export", session, html], env)
            rls = fold_run_loop_sessions(ws)

            # For multi_phase, trust the run-loop's own state over the pi exit
            # code: a clean exit (rc==0) doesn't mean the loop finished.
            if spec.mode == "multi_phase":
                status = _multiphase_final_status(ws, status)

            _write_manifest(ws, spec, status, runs, rls, resuming)
            _log(
                on_event, name, f"done status={status} run_loop_sessions={rls} -> {ws}"
            )
            return RunResult(spec, name, status, runs, rls, str(ws))
        except Exception as exc:  # noqa: BLE001 - record and keep other runs going
            return RunResult(
                spec, name, "error", runs, 0, None, f"{type(exc).__name__}: {exc}"
            )
        finally:
            marker.unlink(missing_ok=True)


async def run_many(
    specs: list[RunSpec], *, max_concurrent: int = 2, on_event=None
) -> list[RunResult]:
    if sandbox.available() is None:
        raise SystemExit(
            "bubblewrap (bwrap) is not installed. Install it with "
            "`sudo apt-get install -y bubblewrap` (see scripts/setup_machine.sh)."
        )
    sem = asyncio.Semaphore(max(1, max_concurrent))
    return await asyncio.gather(
        *(run_one(s, sem=sem, on_event=on_event) for s in specs)
    )


# --------------------------------------------------------------------------- #
# Small CLI (mostly for direct testing; experiments call run_many directly)
# --------------------------------------------------------------------------- #
def _read_env() -> str | None:
    env = ROOT / ".env"
    return env.read_text() if env.exists() else None


def main() -> None:
    from src import DEFAULT_MODEL

    parser = argparse.ArgumentParser(
        description="Run the pi agent in a bwrap sandbox (no Docker)."
    )
    parser.add_argument("--proposal-file", type=Path, required=True)
    parser.add_argument(
        "--proposal-name",
        default=None,
        help="Label for the run (defaults to file stem).",
    )
    parser.add_argument("--modes", nargs="+", default=list(MODES), choices=list(MODES))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--thinking", default="xhigh")
    parser.add_argument("--output-dir", default="outputs/agent_runner")
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=None,
        help="Per-phase wall-clock cap in seconds. Default: no timeout (run unbounded).",
    )
    parser.add_argument("--run-loop-args", default="")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume each run from its existing output dir instead of starting fresh.",
    )
    parser.add_argument("--max-concurrent", type=int, default=2)
    args = parser.parse_args()

    proposal_name = args.proposal_name or args.proposal_file.stem
    text = args.proposal_file.read_text()
    base = (ROOT / args.output_dir).resolve()
    env = _read_env()
    specs = [
        RunSpec(
            proposal=proposal_name,
            proposal_text=text,
            mode=mode,
            model=args.model,
            out_dir=base / f"{proposal_name}_{mode}",
            thinking=args.thinking,
            command_timeout=args.command_timeout,
            run_loop_args=args.run_loop_args,
            env_contents=env,
            resume=args.resume,
        )
        for mode in args.modes
    ]
    print(f"Running {proposal_name} in modes {args.modes} (model={args.model})")
    results = asyncio.run(run_many(specs, max_concurrent=args.max_concurrent))
    for r in results:
        print(
            f"  {r.spec.mode:11} {r.status:9} sub-sessions={r.run_loop_sessions} -> {r.agent_dir}"
        )


if __name__ == "__main__":
    main()
