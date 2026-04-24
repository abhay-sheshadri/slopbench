"""Inspect AI Task wrapper for the agent scaffold."""

from pathlib import Path

from inspect_ai import Task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import SandboxEnvironmentType

from .orchestrator import run as orchestrator_run


@solver
def orchestrator_solver(
    working_dir: str = "/workspace",
    env_contents: str | None = None,
    max_phases: int = 10,
    max_review_iterations: int = 5,
    max_continuations: int = 15,
    simple_worker: bool = True,
    planning_only: bool = False,
    planner_model: str | None = None,
    worker_model: str | None = None,
    phase_planner_model: str | None = None,
    snapshot_dir: str | None = None,
    skills: list[str] | None = None,
    stall_timeout: float | None = 1800,
) -> Solver:
    """Solver that runs the full orchestrator lifecycle."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        result = await orchestrator_run(
            task_instructions=state.input_text,
            working_dir=working_dir,
            env_contents=env_contents,
            max_phases=max_phases,
            max_review_iterations=max_review_iterations,
            max_continuations=max_continuations,
            simple_worker=simple_worker,
            planning_only=planning_only,
            planner_model=planner_model,
            worker_model=worker_model,
            phase_planner_model=phase_planner_model,
            skills=skills,
            stall_timeout=stall_timeout,
        )
        state.metadata["orchestrator_status"] = result.status
        state.metadata["phases_completed"] = len(result.phases)
        state.metadata["phase_details"] = [
            {
                "segment": p.segment_idx,
                "phase": p.phase_idx,
                "name": p.name,
                "decision": p.phase_planner_decision,
            }
            for p in result.phases
        ]
        if result.final_dir:
            state.metadata["final_dir"] = result.final_dir

        if snapshot_dir and result.workspace_tar:
            snap_path = Path(snapshot_dir) / f"agent_{state.sample_id}.tar.gz"
            snap_path.parent.mkdir(parents=True, exist_ok=True)
            snap_path.write_bytes(result.workspace_tar)
            state.metadata["snapshot"] = str(snap_path)

        return state

    return solve


def create_task(
    task_instructions: str | list[str],
    *,
    name: str | None = None,
    sandbox: SandboxEnvironmentType | None = None,
    env_file: str | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    max_phases: int = 10,
    max_review_iterations: int = 5,
    max_continuations: int = 15,
    simple_worker: bool = True,
    planning_only: bool = False,
    working_dir: str = "/workspace",
    planner_model: str | None = None,
    worker_model: str | None = None,
    phase_planner_model: str | None = None,
    snapshot_dir: str | None = None,
    skills: list[str] | None = None,
    stall_timeout: float | None = 1800,
) -> Task:
    if isinstance(task_instructions, str):
        task_instructions = [task_instructions]

    env_contents = None
    if env_file:
        env_contents = Path(env_file).read_text()

    samples = [Sample(input=instr, id=i) for i, instr in enumerate(task_instructions)]

    return Task(
        name=name,
        dataset=samples,
        solver=orchestrator_solver(
            working_dir=working_dir,
            env_contents=env_contents,
            max_phases=max_phases,
            max_review_iterations=max_review_iterations,
            max_continuations=max_continuations,
            simple_worker=simple_worker,
            planning_only=planning_only,
            planner_model=planner_model,
            worker_model=worker_model,
            phase_planner_model=phase_planner_model,
            snapshot_dir=snapshot_dir,
            skills=skills,
            stall_timeout=stall_timeout,
        ),
        sandbox=sandbox,
        token_limit=token_limit,
        time_limit=time_limit,
    )
