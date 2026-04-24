"""Inspect AI Task wrapper for the agent scaffold."""

import uuid
from pathlib import Path

from inspect_ai import Task
from inspect_ai.agent import AgentState
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import bash, python, text_editor
from inspect_ai.util import SandboxEnvironmentType, sandbox, span

from .agent import (
    INITIAL_INSTRUCTIONS_FILE,
    ActivityTracker,
    StallError,
    basic_agent,
    run_with_watchdog,
    write_file,
)
from .orchestrator import init_git
from .orchestrator import run as orchestrator_run
from .orchestrator import snapshot_workspace


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


# ---------------------------------------------------------------------------
# Basic agent solver + task
# ---------------------------------------------------------------------------


@solver
def basic_agent_solver(
    working_dir: str = "/workspace",
    env_contents: str | None = None,
    max_continuations: int = 30,
    model: str | None = None,
    snapshot_dir: str | None = None,
    skills: list[str] | None = None,
    stall_timeout: float | None = 1800,
) -> Solver:
    """Solver that runs a single basic agent (plan → execute → checklist)."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await sandbox().exec(["mkdir", "-p", working_dir], timeout=10)

        await write_file(f"{working_dir}/{INITIAL_INSTRUCTIONS_FILE}", state.input_text)
        if env_contents:
            await write_file(f"{working_dir}/.env", env_contents)

        await init_git(working_dir)

        tracker = ActivityTracker() if stall_timeout else None
        agent = basic_agent(
            working_dir=working_dir,
            tools=[bash(), text_editor(), python()],
            max_continuations=max_continuations,
            model=model,
            skills=skills,
            activity_tracker=tracker,
        )

        agent_state = AgentState(messages=[ChatMessageUser(content="Begin the task.")])

        span_id = uuid.uuid4().hex
        async with span("basic_agent", type="agent", id=span_id):
            try:
                if tracker:
                    tracker.ping()
                    agent_state = await run_with_watchdog(
                        agent(agent_state),
                        tracker,
                        stall_timeout,
                        label="basic_agent",
                    )
                else:
                    agent_state = await agent(agent_state)
                state.metadata["agent_status"] = "completed"
            except StallError as e:
                state.metadata["agent_status"] = "stalled"
                state.metadata["stall_reason"] = str(e)

        state.metadata["stop_reason"] = agent_state.output.stop_reason

        if snapshot_dir:
            tar_bytes = await snapshot_workspace(working_dir)
            if tar_bytes:
                snap_path = Path(snapshot_dir) / f"agent_{state.sample_id}.tar.gz"
                snap_path.parent.mkdir(parents=True, exist_ok=True)
                snap_path.write_bytes(tar_bytes)
                state.metadata["snapshot"] = str(snap_path)

        return state

    return solve


def create_basic_task(
    task_instructions: str | list[str],
    *,
    name: str | None = None,
    sandbox: SandboxEnvironmentType | None = None,
    env_file: str | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    max_continuations: int = 30,
    working_dir: str = "/workspace",
    model: str | None = None,
    snapshot_dir: str | None = None,
    skills: list[str] | None = None,
    stall_timeout: float | None = 1800,
) -> Task:
    """Create an Inspect Task using the basic single-loop agent."""
    if isinstance(task_instructions, str):
        task_instructions = [task_instructions]

    env_contents = None
    if env_file:
        env_contents = Path(env_file).read_text()

    samples = [Sample(input=instr, id=i) for i, instr in enumerate(task_instructions)]

    return Task(
        name=name,
        dataset=samples,
        solver=basic_agent_solver(
            working_dir=working_dir,
            env_contents=env_contents,
            max_continuations=max_continuations,
            model=model,
            snapshot_dir=snapshot_dir,
            skills=skills,
            stall_timeout=stall_timeout,
        ),
        sandbox=sandbox,
        token_limit=token_limit,
        time_limit=time_limit,
    )
