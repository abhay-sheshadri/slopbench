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
    basic_planner,
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
        snap_dest = (
            Path(snapshot_dir) / f"agent_{state.sample_id}.tar.gz"
            if snapshot_dir
            else None
        )
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
            snapshot_dest=snap_dest,
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
        if result.snapshot_path:
            state.metadata["snapshot"] = str(result.snapshot_path)

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
    mig_uuids: list[str] | None = None,
) -> Task:
    if isinstance(task_instructions, str):
        task_instructions = [task_instructions]

    env_contents = None
    if env_file:
        env_contents = Path(env_file).read_text()

    if mig_uuids is not None:
        if len(task_instructions) > len(mig_uuids):
            raise ValueError(
                f"Need {len(task_instructions)} MIG UUIDs but only "
                f"{len(mig_uuids)} available. Reduce K or add more MIG slices."
            )
        samples = [
            Sample(input=instr, id=i, metadata={"MIG_UUID": mig_uuids[i]})
            for i, instr in enumerate(task_instructions)
        ]
    else:
        samples = [
            Sample(input=instr, id=i) for i, instr in enumerate(task_instructions)
        ]

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
    """Solver that runs the basic two-stage flow in ``working_dir``:
    1. ``basic_planner`` writes ``GOALS.md`` (exhaustive goals + verification steps).
    2. ``basic_agent`` completes the project and exits only when every goal in
       ``GOALS.md`` has been verified achieved.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await sandbox().exec(["mkdir", "-p", working_dir], timeout=10)

        await write_file(f"{working_dir}/{INITIAL_INSTRUCTIONS_FILE}", state.input_text)
        if env_contents:
            await write_file(f"{working_dir}/.env", env_contents)

        await init_git(working_dir)

        tracker = ActivityTracker() if stall_timeout else None
        tools = [bash(), text_editor(), python()]

        async def run_stage(
            agent, stage_name: str, initial_message: str
        ) -> tuple[AgentState, bool]:
            """Run an agent stage under the watchdog. Returns (final_state, stalled)."""
            agent_state = AgentState(
                messages=[ChatMessageUser(content=initial_message)]
            )
            span_id = uuid.uuid4().hex
            async with span(stage_name, type="agent", id=span_id):
                try:
                    if tracker:
                        tracker.ping()
                        agent_state = await run_with_watchdog(
                            agent(agent_state),
                            tracker,
                            stall_timeout,
                            label=stage_name,
                        )
                    else:
                        agent_state = await agent(agent_state)
                    return agent_state, False
                except StallError as e:
                    state.metadata["agent_status"] = "stalled"
                    state.metadata["stall_reason"] = f"{stage_name}: {e}"
                    return agent_state, True

        # === Stage 1: planner writes GOALS.md ===
        planner = basic_planner(
            working_dir=working_dir,
            tools=tools,
            max_continuations=max_continuations,
            model=model,
            skills=skills,
            activity_tracker=tracker,
        )
        _, stalled = await run_stage(
            planner,
            "basic_planner",
            f"Read {INITIAL_INSTRUCTIONS_FILE} and write GOALS.md.",
        )

        # === Stage 2: executor verifies every goal ===
        agent_state: AgentState | None = None
        if not stalled:
            agent = basic_agent(
                working_dir=working_dir,
                tools=tools,
                max_continuations=max_continuations,
                model=model,
                skills=skills,
                activity_tracker=tracker,
            )
            agent_state, stalled = await run_stage(
                agent,
                "basic_agent",
                "Begin the task.",
            )
            if not stalled:
                state.metadata["agent_status"] = "completed"

        if agent_state is not None and agent_state.output.choices:
            state.metadata["stop_reason"] = agent_state.output.stop_reason

        if snapshot_dir:
            snap_path = Path(snapshot_dir) / f"agent_{state.sample_id}.tar.gz"
            if await snapshot_workspace(working_dir, snap_path):
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
    mig_uuids: list[str] | None = None,
) -> Task:
    """Create an Inspect Task using the basic single-loop agent."""
    if isinstance(task_instructions, str):
        task_instructions = [task_instructions]

    env_contents = None
    if env_file:
        env_contents = Path(env_file).read_text()

    if mig_uuids is not None:
        if len(task_instructions) > len(mig_uuids):
            raise ValueError(
                f"Need {len(task_instructions)} MIG UUIDs but only "
                f"{len(mig_uuids)} available. Reduce K or add more MIG slices."
            )
        samples = [
            Sample(input=instr, id=i, metadata={"MIG_UUID": mig_uuids[i]})
            for i, instr in enumerate(task_instructions)
        ]
    else:
        samples = [
            Sample(input=instr, id=i) for i, instr in enumerate(task_instructions)
        ]

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
