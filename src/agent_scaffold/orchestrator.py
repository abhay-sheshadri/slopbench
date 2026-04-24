"""Orchestrator: planner → worker → phase planner → review → repeat."""

import uuid
from dataclasses import dataclass, field

import yaml
from inspect_ai.agent import AgentState
from inspect_ai.event import (
    EventTreeSpan,
    event_sequence,
    event_tree,
    event_tree_walk,
    timeline_build,
)
from inspect_ai.log import transcript
from inspect_ai.model import ChatMessageUser
from inspect_ai.tool import Tool, bash, python, text_editor
from inspect_ai.util import sandbox, span

from .agent import (
    INITIAL_INSTRUCTIONS_FILE,
    OVERALL_PLAN_FILE,
    PHASE_DECISIONS,
    PLANNER_GUIDANCE_FILE,
    PROMISE_APPROVE,
    PROMISE_PHASE_ALL_COMPLETE,
    PROMISE_PHASE_MORE_WORK,
    PROMISE_PHASE_NEXT_SEGMENT,
    ActivityTracker,
    StallError,
    context_file,
    file_exists,
    find_promise,
    fork,
    instructions_file,
    load_prompt,
    make_compact_handler,
    phase_dir_name,
    phase_planner_prompt,
    phase_planner_response_file,
    planner,
    planner_review_prompt,
    read_file,
    resume,
    review_message_file,
    run_with_watchdog,
    worker,
    write_file,
)


@dataclass
class PhaseResult:
    segment_idx: int
    phase_idx: int
    name: str
    phase_dir: str
    phase_planner_decision: str | None = None


@dataclass
class OrchestratorResult:
    status: str  # "completed" | "failed" | "max_phases" | "stalled"
    phases: list[PhaseResult] = field(default_factory=list)
    planner_dir: str | None = None
    final_dir: str | None = None
    workspace_tar: bytes | None = None


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

PLANNER_ARTIFACTS = {
    PLANNER_GUIDANCE_FILE,
}


def _parse_phase_name(text: str, fallback: str) -> str:
    """Extract the 'name' field from instruction file YAML frontmatter."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1])
                if isinstance(meta, dict) and "name" in meta:
                    return meta["name"]
            except yaml.YAMLError:
                pass
    return fallback


async def _init_git(directory: str) -> None:
    """Initialize a git repo with an initial commit if not already one."""
    sb = sandbox()
    result = await sb.exec(["test", "-d", f"{directory}/.git"], timeout=5)
    if result.success:
        return

    # Write .gitignore before adding files
    await sb.exec(
        [
            "bash",
            "-c",
            f"test -f {directory}/.gitignore || echo '.env' > {directory}/.gitignore",
        ],
        timeout=5,
    )
    for cmd in [
        ["git", "init"],
        ["git", "config", "user.email", "agent@scaffold.local"],
        ["git", "config", "user.name", "Agent Scaffold"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", "Initial setup", "--allow-empty"],
    ]:
        await sb.exec(cmd, cwd=directory, timeout=10)


async def _setup_worker_dir(
    source: str,
    dest: str,
    raw_instructions: str,
    overall_plan: str,
    completed_phases: list[PhaseResult],
) -> None:
    """Prepare a sandboxed worker directory.

    Clones *source* into *dest*, removes planner-only artifacts, and writes
    the standardized files the worker reads on startup.
    """
    sb = sandbox()
    await sb.exec(["rm", "-rf", dest], timeout=30)
    result = await sb.exec(["cp", "-r", source, dest], timeout=30)
    assert result.success, f"Failed to copy {source} -> {dest}: {result.stderr}"

    # Remove planner-only artifacts and inter-agent communication files
    cleanup = "\n".join(
        [f"rm -f {dest}/{name}" for name in PLANNER_ARTIFACTS]
        + [
            f"rm -f {dest}/INSTRUCTIONS_SEGMENT_*.md",
            f"rm -f {dest}/context_for_main_planner_*.md",
            f"rm -f {dest}/message_*_for_phase_planner_*.md",
            f"rm -f {dest}/message_to_main_planner_*.md",
        ]
    )
    await sb.exec(["bash", "-c", cleanup], timeout=10)

    body = raw_instructions
    if completed_phases:
        body += (
            "\n\n# Understanding the current project state\n\n"
            "You are continuing a broader task/project. Review relevant files "
            "in the directory (write-ups, code, etc.) to understand what has "
            "already been done.\n\n"
            "# Prior phases (already completed)\n\n"
        )
        for p in completed_phases:
            body += f"- Segment {p.segment_idx}, Phase {p.phase_idx} ({p.name})\n"

    body += (
        f"\n\n# Overall Plan (Optional Reference)\n\n"
        f"The overall plan for the broader task/project can be found in "
        f"{OVERALL_PLAN_FILE}. You don't necessarily need to read it, but it "
        f"may provide useful context. (Don't modify {OVERALL_PLAN_FILE}.)"
    )

    await write_file(f"{dest}/{INITIAL_INSTRUCTIONS_FILE}", body)
    await write_file(f"{dest}/{OVERALL_PLAN_FILE}", overall_plan)


def _next_instructions_file(
    decision: str | None, segment_idx: int, phase_idx: int
) -> str | None:
    if decision == PROMISE_PHASE_MORE_WORK:
        return instructions_file(segment_idx, phase_idx + 1)
    if decision == PROMISE_PHASE_NEXT_SEGMENT:
        return instructions_file(segment_idx + 1, 0)
    return None


def _decision_label(decision: str | None) -> str:
    labels = {
        PROMISE_PHASE_MORE_WORK: "more_work",
        PROMISE_PHASE_NEXT_SEGMENT: "next_segment",
        PROMISE_PHASE_ALL_COMPLETE: "all_complete",
    }
    return labels.get(decision, "unknown")


# ---------------------------------------------------------------------------
# Workspace snapshot
# ---------------------------------------------------------------------------


async def _snapshot_workspace(working_dir: str) -> bytes | None:
    """Tar+gzip the workspace and return raw bytes."""
    sb = sandbox()
    tar_path = "/tmp/workspace_snapshot.tar.gz"
    result = await sb.exec(
        ["tar", "czf", tar_path, "-C", working_dir, "."],
        timeout=120,
    )
    if not result.success:
        return None
    return await sb.read_file(tar_path, text=False)


# ---------------------------------------------------------------------------
# Timeline helpers
# ---------------------------------------------------------------------------


def _find_span(tree: list, span_id: str) -> EventTreeSpan | None:
    for node in event_tree_walk(tree):
        if isinstance(node, EventTreeSpan) and node.id == span_id:
            return node
    return None


def _add_timelines(span_ids: list[tuple[str, str]]) -> None:
    """Build and register timelines from collected (name, span_id) pairs."""
    events = transcript().events
    tree = event_tree(events)
    for name, sid in span_ids:
        node = _find_span(tree, sid)
        if node is None:
            continue
        tl = timeline_build(
            list(event_sequence(node.children)),
            name=name,
        )
        transcript().add_timeline(tl)


# ---------------------------------------------------------------------------
# Main orchestration loop
# ---------------------------------------------------------------------------


async def run(
    task_instructions: str,
    working_dir: str = "/workspace",
    *,
    tools: list[Tool] | None = None,
    env_contents: str | None = None,
    max_phases: int = 10,
    max_review_iterations: int = 5,
    max_continuations: int = 15,
    simple_worker: bool = True,
    has_initial_dir: bool = False,
    planning_only: bool = False,
    verbose: bool = True,
    planner_model: str | None = None,
    worker_model: str | None = None,
    phase_planner_model: str | None = None,
    skills: list[str] | None = None,
    stall_timeout: float | None = 1800,
) -> OrchestratorResult:
    """Run the full orchestration lifecycle."""
    if phase_planner_model is None:
        phase_planner_model = planner_model

    if tools is None:
        tools = [bash(), text_editor(), python()]

    compaction_threshold = 0.9
    tracker = ActivityTracker() if stall_timeout else None

    async def watched(coro, label: str):
        """Run coro with stall detection if enabled."""
        if tracker:
            tracker.ping()
            return await run_with_watchdog(coro, tracker, stall_timeout, label=label)
        return await coro

    sb = sandbox()
    planner_dir = f"{working_dir}/planner"
    await sb.exec(["mkdir", "-p", planner_dir], timeout=10)

    result = OrchestratorResult(status="failed", planner_dir=planner_dir)
    span_ids: list[tuple[str, str]] = []

    def log(msg: str):
        if verbose:
            print(msg)

    async def finalize() -> OrchestratorResult:
        _add_timelines(span_ids)
        log("  Snapshotting workspace...")
        result.workspace_tar = await _snapshot_workspace(working_dir)
        return result

    # --- Write planner inputs ---
    await write_file(f"{planner_dir}/{INITIAL_INSTRUCTIONS_FILE}", task_instructions)
    guidance = load_prompt("planner/guidance.jinja2")
    await write_file(f"{planner_dir}/{PLANNER_GUIDANCE_FILE}", guidance)

    if env_contents:
        await write_file(f"{planner_dir}/.env", env_contents)

    await _init_git(planner_dir)

    # === Step 1: Run main planner ===
    log("=== Running main planner ===")
    planner_agent = planner(
        working_dir=planner_dir,
        tools=tools,
        has_initial_dir=has_initial_dir,
        max_continuations=max_continuations,
        model=planner_model,
        skills=skills,
        activity_tracker=tracker,
    )
    planner_state = AgentState(
        messages=[
            ChatMessageUser(
                content=f"Read {INITIAL_INSTRUCTIONS_FILE} and begin planning.",
            )
        ]
    )
    planner_span_id = uuid.uuid4().hex
    async with span("main_planner", type="agent", id=planner_span_id):
        try:
            planner_state = await watched(planner_agent(planner_state), "main_planner")
        except StallError as e:
            log(f"  STALL: {e}")
            return await finalize()
    span_ids.append(("Main Planner", planner_span_id))
    log(f"  Planner finished (stop_reason={planner_state.output.stop_reason})")

    first_instr = f"{planner_dir}/{instructions_file(0, 0)}"
    if not await file_exists(first_instr):
        log(f"  ERROR: Planner did not create {instructions_file(0, 0)}")
        return await finalize()

    if planning_only:
        log("  Planning only — stopping after planner.")
        result.status = "completed"
        return await finalize()

    # === Phase loop ===
    segment_idx = 0
    phase_idx = 0
    current_source = planner_dir

    for phase_count in range(max_phases):
        instr_name = instructions_file(segment_idx, phase_idx)
        instr_path = f"{planner_dir}/{instr_name}"
        if not await file_exists(instr_path):
            log(f"  ERROR: Missing {instr_name}")
            break

        raw_instr = await read_file(instr_path)
        phase_name = _parse_phase_name(raw_instr, instr_name)
        completed_name = phase_dir_name(segment_idx, phase_idx)
        log(f"\n=== Phase {phase_count}: {completed_name} ({phase_name}) ===")

        # --- Set up sandboxed worker directory ---
        plan_path = f"{planner_dir}/{OVERALL_PLAN_FILE}"
        overall_plan = ""
        if await file_exists(plan_path):
            overall_plan = await read_file(plan_path)

        phase_path = f"{working_dir}/{completed_name}"
        await _setup_worker_dir(
            source=current_source,
            dest=phase_path,
            raw_instructions=raw_instr,
            overall_plan=overall_plan,
            completed_phases=result.phases,
        )
        if env_contents:
            await write_file(f"{phase_path}/.env", env_contents)
        await _init_git(phase_path)

        # --- Run worker ---
        log(f"  Running worker in {completed_name}/...")
        worker_agent = worker(
            working_dir=phase_path,
            tools=tools,
            simple=simple_worker,
            max_continuations=max_continuations,
            model=worker_model,
            skills=skills,
            activity_tracker=tracker,
        )
        worker_state = AgentState(messages=[ChatMessageUser(content="Begin the task.")])
        worker_span_id = uuid.uuid4().hex
        worker_stalled = False
        async with span(f"worker_{completed_name}", type="agent", id=worker_span_id):
            try:
                worker_state = await watched(
                    worker_agent(worker_state),
                    f"worker_{completed_name}",
                )
            except StallError as e:
                log(f"  STALL: {e}")
                worker_stalled = True
        span_ids.append((f"Worker: {completed_name} ({phase_name})", worker_span_id))
        if worker_stalled:
            result.status = "stalled"
            result.final_dir = phase_path
            return await finalize()
        log(f"  Worker finished (stop_reason={worker_state.output.stop_reason})")

        current_source = phase_path

        # --- Run phase planner (forked from main planner) ---
        log("  Running phase planner...")
        phase_msg, phase_exit = phase_planner_prompt(
            segment_idx=segment_idx,
            phase_idx=phase_idx,
            phase_dir=phase_path,
            planner_dir=planner_dir,
            completed_phase_name=completed_name,
        )
        pp_compact = make_compact_handler(
            "",
            tools,
            phase_planner_model,
            compaction_threshold,
        )
        pp_span_id = uuid.uuid4().hex
        phase_stalled = False
        async with span(f"phase_planner_{completed_name}", type="agent", id=pp_span_id):
            try:
                phase_planner_state = await watched(
                    fork(
                        state=planner_state,
                        user_message=phase_msg,
                        tools=tools,
                        exit_config=phase_exit,
                        model=phase_planner_model,
                        compact_handler=pp_compact,
                        activity_tracker=tracker,
                    ),
                    f"phase_planner_{completed_name}",
                )
            except StallError as e:
                log(f"  STALL: {e}")
                phase_stalled = True
        span_ids.append((f"Phase Planner: {completed_name} ({phase_name})", pp_span_id))
        if phase_stalled:
            result.status = "stalled"
            result.final_dir = phase_path
            return await finalize()

        decision = find_promise(
            phase_planner_state.output.message.text or "",
            PHASE_DECISIONS,
        )
        log(f"  Phase planner decision: {_decision_label(decision)}")

        result.phases.append(
            PhaseResult(
                segment_idx=segment_idx,
                phase_idx=phase_idx,
                name=phase_name,
                phase_dir=phase_path,
                phase_planner_decision=_decision_label(decision),
            )
        )

        # --- Main planner review/approval cycle ---
        ctx = context_file(segment_idx, phase_idx)
        next_instr = _next_instructions_file(decision, segment_idx, phase_idx)
        is_all_complete = decision == PROMISE_PHASE_ALL_COMPLETE

        approved = False
        review_stalled = False
        review_compact = make_compact_handler(
            "",
            tools,
            planner_model,
            compaction_threshold,
        )
        review_span_id = uuid.uuid4().hex
        async with span(f"review_{completed_name}", type="agent", id=review_span_id):
            for iteration in range(max_review_iterations):
                msg_file = review_message_file(iteration, segment_idx, phase_idx)
                pp_msg_file = phase_planner_response_file(
                    iteration, segment_idx, phase_idx
                )

                review_msg, review_exit = planner_review_prompt(
                    segment_idx=segment_idx,
                    phase_idx=phase_idx,
                    completed_phase_name=completed_name,
                    working_dir=planner_dir,
                    ctx_file=ctx,
                    instr_file=next_instr,
                    is_all_complete=is_all_complete,
                    iteration=iteration,
                    phase_planner_message_file=pp_msg_file,
                    message_file=msg_file,
                )

                log(f"  Main planner review (iteration {iteration})...")
                try:
                    planner_state = await watched(
                        resume(
                            state=planner_state,
                            user_message=review_msg,
                            tools=tools,
                            exit_config=review_exit,
                            model=planner_model,
                            compact_handler=review_compact,
                            activity_tracker=tracker,
                        ),
                        f"review_{completed_name}_iter{iteration}",
                    )
                except StallError as e:
                    log(f"  STALL: {e}")
                    review_stalled = True
                    break

                if PROMISE_APPROVE in (planner_state.output.message.text or ""):
                    log("  Main planner: APPROVED")
                    approved = True
                    break

                # Rejected — resume phase planner with feedback
                log("  Main planner: REJECTED, sending feedback to phase planner...")

                try:
                    phase_planner_state = await watched(
                        resume(
                            state=phase_planner_state,
                            user_message=(
                                f"The main planner has provided feedback (iteration {iteration}).\n\n"
                                f"**Feedback**: Read `{msg_file}` in your working directory.\n\n"
                                f"Revise your output files accordingly, then write your response to "
                                f"`{pp_msg_file}`.\n\n"
                                f"Then output the appropriate exit promise."
                            ),
                            tools=tools,
                            exit_config=phase_exit,
                            model=phase_planner_model,
                            compact_handler=pp_compact,
                            activity_tracker=tracker,
                        ),
                        f"phase_planner_review_{completed_name}_iter{iteration}",
                    )
                except StallError as e:
                    log(f"  STALL: {e}")
                    review_stalled = True
                    break

            if not review_stalled:
                decision = find_promise(
                    phase_planner_state.output.message.text or "",
                    PHASE_DECISIONS,
                )
                next_instr = _next_instructions_file(decision, segment_idx, phase_idx)
                is_all_complete = decision == PROMISE_PHASE_ALL_COMPLETE

        span_ids.append((f"Review: {completed_name} ({phase_name})", review_span_id))

        if review_stalled:
            result.status = "stalled"
            result.final_dir = phase_path
            return await finalize()

        if not approved:
            log("  WARNING: Max review iterations reached, proceeding")

        # --- Advance ---
        if is_all_complete:
            log("\n=== All work complete ===")
            result.status = "completed"
            result.final_dir = phase_path
            _add_timelines(span_ids)
            return result

        if decision == PROMISE_PHASE_MORE_WORK:
            phase_idx += 1
        else:
            segment_idx += 1
            phase_idx = 0

    result.status = "max_phases"
    result.final_dir = current_source
    log(f"\n=== Reached max phases ({max_phases}) ===")
    return await finalize()
