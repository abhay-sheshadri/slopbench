"""Launch agent runs across project ideas.

Each project idea becomes a task. For each task, k agents are launched in
separate Docker containers, each running the full orchestrator lifecycle.

Usage:
    python experiments/01_run_agents/run.py
    python experiments/01_run_agents/run.py --projects understanding_probe_generalization
    python experiments/01_run_agents/run.py --k 3 --gpu-memory 20 --planning-only
    python experiments/01_run_agents/run.py --help

See run.sh for convenient wrapper with defaults.
"""

import argparse
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from inspect_ai import eval

from src.agent_scaffold.task import create_task

PROJECT_IDEAS_DIR = Path(__file__).resolve().parent.parent / "project_ideas"


def load_project(name: str) -> str:
    """Load a project idea markdown file and return its contents."""
    path = PROJECT_IDEAS_DIR / f"{name}.md"
    assert path.exists(), f"Project idea not found: {path}"
    return path.read_text()


def list_projects() -> list[str]:
    """List available project idea names (without .md extension)."""
    return sorted(p.stem for p in PROJECT_IDEAS_DIR.glob("*.md"))


def main():
    available = list_projects()

    parser = argparse.ArgumentParser(
        description="Launch agent runs across project ideas.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Available projects:\n  " + "\n  ".join(available),
    )
    parser.add_argument(
        "--projects",
        nargs="+",
        default=available,
        metavar="NAME",
        help="Project ideas to run (default: all). Names match filenames in experiments/project_ideas/.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=1,
        help="Number of agents to launch per project (default: 1).",
    )
    parser.add_argument(
        "--planner-model",
        required=True,
        help="Model for the main planner.",
    )
    parser.add_argument(
        "--worker-model",
        required=True,
        help="Model for workers.",
    )
    parser.add_argument(
        "--phase-planner-model",
        default=None,
        help="Model for phase planners and reviews (default: --planner-model).",
    )
    parser.add_argument(
        "--gpu-memory",
        type=int,
        default=None,
        metavar="GB",
        help="VRAM limit per container in GB (default: no limit).",
    )
    parser.add_argument(
        "--max-sandboxes",
        type=int,
        default=None,
        help="Max concurrent containers (default: auto).",
    )
    parser.add_argument(
        "--log-dir",
        default="logs/01_run_agents",
        help="Directory for Inspect eval logs (default: logs/01_run_agents).",
    )
    parser.add_argument(
        "--token-limit",
        type=int,
        default=None,
        help="Token budget per agent run.",
    )
    parser.add_argument(
        "--time-limit",
        type=int,
        default=None,
        help="Wall-clock time limit per agent run in seconds.",
    )
    parser.add_argument(
        "--max-phases",
        type=int,
        default=10,
        help="Max orchestrator phases per run.",
    )
    parser.add_argument(
        "--max-continuations",
        type=int,
        default=15,
        help="Max continuation nudges per agent.",
    )
    parser.add_argument(
        "--display",
        default="full",
        choices=["full", "conversation", "rich", "plain", "none"],
        help="Terminal display mode during eval (default: full).",
    )
    parser.add_argument(
        "--snapshot-dir",
        default=None,
        help="Directory to save workspace snapshots (tar.gz per agent). Defaults to <log-dir>/snapshots.",
    )
    parser.add_argument(
        "--stall-timeout",
        type=int,
        default=1800,
        help="Kill agent step after this many seconds of no API/tool activity (default: 1800 = 30 min). 0 to disable.",
    )
    parser.add_argument("--planning-only", action="store_true")
    parser.add_argument(
        "--list", action="store_true", help="List available projects and exit."
    )
    args = parser.parse_args()

    if args.list:
        for name in available:
            print(name)
        return

    # Set GPU memory limit via env var (read by compose.research.yml)
    if args.gpu_memory:
        os.environ["GPU_MEMORY_GB"] = str(args.gpu_memory)

    sandbox = ("docker", "docker/compose.research.yml")
    snapshot_dir = args.snapshot_dir or f"{args.log_dir}/snapshots"

    # Build tasks: for each project, create k copies of the instructions
    tasks = []
    for project_name in args.projects:
        instructions = load_project(project_name)
        task_instructions = [instructions] * args.k
        task = create_task(
            task_instructions,
            name=project_name,
            sandbox=sandbox,
            env_file=".env" if Path(".env").exists() else None,
            token_limit=args.token_limit,
            time_limit=args.time_limit,
            max_phases=args.max_phases,
            max_continuations=args.max_continuations,
            planning_only=args.planning_only,
            planner_model=args.planner_model,
            worker_model=args.worker_model,
            phase_planner_model=args.phase_planner_model,
            snapshot_dir=f"{snapshot_dir}/{project_name}",
            stall_timeout=args.stall_timeout or None,
        )
        tasks.append(task)

    print(f"Launching {len(tasks)} project(s), {args.k} agent(s) each:")
    for t in tasks:
        print(f"  {t.name}")
    print(f"Models:")
    print(f"  Planner: {args.planner_model}")
    print(f"  Worker: {args.worker_model}")
    print(f"  Phase planner: {args.phase_planner_model or args.planner_model}")
    print(f"Sandbox: {sandbox or 'local'}")
    if args.gpu_memory:
        print(f"VRAM limit: {args.gpu_memory} GB per container")
    print(f"Logs: {args.log_dir}")
    print()

    results = eval(
        tasks,
        model=args.planner_model,
        log_dir=args.log_dir,
        max_sandboxes=args.max_sandboxes,
        display=args.display,
        log_realtime=True,
        log_buffer=1,
        log_shared=True,
    )

    # Print summary and rename log files
    for log in results:
        task_name = log.eval.task or "unknown"

        print(f"\n{'=' * 60}")
        print(f"Task: {task_name}")
        print(f"Status: {log.status}")
        if log.samples:
            for i, sample in enumerate(log.samples):
                meta = sample.metadata or {}
                status = meta.get("orchestrator_status", "unknown")
                phases = meta.get("phases_completed", 0)
                print(f"  Agent {i}: {status} ({phases} phases)")
                for p in meta.get("phase_details", []):
                    print(
                        f"    segment {p['segment']}, phase {p['phase']} ({p['name']}) -> {p['decision']}"
                    )

        new_name = f"{task_name}.eval"
        if log.location:
            old_path = Path(log.location)
            new_path = old_path.parent / new_name
            if old_path.exists() and not new_path.exists():
                shutil.move(old_path, new_path)
                print(f"Saved: {new_path}")


if __name__ == "__main__":
    main()
