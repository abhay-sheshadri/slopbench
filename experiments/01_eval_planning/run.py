from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_IDEAS_DIR = ROOT / "experiments" / "project_ideas"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "01_eval_planning"

# Defaults as of 2026-05-25 from the official model docs. Keep these
# configurable because "latest" model IDs change over time.
DEFAULT_CLAUDE_MODEL = "anthropic/claude-opus-4-7"
DEFAULT_GPT_MODEL = "openai/gpt-5.5-pro"

REQUIRED_PLANNER_FILES = (
    "OVERALL_PLAN.md",
    "INSTRUCTIONS_SEGMENT_0_PHASE_0.md",
    "RUBRIC_SEGMENT_0_PHASE_0.md",
)


@dataclass(frozen=True)
class PlannerJob:
    project: str
    project_file: Path
    model_family: str
    model: str
    attempt: int
    work_dir: Path


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    slug = slug.strip("-._")
    return slug or "unnamed"


def list_projects() -> list[str]:
    return sorted(path.stem for path in PROJECT_IDEAS_DIR.glob("*.md"))


def planner_dir_complete(work_dir: Path) -> bool:
    planner_dir = work_dir / "planner"
    for name in REQUIRED_PLANNER_FILES:
        path = planner_dir / name
        if not path.exists() or not path.read_text().strip():
            return False
    return True


def build_initial_instructions(project_name: str, project_text: str) -> str:
    return f"""# Initial Instructions

You are planning an autonomous research project from the project idea below.

Create a concrete Ryan-style execution plan for an autonomous worker agent. The
plan should decompose the project into useful segments/phases, identify risks
and likely failure modes, and produce a strong first phase that starts making
real progress without trying to complete the entire project shallowly.

# Project Idea: {project_name}

{project_text.strip()}
"""


def prepare_work_dir(job: PlannerJob, force: bool) -> bool:
    if job.work_dir.exists() and planner_dir_complete(job.work_dir) and not force:
        return False

    if force and job.work_dir.exists():
        shutil.rmtree(job.work_dir)

    planner_dir = job.work_dir / "planner"
    planner_dir.mkdir(parents=True, exist_ok=True)

    project_text = job.project_file.read_text()
    (job.work_dir / "project_idea.md").write_text(project_text)
    (planner_dir / "INITIAL_INSTRUCTIONS.md").write_text(
        build_initial_instructions(job.project, project_text)
    )
    return True


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


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = value


async def run_job(job: PlannerJob, pi_bin: str, thinking: str, force: bool) -> bool:
    should_run = prepare_work_dir(job, force=force)
    if not should_run:
        print(f"skip complete: {job.project} {job.model_family} attempt {job.attempt}")
        return True

    paths = transcript_paths(job.work_dir)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    session_path = paths["session"]
    cmd = [
        pi_bin,
        "-p",
        "--session",
        str(session_path),
        "--model",
        job.model,
        "--thinking",
        thinking,
        "--mode",
        "json",
        "/init-planner",
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

    with paths["events"].open("wb") as stdout, paths["stderr"].open("wb") as stderr:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=job.work_dir,
            stdout=stdout,
            stderr=stderr,
            env=os.environ.copy(),
        )
        returncode = await proc.wait()

    complete = planner_dir_complete(job.work_dir)
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

    status = {
        **metadata,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "returncode": returncode,
        "planner_files_complete": complete,
        "session_exists": session_path.exists(),
        "session_size_bytes": (
            session_path.stat().st_size if session_path.exists() else 0
        ),
        "html_exported": html_exported,
        "html_export_error": html_export_error,
        "status": "ok" if returncode == 0 and complete else "failed",
    }
    write_json(job.work_dir / "run_status.json", status)
    write_json(paths["manifest"], status)

    if status["status"] != "ok":
        print(f"failed: {job.project} {job.model_family} attempt {job.attempt}")
        return False

    print(f"ok: {job.project} {job.model_family} attempt {job.attempt}")
    return True


async def run_all(args: argparse.Namespace) -> int:
    load_env_file(ROOT / ".env")

    available_projects = list_projects()
    selected_projects = args.projects or available_projects
    unknown = sorted(set(selected_projects) - set(available_projects))
    if unknown:
        raise SystemExit(f"Unknown project(s): {', '.join(unknown)}")

    model_specs: list[tuple[str, str]] = []
    if "claude" in args.models:
        model_specs.append(("claude", args.claude_model))
    if "gpt" in args.models:
        model_specs.append(("gpt", args.gpt_model))

    jobs: list[PlannerJob] = []
    for project in selected_projects:
        project_file = PROJECT_IDEAS_DIR / f"{project}.md"
        for model_family, model in model_specs:
            for attempt in range(1, args.attempts + 1):
                work_dir = (
                    args.output_dir
                    / safe_slug(project)
                    / safe_slug(model_family)
                    / f"attempt_{attempt:02d}"
                )
                jobs.append(
                    PlannerJob(
                        project=project,
                        project_file=project_file,
                        model_family=model_family,
                        model=model,
                        attempt=attempt,
                        work_dir=work_dir,
                    )
                )

    print(f"Projects: {', '.join(selected_projects)}")
    print(f"Models: {', '.join(f'{family}={model}' for family, model in model_specs)}")
    print(f"Attempts per project/model: {args.attempts}")
    print(f"Output: {args.output_dir}")
    print(f"Pi binary: {args.pi_bin}")
    print()

    semaphore = asyncio.Semaphore(args.max_concurrent)

    async def guarded(job: PlannerJob) -> bool:
        async with semaphore:
            return await run_job(
                job=job,
                pi_bin=args.pi_bin,
                thinking=args.thinking,
                force=args.force,
            )

    results = await asyncio.gather(*(guarded(job) for job in jobs))
    failed = len([ok for ok in results if not ok])
    if failed:
        print(f"\n{failed} planner attempt(s) failed.")
        return 1
    print("\nAll planner attempts completed or were already complete.")
    return 0


def default_pi_bin() -> str:
    local_abhay_pi = ROOT / "scripts" / "abhay-pi"
    if local_abhay_pi.exists():
        return str(local_abhay_pi)
    return shutil.which("abhay-pi") or shutil.which("pi") or "pi"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list", action="store_true", help="List project ideas and exit."
    )
    parser.add_argument(
        "--projects", nargs="+", help="Project idea names to run. Default: all."
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=["claude", "gpt"],
        default=["claude", "gpt"],
        help="Model families to run. Default: claude gpt.",
    )
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--claude-model", default=DEFAULT_CLAUDE_MODEL)
    parser.add_argument("--gpt-model", default=DEFAULT_GPT_MODEL)
    parser.add_argument("--thinking", default="xhigh")
    parser.add_argument("--max-concurrent", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pi-bin", default=default_pi_bin())
    parser.add_argument(
        "--force", action="store_true", help="Delete and rerun existing attempt dirs."
    )
    args = parser.parse_args()

    if args.list:
        for project in list_projects():
            print(project)
        return

    if args.attempts < 1:
        raise SystemExit("--attempts must be at least 1")
    if args.max_concurrent < 1:
        raise SystemExit("--max-concurrent must be at least 1")

    raise SystemExit(asyncio.run(run_all(args)))


if __name__ == "__main__":
    main()
