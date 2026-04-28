"""Launch agent runs across project ideas.

Supports both basic (single-loop) and advanced (full orchestrator) agent types.
Each project idea becomes an Inspect task. For each task, k agents are launched
in separate Docker containers.

Usage:
    # Basic agent
    python experiments/01_run_agents/run.py basic --model claude-sonnet-4-6

    # Advanced orchestrator
    python experiments/01_run_agents/run.py advanced --planner-model claude-sonnet-4-6 --worker-model claude-sonnet-4-6

    # Common options work with both
    python experiments/01_run_agents/run.py basic --model claude-opus-4-7 --k 3 --projects my_project --time-limit 3600

    # List available projects
    python experiments/01_run_agents/run.py --list
"""

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from inspect_ai import eval

from src.agent_scaffold.task import create_basic_task, create_task

PROJECT_IDEAS_DIR = Path(__file__).resolve().parent.parent / "project_ideas"
MIG_UUIDS_FILE = Path(__file__).resolve().parent.parent.parent / ".mig_uuids"

# Inspect's task_init runs `docker compose build / pull / config` ONCE per task
# before any sample is launched, so it has no sample-scoped metadata. Our
# compose file uses `${SAMPLE_METADATA_MIG_UUID:?...}` so that a real container
# start without metadata fails loudly. To let task-time YAML parsing succeed we
# expose a placeholder at the process level. Sample-scoped metadata overrides
# this at actual container-start time. If the override ever fails to land, the
# container will refuse to start (placeholder isn't a valid MIG UUID), which is
# the fail-loud behavior we want.
os.environ.setdefault("SAMPLE_METADATA_MIG_UUID", "TASK_INIT_PLACEHOLDER")


EXPECTED_MIG_PROFILE = "3g.40gb"


def _live_mig_slices() -> dict[str, str]:
    """Return {uuid: profile_name} for every MIG slice the driver exposes."""
    try:
        out = subprocess.check_output(["nvidia-smi", "-L"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError(f"nvidia-smi -L failed: {e}") from e
    # nvidia-smi -L lines for slices look like:
    #   "  MIG 3g.40gb     Device  0: (UUID: MIG-<hex-uuid>)"
    pattern = re.compile(r"MIG\s+(\S+).*?UUID:\s*(MIG-[0-9a-f-]+)")
    return {uuid: profile for profile, uuid in pattern.findall(out)}


def load_mig_uuids() -> list[str]:
    """Read MIG UUIDs from `.mig_uuids` and verify every one is a live MIG slice.

    Fails loudly if:
      - `.mig_uuids` is missing (MIG never enabled, or file deleted)
      - the file is empty
      - any UUID in the file is no longer a live MIG slice (host was rebooted,
        instances were torn down, or someone disabled MIG)
      - there are live MIG slices missing from the file (file is stale; would
        leak otherwise-usable capacity)
    """
    if not MIG_UUIDS_FILE.exists():
        raise FileNotFoundError(
            f"{MIG_UUIDS_FILE} not found. Run scripts/enable_mig.sh first."
        )
    file_uuids = [
        line.strip() for line in MIG_UUIDS_FILE.read_text().splitlines() if line.strip()
    ]
    if not file_uuids:
        raise ValueError(f"{MIG_UUIDS_FILE} is empty. Re-run scripts/enable_mig.sh.")

    live = _live_mig_slices()
    file_set = set(file_uuids)
    stale = file_set - live.keys()
    extra = live.keys() - file_set
    if stale:
        raise RuntimeError(
            f"{len(stale)} MIG UUID(s) in {MIG_UUIDS_FILE} are not live slices: "
            f"{sorted(stale)}. Likely the host was rebooted or MIG was disabled. "
            f"Re-run scripts/enable_mig.sh."
        )
    if extra:
        raise RuntimeError(
            f"{len(extra)} live MIG UUID(s) are not in {MIG_UUIDS_FILE}: "
            f"{sorted(extra)}. The file is stale. Re-run scripts/enable_mig.sh "
            f"to refresh it."
        )
    wrong_profile = {u: p for u, p in live.items() if p != EXPECTED_MIG_PROFILE}
    if wrong_profile:
        raise RuntimeError(
            f"Expected all MIG slices to be {EXPECTED_MIG_PROFILE}, but found "
            f"{wrong_profile}. The compose/dockerfile assume 40 GB slices; "
            f"reconfigure or re-run scripts/enable_mig.sh."
        )
    return file_uuids


def load_project(name: str) -> str:
    path = PROJECT_IDEAS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Project idea not found: {path}")
    return path.read_text()


def list_projects() -> list[str]:
    return sorted(p.stem for p in PROJECT_IDEAS_DIR.glob("*.md"))


def _model_short_name(model: str) -> str:
    """Shorten a model ID for use in directory names."""
    return model.split("/")[-1]


def _build_output_dir(base: str, agent_type: str, model_name: str) -> str:
    """Build structured output directory: base/agent_type/model/"""
    return f"{base}/{agent_type}/{_model_short_name(model_name)}"


def _print_summary(results, agent_type: str, output_dir: str):
    """Print results and rename log files."""
    for log in results:
        task_name = log.eval.task or "unknown"
        print(f"\n{'=' * 60}")
        print(f"Task: {task_name} ({agent_type})")
        print(f"Status: {log.status}")

        if log.samples:
            for i, sample in enumerate(log.samples):
                meta = sample.metadata or {}
                if agent_type == "advanced":
                    status = meta.get("orchestrator_status", "unknown")
                    phases = meta.get("phases_completed", 0)
                    print(f"  Agent {i}: {status} ({phases} phases)")
                    for p in meta.get("phase_details", []):
                        print(
                            f"    segment {p['segment']}, phase {p['phase']} "
                            f"({p['name']}) -> {p['decision']}"
                        )
                else:
                    status = meta.get("agent_status", "unknown")
                    print(f"  Agent {i}: {status}")

        new_name = f"{task_name}.eval"
        if log.location:
            old_path = Path(log.location)
            new_path = old_path.parent / new_name
            if old_path.exists() and not new_path.exists():
                shutil.move(old_path, new_path)
                print(f"  Log: {new_path}")


def _clean_output_dir(output_dir: str):
    """Remove previous run output for this specific agent/model combo."""
    p = Path(output_dir)
    if p.exists():
        shutil.rmtree(p)
        print(f"Cleaned previous output: {output_dir}")


def _extract_writeups(snapshot_dir: Path, writeups_dir: Path) -> int:
    """Pull the ``writeup/`` subtree out of every ``agent_*.tar.gz`` in
    ``snapshot_dir`` into ``writeups_dir/agent_<i>/`` (with the leading
    ``writeup/`` prefix stripped). Returns the count of agents extracted.
    """
    import re
    import tarfile

    if not snapshot_dir.exists():
        return 0
    pat = re.compile(r"^agent_(\d+)\.tar\.gz$")
    extracted = 0
    for tar_file in sorted(snapshot_dir.glob("agent_*.tar.gz")):
        m = pat.match(tar_file.name)
        if not m:
            continue
        agent_dest = writeups_dir / f"agent_{m.group(1)}"
        agent_dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar_file, "r:gz") as tar:
            members = []
            for member in tar.getmembers():
                name = member.name.lstrip("./")
                if not name.startswith("writeup/"):
                    continue
                stripped = name[len("writeup/") :]
                if not stripped:
                    continue
                member.name = stripped
                members.append(member)
            if members:
                tar.extractall(path=agent_dest, members=members, filter="data")
                extracted += 1
        if not any(agent_dest.iterdir()):
            agent_dest.rmdir()
    return extracted


def _allocate_mig_uuids(num_projects: int, k: int) -> list[list[str]]:
    """Slice the MIG-UUID pool into disjoint per-project chunks of size k."""
    pool = load_mig_uuids()
    needed = num_projects * k
    if needed > len(pool):
        raise ValueError(
            f"Total samples ({num_projects} projects x K={k} = {needed}) exceeds "
            f"available MIG slices ({len(pool)}). Reduce K, drop projects, or "
            f"add more MIG slices."
        )
    return [pool[i * k : (i + 1) * k] for i in range(num_projects)]


def run_basic(args, projects: list[str]):
    """Run basic (single-loop) agents."""
    output_dir = _build_output_dir(args.output_dir, "basic", args.model)
    _clean_output_dir(output_dir)
    snapshot_dir = f"{output_dir}/snapshots"

    sandbox = ("docker", "docker/compose.research.yml")
    project_uuids = _allocate_mig_uuids(len(projects), args.k)

    tasks = []
    for project_name, uuids in zip(projects, project_uuids):
        instructions = load_project(project_name)
        task = create_basic_task(
            [instructions] * args.k,
            name=project_name,
            sandbox=sandbox,
            env_file=".env" if Path(".env").exists() else None,
            token_limit=args.token_limit,
            time_limit=args.time_limit,
            max_continuations=args.max_continuations,
            model=args.model,
            snapshot_dir=f"{snapshot_dir}/{project_name}",
            stall_timeout=args.stall_timeout or None,
            mig_uuids=uuids,
        )
        tasks.append(task)

    print(f"Agent type: basic")
    print(f"Model: {args.model}")
    print(f"Projects ({len(tasks)}), {args.k} agent(s) each:")
    for t in tasks:
        print(f"  {t.name}")
    print(f"Output: {output_dir}")
    print()

    results = eval(
        tasks,
        model=args.model,
        log_dir=output_dir,
        max_sandboxes=args.max_sandboxes,
        display=args.display,
        log_realtime=True,
        log_buffer=1,
        log_shared=True,
    )

    _print_summary(results, "basic", output_dir)

    writeups_root = Path(output_dir) / "writeups"
    for project_name in projects:
        n = _extract_writeups(
            snapshot_dir=Path(snapshot_dir) / project_name,
            writeups_dir=writeups_root / project_name,
        )
        if n:
            print(f"  Extracted {n} writeup(s) → {writeups_root / project_name}")


def run_advanced(args, projects: list[str]):
    """Run full orchestrator agents."""
    primary_model = args.planner_model
    output_dir = _build_output_dir(args.output_dir, "advanced", primary_model)
    _clean_output_dir(output_dir)
    snapshot_dir = f"{output_dir}/snapshots"

    sandbox = ("docker", "docker/compose.research.yml")
    project_uuids = _allocate_mig_uuids(len(projects), args.k)

    tasks = []
    for project_name, uuids in zip(projects, project_uuids):
        instructions = load_project(project_name)
        task = create_task(
            [instructions] * args.k,
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
            mig_uuids=uuids,
        )
        tasks.append(task)

    print(f"Agent type: advanced (full orchestrator)")
    print(f"Models:")
    print(f"  Planner: {args.planner_model}")
    print(f"  Worker: {args.worker_model}")
    print(f"  Phase planner: {args.phase_planner_model or args.planner_model}")
    print(f"Projects ({len(tasks)}), {args.k} agent(s) each:")
    for t in tasks:
        print(f"  {t.name}")
    print(f"Output: {output_dir}")
    print()

    results = eval(
        tasks,
        model=args.planner_model,
        log_dir=output_dir,
        max_sandboxes=args.max_sandboxes,
        display=args.display,
        log_realtime=True,
        log_buffer=1,
        log_shared=True,
    )

    _print_summary(results, "advanced", output_dir)

    writeups_root = Path(output_dir) / "writeups"
    for project_name in projects:
        n = _extract_writeups(
            snapshot_dir=Path(snapshot_dir) / project_name,
            writeups_dir=writeups_root / project_name,
        )
        if n:
            print(f"  Extracted {n} writeup(s) → {writeups_root / project_name}")


def main():
    available = list_projects()

    parser = argparse.ArgumentParser(
        description="Launch agent runs across project ideas.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--list", action="store_true", help="List available projects and exit."
    )

    subparsers = parser.add_subparsers(dest="agent_type", help="Agent type to run.")

    # --- Shared arguments (added to both subparsers) ---
    def add_common_args(sub):
        sub.add_argument(
            "--projects",
            nargs="+",
            default=None,
            metavar="NAME",
            help="Project ideas to run (default: all).",
        )
        sub.add_argument(
            "--k", type=int, default=1, help="Agents per project (default: 1)."
        )
        sub.add_argument(
            "--max-sandboxes",
            type=int,
            default=None,
            help="Max concurrent containers.",
        )
        sub.add_argument(
            "--output-dir",
            default="outputs/01_run_agents",
            help="Base output directory (default: outputs/01_run_agents).",
        )
        sub.add_argument("--token-limit", type=int, default=None)
        sub.add_argument(
            "--time-limit", type=int, default=None, help="Seconds per agent."
        )
        sub.add_argument("--max-continuations", type=int, default=30)
        sub.add_argument(
            "--display",
            default="full",
            choices=["full", "conversation", "rich", "plain", "none"],
        )
        sub.add_argument(
            "--stall-timeout",
            type=int,
            default=1800,
            help="Seconds of no activity before killing agent (0 = disable).",
        )

    # --- Basic subcommand ---
    basic_parser = subparsers.add_parser(
        "basic",
        help="Single-loop agent (plan → execute → checklist).",
    )
    add_common_args(basic_parser)
    basic_parser.add_argument("--model", required=True, help="Model for the agent.")

    # --- Advanced subcommand ---
    advanced_parser = subparsers.add_parser(
        "advanced",
        help="Full orchestrator (planner → worker → phase planner → review).",
    )
    add_common_args(advanced_parser)
    advanced_parser.add_argument(
        "--planner-model", required=True, help="Model for the main planner."
    )
    advanced_parser.add_argument(
        "--worker-model", required=True, help="Model for workers."
    )
    advanced_parser.add_argument(
        "--phase-planner-model",
        default=None,
        help="Model for phase planners/reviews (default: --planner-model).",
    )
    advanced_parser.add_argument("--max-phases", type=int, default=10)
    advanced_parser.add_argument("--planning-only", action="store_true")

    args = parser.parse_args()

    if args.list:
        for name in available:
            print(name)
        return

    if not args.agent_type:
        parser.print_help()
        return

    projects = args.projects or available

    if args.agent_type == "basic":
        run_basic(args, projects)
    elif args.agent_type == "advanced":
        run_advanced(args, projects)


if __name__ == "__main__":
    main()
