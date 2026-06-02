from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys as _sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in _sys.path:
    _sys.path.insert(0, str(ROOT))

from src import DEFAULT_GPT_MODEL
from src import DEFAULT_MODEL as DEFAULT_CLAUDE_MODEL  # noqa: E402
from src.runner_utils import load_env_file  # noqa: E402

PROJECT_IDEAS_DIR = ROOT / "proposals"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "01_eval_planning"
SKIPPED_PROJECT_PREFIXES = ("all_souls", "allsouls_")

REQUIRED_PLANNER_FILES = (
    "OVERALL_PLAN.md",
    "INSTRUCTIONS_SEGMENT_0_PHASE_0.md",
    "RUBRIC_SEGMENT_0_PHASE_0.md",
)
PLANNER_FINAL_RESPONSE = (
    "I have completed the plan. OVERALL_PLAN.md, "
    "INSTRUCTIONS_SEGMENT_0_PHASE_0.md, and "
    "RUBRIC_SEGMENT_0_PHASE_0.md have been written and reviewed."
)

PLANNER_GUIDANCE = """# Planner Guidance

Create and maintain a concrete execution plan for the task.

Required files:
- OVERALL_PLAN.md: high-level approach, risks, sequencing, and acceptance criteria.
- INSTRUCTIONS_SEGMENT_0_PHASE_0.md: instructions for the first executable phase. It must start with YAML frontmatter:
- RUBRIC_SEGMENT_0_PHASE_0.md: concrete success criteria, required checks, likely failure modes, and conditions that should block reviewer approval for the first phase.

---
name: "short_underscore_name"
description: "One or two sentence description of this phase"
---

# Instructions

...

Planning guidance:
- Write the required files under the local `planner/` directory. Do not only describe the plan in chat.
- Before finishing, inspect the files you wrote and make sure all three required files exist and are non-empty.
- Break the work into reasonably self-contained segments. Prefer more focused segments when one segment would mix distinct objectives, require a long-running context, or combine weakly related work.
- Make phase instructions detailed enough for a fresh agent to complete the phase autonomously. Include the motivation, objective, relevant constraints, acceptance criteria, and important context from the original task.
- Keep instructions self-contained. Workers receive the current phase instructions and OVERALL_PLAN.md; they should not need to read prior instruction files.
- Do not make the first phase too small, but avoid "do everything" phases that are likely to produce shallow work.
- If useful skills should be used for a phase, mention them in that phase's instructions.
- You are only planning and decomposing the work. Do not start implementing the task.

When the plan and first phase are complete, end with this exact string:
I have completed the plan. OVERALL_PLAN.md, INSTRUCTIONS_SEGMENT_0_PHASE_0.md, and RUBRIC_SEGMENT_0_PHASE_0.md have been written and reviewed.
"""


@dataclass(frozen=True)
class PlannerJob:
    project: str
    project_file: Path
    model_family: str
    model: str
    attempt: int
    work_dir: Path


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug or "unnamed"


def list_projects() -> list[str]:
    return sorted(
        path.stem
        for path in PROJECT_IDEAS_DIR.glob("*.md")
        if not any(path.stem.startswith(prefix) for prefix in SKIPPED_PROJECT_PREFIXES)
    )


def filter_projects_by_kind(
    projects: list[str], conceptual_only: bool, empirical_only: bool
) -> list[str]:
    if conceptual_only:
        return [project for project in projects if project.startswith("conceptual_")]
    if empirical_only:
        return [project for project in projects if project.startswith("empirical_")]
    return projects


def planner_dir_complete(work_dir: Path) -> bool:
    planner_dir = work_dir / "planner"
    return all(
        (planner_dir / name).exists() and (planner_dir / name).read_text().strip()
        for name in REQUIRED_PLANNER_FILES
    )


def build_initial_instructions(project_name: str, project_text: str) -> str:
    return f"""# Initial Instructions

You are planning an autonomous research project from the project idea below.

Create a concrete execution plan for an autonomous worker agent. The
plan should decompose the project into useful segments/phases, identify risks
and likely failure modes, and produce a strong first phase that starts making
real progress without trying to complete the entire project shallowly.

You are running from the attempt work directory. Write the planner outputs to
the relative paths `planner/OVERALL_PLAN.md`,
`planner/INSTRUCTIONS_SEGMENT_0_PHASE_0.md`, and
`planner/RUBRIC_SEGMENT_0_PHASE_0.md`.

{PLANNER_GUIDANCE}

# Project Idea: {project_name}

{project_text.strip()}
"""


def prepare_work_dir(job: PlannerJob) -> None:
    if job.work_dir.exists():
        shutil.rmtree(job.work_dir)

    planner_dir = job.work_dir / "planner"
    planner_dir.mkdir(parents=True, exist_ok=True)

    project_text = job.project_file.read_text()
    (job.work_dir / "project_idea.md").write_text(project_text)
    (planner_dir / "PLANNER_GUIDANCE.md").write_text(PLANNER_GUIDANCE)
    (planner_dir / "INITIAL_INSTRUCTIONS.md").write_text(
        build_initial_instructions(job.project, project_text)
    )


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def transcript_paths(work_dir: Path) -> dict[str, Path]:
    transcript_dir = work_dir / "pi_transcripts"
    return {
        "dir": transcript_dir,
        "session": transcript_dir / "init_planner.session.jsonl",
        "events": transcript_dir / "pi_events.jsonl",
        "stderr": transcript_dir / "pi.stderr.log",
        "html": transcript_dir / "init_planner.html",
        "manifest": transcript_dir / "manifest.json",
    }


def iter_jsonl(path: Path):
    if not path.exists():
        return
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def reviewer_subagent_success(work_dir: Path) -> bool:
    for path in (
        transcript_paths(work_dir)["events"],
        transcript_paths(work_dir)["session"],
    ):
        for event in iter_jsonl(path) or ():
            for item in walk_json(event):
                details = (
                    item.get("details") if item.get("toolName") == "subagent" else None
                )
                args = item.get("args") if item.get("toolName") == "subagent" else None
                partial_result = item.get("partialResult")
                if isinstance(partial_result, dict):
                    details = partial_result.get("details", details)
                    args = partial_result.get("args", args)
                if (
                    isinstance(details, dict)
                    and details.get("agent") == "research-plan-reviewer"
                    and details.get("exitCode") == 0
                ):
                    return True
                if (
                    isinstance(args, dict)
                    and args.get("agent") == "research-plan-reviewer"
                    and isinstance(details, dict)
                    and details.get("exitCode") == 0
                ):
                    return True
    return False


def planner_final_response_seen(work_dir: Path) -> bool:
    for path in (
        transcript_paths(work_dir)["events"],
        transcript_paths(work_dir)["session"],
    ):
        for event in iter_jsonl(path) or ():
            for item in walk_json(event):
                if item.get("role") != "assistant":
                    continue
                for content in item.get("content", []):
                    if isinstance(content, dict) and content.get("type") == "text":
                        if PLANNER_FINAL_RESPONSE in str(content.get("text", "")):
                            return True
    return False


def progress_signature(work_dir: Path) -> tuple[tuple[str, int, int], ...]:
    paths = transcript_paths(work_dir)
    watched = [
        paths["session"],
        paths["events"],
        paths["stderr"],
        *(work_dir / "planner" / name for name in REQUIRED_PLANNER_FILES),
    ]
    signature = []
    for path in watched:
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        signature.append(
            (str(path.relative_to(work_dir)), stat.st_size, stat.st_mtime_ns)
        )
    return tuple(signature)


async def terminate_process_group(
    proc: asyncio.subprocess.Process, timeout: int = 30
) -> int:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return await proc.wait()
    except PermissionError:
        proc.terminate()

    try:
        return await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            proc.kill()
        return await proc.wait()


def prefer_local_abhay_pi_dir() -> None:
    local_abhay_pi_dir = ROOT / "abhay-pi"
    if local_abhay_pi_dir.exists() and not os.environ.get("ABHAY_PI_DIR"):
        os.environ["ABHAY_PI_DIR"] = str(local_abhay_pi_dir)


def clean_selected_outputs(
    output_dir: Path, selected_projects: list[str], model_specs: list[tuple[str, str]]
) -> None:
    for project in selected_projects:
        for model_family, _model in model_specs:
            path = output_dir / safe_slug(project) / safe_slug(model_family)
            if path.exists():
                shutil.rmtree(path)
                print(f"cleaned previous planner output: {path}")


def attempt_status(work_dir: Path) -> str:
    complete = planner_dir_complete(work_dir)
    reviewer_complete = reviewer_subagent_success(work_dir)
    final_seen = planner_final_response_seen(work_dir)
    if complete and reviewer_complete and final_seen:
        return "ok"
    if complete and reviewer_complete:
        return "complete_missing_final_response"
    if complete:
        return "complete_missing_reviewer"

    status_path = work_dir / "run_status.json"
    if status_path.exists():
        try:
            return str(json.loads(status_path.read_text()).get("status") or "failed")
        except json.JSONDecodeError:
            return "failed"

    paths = transcript_paths(work_dir)
    if paths["events"].exists() or paths["session"].exists():
        return "in_progress_or_stale"
    return "pending"


def print_status(output_dir: Path) -> None:
    if not output_dir.exists():
        print(f"No output directory: {output_dir}")
        return

    rows: list[tuple[str, str, str, str]] = []
    for project_dir in sorted(path for path in output_dir.iterdir() if path.is_dir()):
        for model_dir in sorted(
            path for path in project_dir.iterdir() if path.is_dir()
        ):
            for attempt_dir in sorted(
                path for path in model_dir.iterdir() if path.is_dir()
            ):
                if attempt_dir.name.startswith("attempt_"):
                    rows.append(
                        (
                            project_dir.name,
                            model_dir.name,
                            attempt_dir.name,
                            attempt_status(attempt_dir),
                        )
                    )

    if not rows:
        print(f"No planner attempts found under {output_dir}")
        return

    counts: dict[str, int] = {}
    for _project, _model, _attempt, status in rows:
        counts[status] = counts.get(status, 0) + 1

    print(f"Output: {output_dir}")
    print(
        "Summary: "
        + ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))
    )
    print()
    for project, model, attempt, status in rows:
        print(f"{status:32} {project}/{model}/{attempt}")


async def run_job(
    job: PlannerJob,
    pi_bin: str,
    thinking: str,
    complete_grace_seconds: int,
    no_progress_timeout_seconds: int,
) -> bool:
    prepare_work_dir(job)
    paths = transcript_paths(job.work_dir)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    session_path = paths["session"]
    cmd = [
        pi_bin,
        "-p",
        "/init-planner",
        "--session",
        str(session_path),
        "--model",
        job.model,
        "--thinking",
        thinking,
        "--mode",
        "json",
    ]

    metadata = {
        "project": job.project,
        "model_family": job.model_family,
        "model": job.model,
        "attempt": job.attempt,
        "work_dir": str(job.work_dir),
        "session_path": str(session_path),
        "transcript_dir": str(paths["dir"]),
        "json_events_path": str(paths["events"]),
        "stderr_path": str(paths["stderr"]),
        "html_export_path": str(paths["html"]),
        "command": cmd,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(job.work_dir / "run_metadata.json", metadata)
    write_json(paths["manifest"], metadata)
    print(
        f"run: {job.project} {job.model_family} attempt {job.attempt} -> {job.work_dir}"
    )

    terminated_after_complete = False
    terminated_after_no_progress = False
    with paths["events"].open("wb") as stdout, paths["stderr"].open("wb") as stderr:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=job.work_dir,
            stdout=stdout,
            stderr=stderr,
            env=os.environ.copy(),
            start_new_session=True,
        )
        complete_since: float | None = None
        last_progress = time.monotonic()
        last_signature = progress_signature(job.work_dir)
        while True:
            try:
                returncode = await asyncio.wait_for(proc.wait(), timeout=5)
                break
            except asyncio.TimeoutError:
                now = time.monotonic()
                signature = progress_signature(job.work_dir)
                if signature != last_signature:
                    last_signature = signature
                    last_progress = now

                complete = planner_dir_complete(job.work_dir)
                reviewer_complete = reviewer_subagent_success(job.work_dir)
                final_seen = planner_final_response_seen(job.work_dir)
                if complete and reviewer_complete and final_seen:
                    complete_since = complete_since or time.monotonic()
                    if time.monotonic() - complete_since >= complete_grace_seconds:
                        terminated_after_complete = True
                        returncode = await terminate_process_group(proc)
                        break
                else:
                    complete_since = None
                    if (
                        no_progress_timeout_seconds > 0
                        and now - last_progress >= no_progress_timeout_seconds
                    ):
                        terminated_after_no_progress = True
                        returncode = await terminate_process_group(proc)
                        break

    complete = planner_dir_complete(job.work_dir)
    reviewer_complete = reviewer_subagent_success(job.work_dir)
    final_seen = planner_final_response_seen(job.work_dir)
    html_exported = False
    html_export_error = None
    if session_path.exists() and session_path.stat().st_size > 0:
        export_proc = subprocess.run(
            [pi_bin, "--export", str(session_path), str(paths["html"])],
            cwd=job.work_dir,
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        html_exported = export_proc.returncode == 0 and paths["html"].exists()
        if not html_exported:
            html_export_error = (
                export_proc.stderr.strip() or f"exit {export_proc.returncode}"
            )

    ok = (
        complete
        and reviewer_complete
        and final_seen
        and (returncode == 0 or terminated_after_complete)
    )
    status = {
        **metadata,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "returncode": returncode,
        "planner_files_complete": complete,
        "reviewer_subagent_success": reviewer_complete,
        "planner_final_response_seen": final_seen,
        "terminated_after_complete": terminated_after_complete,
        "terminated_after_no_progress": terminated_after_no_progress,
        "session_exists": session_path.exists(),
        "session_size_bytes": (
            session_path.stat().st_size if session_path.exists() else 0
        ),
        "html_exported": html_exported,
        "html_export_error": html_export_error,
        "status": "ok" if ok else "failed",
    }
    write_json(job.work_dir / "run_status.json", status)
    write_json(paths["manifest"], status)

    if ok:
        print(f"ok: {job.project} {job.model_family} attempt {job.attempt}")
        return True
    print(f"failed: {job.project} {job.model_family} attempt {job.attempt}")
    return False


async def run_all(args: argparse.Namespace) -> int:
    # Prefer the values in .env over anything already in the ambient shell so a
    # stale/invalid key (e.g. an old OPENAI_API_KEY) can't shadow the correct
    # one and cause 401s.
    load_env_file(ROOT / ".env", override=True)
    prefer_local_abhay_pi_dir()

    output_dir = (
        args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    )
    output_dir = output_dir.resolve()

    available_projects = list_projects()
    selected_projects = args.projects or available_projects
    unknown = sorted(set(selected_projects) - set(available_projects))
    if unknown:
        raise SystemExit(f"Unknown project(s): {', '.join(unknown)}")
    selected_projects = filter_projects_by_kind(
        selected_projects,
        conceptual_only=args.conceptual_only,
        empirical_only=args.empirical_only,
    )
    if not selected_projects:
        raise SystemExit("No project ideas matched the selected filters.")

    model_specs: list[tuple[str, str]] = []
    if "claude" in args.models:
        model_specs.append(("claude", args.claude_model))
    if "gpt" in args.models:
        model_specs.append(("gpt", args.gpt_model))

    clean_selected_outputs(output_dir, selected_projects, model_specs)

    jobs = [
        PlannerJob(
            project=project,
            project_file=PROJECT_IDEAS_DIR / f"{project}.md",
            model_family=model_family,
            model=model,
            attempt=attempt,
            work_dir=output_dir
            / safe_slug(project)
            / safe_slug(model_family)
            / f"attempt_{attempt:02d}",
        )
        for project in selected_projects
        for model_family, model in model_specs
        for attempt in range(1, args.attempts + 1)
    ]

    print(f"Projects: {', '.join(selected_projects)}")
    print(f"Models: {', '.join(f'{family}={model}' for family, model in model_specs)}")
    print(f"Attempts per project/model: {args.attempts}")
    print(f"Jobs: {len(jobs)}")
    print(f"Output: {output_dir}")
    print(f"Pi binary: {args.pi_bin}")
    print()

    semaphore = asyncio.Semaphore(args.max_concurrent)

    async def guarded(job: PlannerJob) -> bool:
        async with semaphore:
            return await run_job(
                job=job,
                pi_bin=args.pi_bin,
                thinking=args.thinking,
                complete_grace_seconds=args.complete_grace_seconds,
                no_progress_timeout_seconds=args.no_progress_timeout_seconds,
            )

    results = await asyncio.gather(*(guarded(job) for job in jobs))
    failed = len([ok for ok in results if not ok])
    if failed:
        print(f"\n{failed} planner job(s) failed.")
        return 1
    print("\nAll planner jobs completed.")
    return 0


def default_pi_bin() -> str:
    local_abhay_pi = ROOT / "scripts" / "abhay-pi"
    if local_abhay_pi.exists():
        return str(local_abhay_pi)
    return shutil.which("abhay-pi") or shutil.which("pi") or "pi"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate one initial planner output for each selected proposal/model."
    )
    parser.add_argument(
        "--list", action="store_true", help="List project ideas and exit."
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print planner attempt status for the output directory and exit.",
    )
    parser.add_argument(
        "--projects", nargs="+", help="Project idea names to run. Default: all."
    )
    kind_group = parser.add_mutually_exclusive_group()
    kind_group.add_argument(
        "--conceptual-only",
        action="store_true",
        help="Run only project ideas whose filenames start with conceptual_.",
    )
    kind_group.add_argument(
        "--empirical-only",
        action="store_true",
        help="Run only project ideas whose filenames start with empirical_.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=["claude", "gpt"],
        default=["claude", "gpt"],
        help="Model families to run. Default: claude gpt.",
    )
    parser.add_argument("--claude-model", default=DEFAULT_CLAUDE_MODEL)
    parser.add_argument("--gpt-model", default=DEFAULT_GPT_MODEL)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--thinking", default="xhigh")
    parser.add_argument("--max-concurrent", type=int, default=1)
    parser.add_argument("--complete-grace-seconds", type=int, default=180)
    parser.add_argument("--no-progress-timeout-seconds", type=int, default=1800)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pi-bin", default=default_pi_bin())
    args = parser.parse_args()

    output_dir = (
        args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    )
    output_dir = output_dir.resolve()

    if args.status:
        print_status(output_dir)
        return

    if args.list:
        projects = filter_projects_by_kind(
            list_projects(),
            conceptual_only=args.conceptual_only,
            empirical_only=args.empirical_only,
        )
        for project in projects:
            print(project)
        return

    if args.max_concurrent < 1:
        raise SystemExit("--max-concurrent must be at least 1")
    if args.attempts < 1:
        raise SystemExit("--attempts must be at least 1")
    if args.complete_grace_seconds < 0:
        raise SystemExit("--complete-grace-seconds must be non-negative")
    if args.no_progress_timeout_seconds < 0:
        raise SystemExit("--no-progress-timeout-seconds must be non-negative")

    raise SystemExit(asyncio.run(run_all(args)))


if __name__ == "__main__":
    main()
