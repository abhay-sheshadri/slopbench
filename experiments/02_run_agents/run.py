from __future__ import annotations

import argparse
import os
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROPOSALS_DIR = ROOT / "experiments" / "project_ideas"
DEFAULT_OUTPUT_DIR = "outputs/02_run_agents"


def load_proposal(name: str) -> str:
    path = PROPOSALS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Proposal not found: {path}")
    return path.read_text()


def list_proposals() -> list[str]:
    return sorted(path.stem for path in PROPOSALS_DIR.glob("*.md"))


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


def model_slug(model: str) -> str:
    return model.split("/")[-1]


def output_dir(base: str, mode: str, model: str) -> Path:
    return Path(base) / mode / model_slug(model)


def clean_output_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
        print(f"Cleaned previous output: {path}")


def extract_writeups(snapshot_dir: Path, writeups_dir: Path) -> int:
    if not snapshot_dir.exists():
        return 0

    extracted = 0
    for tar_file in sorted(snapshot_dir.glob("agent_*.tar.gz")):
        agent_dest = writeups_dir / tar_file.stem.removesuffix(".tar")
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


def print_summary(results, mode: str) -> None:
    for log in results:
        task_name = log.eval.task or "unknown"
        print(f"\n{'=' * 60}")
        print(f"Task: {task_name} ({mode})")
        print(f"Status: {log.status}")

        for index, sample in enumerate(log.samples or []):
            meta = sample.metadata or {}
            print(f"  Agent {index}: {meta.get('pi_status', 'unknown')}")
            if meta.get("pi_transcript_dir"):
                print(f"    Transcript: {meta['pi_transcript_dir']}")
            if meta.get("snapshot"):
                print(f"    Snapshot: {meta['snapshot']}")

        if log.location:
            old_path = Path(log.location)
            new_path = old_path.parent / f"{task_name}.eval"
            if old_path.exists() and not new_path.exists():
                shutil.move(old_path, new_path)
                print(f"  Log: {new_path}")


def run_eval(args: argparse.Namespace, proposals: list[str]) -> None:
    load_env_file(ROOT / ".env")

    from inspect_ai import eval

    from src.pi_inspect import create_pi_agent_task

    out_dir = output_dir(args.output_dir, args.mode, args.model)
    if args.force:
        clean_output_dir(out_dir)

    tasks = []
    for proposal_name in proposals:
        task = create_pi_agent_task(
            [load_proposal(proposal_name)] * args.k,
            mode=args.mode,
            name=proposal_name,
            sandbox=("docker", "docker/compose.research.yml"),
            env_file=".env" if Path(".env").exists() else None,
            token_limit=args.token_limit,
            time_limit=args.time_limit,
            model=args.model,
            pi_bin=args.pi_bin,
            thinking=args.thinking,
            proposal_file="proposal.md",
            prompt=args.prompt,
            run_loop_args=args.run_loop_args,
            command_timeout=args.command_timeout,
            transcript_dir=str(out_dir / "pi_transcripts" / proposal_name),
            snapshot_dir=str(out_dir / "snapshots" / proposal_name),
        )
        tasks.append(task)

    print(f"Mode: {args.mode}")
    print(f"Model: {args.model}")
    print(f"Proposals ({len(tasks)}), {args.k} agent(s) each:")
    for task in tasks:
        print(f"  {task.name}")
    print(f"Output: {out_dir}")
    print()

    results = eval(
        tasks,
        model=args.model,
        log_dir=str(out_dir),
        max_sandboxes=args.max_sandboxes,
        display=args.display,
        log_realtime=True,
        log_buffer=1,
        log_shared=True,
    )
    print_summary(results, args.mode)

    writeups_root = out_dir / "writeups"
    for proposal_name in proposals:
        count = extract_writeups(
            snapshot_dir=out_dir / "snapshots" / proposal_name,
            writeups_dir=writeups_root / proposal_name,
        )
        if count:
            print(f"  Extracted {count} writeup(s) -> {writeups_root / proposal_name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Pi agent modes in Inspect Docker sandboxes."
    )
    parser.add_argument("--list", action="store_true", help="List proposals and exit.")
    parser.add_argument(
        "mode",
        nargs="?",
        default="goal-mode",
        choices=["goal-mode", "ryan-loop"],
        help="Agent mode to run. Default: goal-mode.",
    )
    parser.add_argument(
        "--proposals", "--projects", nargs="+", default=None, metavar="NAME"
    )
    parser.add_argument("--k", type=int, default=1, help="Agents per proposal.")
    parser.add_argument("--model", default="anthropic/claude-opus-4-7")
    parser.add_argument("--thinking", default="xhigh")
    parser.add_argument(
        "--prompt", default=None, help="Custom goal prompt for goal-mode."
    )
    parser.add_argument("--run-loop-args", default="")
    parser.add_argument("--pi-bin", default="pi")
    parser.add_argument("--max-sandboxes", type=int, default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--token-limit", type=int, default=None)
    parser.add_argument("--time-limit", type=int, default=None)
    parser.add_argument("--command-timeout", type=int, default=None)
    parser.add_argument(
        "--stall-timeout", type=int, default=None, help="Alias for --command-timeout."
    )
    parser.add_argument(
        "--display",
        default="full",
        choices=["full", "conversation", "rich", "plain", "none"],
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete this mode/model output before running.",
    )
    return parser.parse_args()


def main() -> None:
    available = list_proposals()
    args = parse_args()

    if args.list:
        for proposal in available:
            print(proposal)
        return

    if args.k < 1:
        raise SystemExit("--k must be at least 1")
    if args.max_sandboxes is not None and args.max_sandboxes < 1:
        raise SystemExit("--max-sandboxes must be at least 1")
    if args.command_timeout is None:
        args.command_timeout = args.stall_timeout

    proposals = args.proposals or available
    unknown = sorted(set(proposals) - set(available))
    if unknown:
        raise SystemExit(f"Unknown proposal(s): {', '.join(unknown)}")

    run_eval(args, proposals)


if __name__ == "__main__":
    main()
