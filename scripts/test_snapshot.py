"""Smoke test for snapshot_workspace. Spawns a trivial Inspect eval, writes a
file inside the sandbox, calls snapshot_workspace, and reports whether the
tarball lands on the host. ~30 seconds end-to-end.

Run: python scripts/test_snapshot.py
"""

import shutil
import sys
import tarfile
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")
sys.path.insert(0, str(REPO))

from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

from src.agent_scaffold.orchestrator import snapshot_workspace

DEST = REPO / "outputs" / "_snapshot_smoke" / "agent_0.tar.gz"
LOG_DIR = REPO / "outputs" / "_snapshot_smoke" / "logs"


@solver
def trivial_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        await sb.exec(["mkdir", "-p", "/workspace/writeup/figures"], timeout=10)
        await sb.exec(
            [
                "bash",
                "-c",
                "echo 'hello from agent' > /workspace/writeup/FINDINGS.md && "
                "echo 'fake png bytes' > /workspace/writeup/figures/plot.png && "
                "echo 'src code' > /workspace/main.py",
            ],
            timeout=10,
        )
        ok = await snapshot_workspace("/workspace", DEST)
        state.metadata["snapshot_ok"] = ok
        state.metadata["dest"] = str(DEST)
        return state

    return solve


def main() -> int:
    if DEST.parent.exists():
        shutil.rmtree(DEST.parent)
    DEST.parent.mkdir(parents=True, exist_ok=True)

    task = Task(
        name="snapshot_smoke",
        dataset=[Sample(input="ignored", id=0)],
        solver=trivial_solver(),
        sandbox=("docker", str(REPO / "docker" / "compose.minimal.yml")),
        time_limit=120,
    )
    inspect_eval([task], log_dir=str(LOG_DIR), display="plain")

    print()
    print("=" * 60)
    print(f"Tarball expected at: {DEST}")
    print(f"Tarball exists:      {DEST.exists()}")
    if DEST.exists():
        print(f"Tarball size:        {DEST.stat().st_size:,} bytes")
        with tarfile.open(DEST, "r:gz") as t:
            members = t.getmembers()
        print(f"Tarball members ({len(members)}):")
        for m in members[:15]:
            kind = "D" if m.isdir() else "F"
            print(f"  {kind}  {m.name}  ({m.size} bytes)")
        return 0
    print("FAIL — snapshot did not land on host. Check the eval log:")
    print(f"  {LOG_DIR}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
