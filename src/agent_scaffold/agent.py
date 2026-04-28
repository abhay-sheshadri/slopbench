"""Long-horizon agent scaffold on Inspect AI.

Mirrors the Redwood Research agent orchestrator. The core mechanism is exit
promise enforcement: an agent cannot stop unless its output contains an exact
promise string. If it tries to stop without one, a continuation prompt is
injected as a user message to keep it going.

Works with any model via Inspect's get_model().generate().
All file I/O goes through Inspect's sandbox API so the scaffold works
identically on local and Docker (GPU) sandboxes.
"""

import asyncio
import contextlib
import copy
import re
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from inspect_ai.agent import Agent, AgentState
from inspect_ai.model import (
    ChatMessageSystem,
    ChatMessageUser,
    execute_tools,
    get_model,
)
from inspect_ai.model._compaction import Compact, compaction
from inspect_ai.model._compaction.auto import CompactionAuto
from inspect_ai.tool import Tool, skill
from inspect_ai.util import sandbox

from src.utils import load_prompt_file

# ---------------------------------------------------------------------------
# Bundled skills
# ---------------------------------------------------------------------------

SKILLS_DIR = Path(__file__).parent / "skills"

ALL_SKILLS = (
    [
        str(SKILLS_DIR / d)
        for d in sorted(SKILLS_DIR.iterdir())
        if d.is_dir() and (d / "SKILL.md").exists()
    ]
    if SKILLS_DIR.is_dir()
    else []
)

# ---------------------------------------------------------------------------
# File naming conventions — single source of truth
# ---------------------------------------------------------------------------

INITIAL_INSTRUCTIONS_FILE = "INITIAL_INSTRUCTIONS.md"
OVERALL_PLAN_FILE = "OVERALL_PLAN.md"
PLANNER_GUIDANCE_FILE = "PLANNER_GUIDANCE.md"
BASIC_GOALS_FILE = "GOALS.md"


def instructions_file(segment_idx: int, phase_idx: int) -> str:
    return f"INSTRUCTIONS_SEGMENT_{segment_idx}_PHASE_{phase_idx}.md"


def context_file(segment_idx: int, phase_idx: int) -> str:
    return f"context_for_main_planner_after_segment_{segment_idx}_phase_{phase_idx}.md"


def phase_dir_name(segment_idx: int, phase_idx: int) -> str:
    return f"segment_{segment_idx}_phase_{phase_idx}"


def review_message_file(iteration: int, segment_idx: int, phase_idx: int) -> str:
    return f"message_{iteration}_for_phase_planner_segment_{segment_idx}_phase_{phase_idx}.md"


def phase_planner_response_file(
    iteration: int, segment_idx: int, phase_idx: int
) -> str:
    return f"message_to_main_planner_{iteration}_segment_{segment_idx}_phase_{phase_idx}.md"


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

FileCheck = Callable[[str, str | None], Awaitable[str | None]]

_PROMPTS = str(Path(__file__).resolve().parent / "prompts")


def load_prompt(path: str, **kwargs: object) -> str:
    """Load a Jinja2 template from the prompts directory."""
    return load_prompt_file(f"{_PROMPTS}/{path}", **kwargs)


# ---------------------------------------------------------------------------
# Exit promise strings — must appear EXACTLY in agent output to allow exit
# ---------------------------------------------------------------------------

PROMISE_CHECKLIST = (
    "Did I go through the entire task completion checklist? Yes. "
    "Did I address all changes surfaced by the checklist and re-check affected items? "
    "Yes - all changes have been made and affected items re-checked."
)

PROMISE_SIMPLE = (
    "I have reviewed my work and the task is complete. No further work is needed."
)

PROMISE_PLAN = (
    f"I have completed the plan. {OVERALL_PLAN_FILE} and "
    f"{instructions_file(0, 0)} have been written and reviewed."
)

PROMISE_PHASE_MORE_WORK = (
    "I have written instructions for additional work in this segment "
    "and the context file for the main planner."
)

PROMISE_PHASE_NEXT_SEGMENT = (
    "I have written instructions for the next segment "
    "and the context file for the main planner."
)

PROMISE_PHASE_ALL_COMPLETE = (
    "All planned work is complete. "
    "I have written the context file for the main planner."
)

PROMISE_BASIC_PLAN = (
    f"I have written {BASIC_GOALS_FILE} with an exhaustive specification "
    "of every goal of this project."
)

PROMISE_BASIC = (
    f"Did I go through every goal listed in {BASIC_GOALS_FILE}? Yes. "
    "Did I run the verification step the planner specified for each goal? Yes. "
    "Did I address every issue surfaced by verification and re-verify the affected goals? "
    f"Yes - every goal is achieved, every checkbox in {BASIC_GOALS_FILE} is ticked, "
    "and all changes are committed."
)

PROMISE_APPROVE = "I approve the phase planner's instructions."

PROMISE_REJECT = "I have written corrections/feedback/requests for the phase planner."

PHASE_DECISIONS = [
    PROMISE_PHASE_MORE_WORK,
    PROMISE_PHASE_NEXT_SEGMENT,
    PROMISE_PHASE_ALL_COMPLETE,
]


# ---------------------------------------------------------------------------
# Sandbox file helpers
# ---------------------------------------------------------------------------


async def file_exists(path: str) -> bool:
    result = await sandbox().exec(["test", "-f", path], timeout=5)
    return result.success


async def read_file(path: str) -> str:
    return await sandbox().read_file(path, text=True)


async def write_file(path: str, content: str) -> None:
    await sandbox().write_file(path, content)


# ---------------------------------------------------------------------------
# Stall detection
# ---------------------------------------------------------------------------


class StallError(Exception):
    """Raised when an agent has no activity for too long."""

    pass


class ActivityTracker:
    """Tracks timestamps of agent activity for stall detection."""

    def __init__(self) -> None:
        self._last_activity = time.monotonic()

    def ping(self) -> None:
        self._last_activity = time.monotonic()

    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_activity


async def run_with_watchdog(
    coro: Awaitable,
    tracker: ActivityTracker,
    stall_timeout: float,
    label: str = "",
    check_interval: float = 60.0,
):
    """Run a coroutine, cancelling it if the tracker goes idle too long."""
    task = asyncio.ensure_future(coro)
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=check_interval)
            if done:
                break
            idle = tracker.idle_seconds()
            if idle >= stall_timeout:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise StallError(
                    f"{label}: no activity for {idle:.0f}s "
                    f"(limit: {stall_timeout:.0f}s)"
                )
        return task.result()
    except asyncio.CancelledError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        raise


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------


@dataclass
class ExitConfig:
    """Controls when and how the agent is allowed to stop."""

    promises: list[str] = field(default_factory=list)
    continuation_prompt: str = ""
    max_continuations: int = 30
    file_checks: list[FileCheck] = field(default_factory=list)
    working_dir: str | None = None


def find_promise(text: str, promises: list[str]) -> str | None:
    """Return the first promise string found in *text*, or None."""
    for p in promises:
        if p in text:
            return p
    return None


async def _run_file_checks(
    checks: list[FileCheck], working_dir: str | None, promise: str | None
) -> list[str]:
    """Run all file checks and collect error strings."""
    if not checks or working_dir is None:
        return []
    errors = []
    for check in checks:
        err = await check(working_dir, promise)
        if err:
            errors.append(err)
    return errors


# ---------------------------------------------------------------------------
# Built-in file checks
# ---------------------------------------------------------------------------


def check_files_exist(*filenames: str) -> FileCheck:
    """Return a check that verifies the given files exist in working_dir."""

    async def check(working_dir: str, promise: str | None) -> str | None:
        missing = []
        for f in filenames:
            if not await file_exists(f"{working_dir}/{f}"):
                missing.append(f)
        if missing:
            paths = ", ".join(f"`{f}`" for f in missing)
            return f"**Missing files**: {paths} must exist in `{working_dir}` before exiting."
        return None

    return check


def check_planner_files() -> FileCheck:
    return check_files_exist(OVERALL_PLAN_FILE, instructions_file(0, 0))


def check_goals_checklist_complete(goals_file: str = BASIC_GOALS_FILE) -> FileCheck:
    """Verify ``goals_file`` exists and has no unchecked ``- [ ]`` items.

    Used by the basic agent's exit gate so that "every checkbox is ticked"
    in the promise text is grounded in actual file state.
    """
    pattern = re.compile(r"^\s*[-*]\s*\[ \]\s+(.+)$", re.MULTILINE)

    async def check(working_dir: str, promise: str | None) -> str | None:
        path = f"{working_dir}/{goals_file}"
        if not await file_exists(path):
            return (
                f"**Missing file**: `{goals_file}` must exist in `{working_dir}` "
                f"before exiting."
            )
        content = await read_file(path)
        unchecked = pattern.findall(content)
        if not unchecked:
            return None
        preview = "\n".join(f"  - [ ] {item.strip()}" for item in unchecked[:5])
        more = f"\n  ... and {len(unchecked) - 5} more" if len(unchecked) > 5 else ""
        return (
            f"**Unchecked goals in `{goals_file}`**: {len(unchecked)} item(s) "
            "remain unchecked. Verify each one and tick it off "
            f"(change `- [ ]` to `- [x]`) before exiting:\n{preview}{more}"
        )

    return check


def check_phase_planner_files(segment_idx: int, phase_idx: int) -> FileCheck:
    """Check that the phase planner wrote its required output files."""
    ctx = context_file(segment_idx, phase_idx)

    async def check(working_dir: str, promise: str | None) -> str | None:
        errors = []
        if not await file_exists(f"{working_dir}/{ctx}"):
            errors.append(f"**Missing context file**: `{ctx}` must be written.")

        if promise == PROMISE_PHASE_MORE_WORK:
            name = instructions_file(segment_idx, phase_idx + 1)
            if not await file_exists(f"{working_dir}/{name}"):
                errors.append(
                    f"**Missing instruction file**: `{name}` must be written."
                )
        elif promise == PROMISE_PHASE_NEXT_SEGMENT:
            name = instructions_file(segment_idx + 1, 0)
            if not await file_exists(f"{working_dir}/{name}"):
                errors.append(
                    f"**Missing instruction file**: `{name}` must be written."
                )

        return "\n\n".join(errors) if errors else None

    return check


def check_git_clean() -> FileCheck:
    """Check that there are no uncommitted changes."""

    async def check(working_dir: str, promise: str | None) -> str | None:
        result = await sandbox().exec(
            ["git", "status", "--porcelain"],
            cwd=working_dir,
            timeout=10,
        )
        if not result.success:
            return None
        if result.stdout.strip():
            return (
                "**Uncommitted changes**: You have uncommitted changes. "
                "Please commit all changes before exiting."
            )
        return None

    return check


def scaffold_loop(
    tools: list[Tool],
    exit_config: ExitConfig,
    system_prompt: str = "",
    model: str | None = None,
    compact_handler: Compact | None = None,
    activity_tracker: ActivityTracker | None = None,
) -> Agent:
    """Build an agent loop with exit promise enforcement.

    If *system_prompt* is non-empty it is prepended once as a system message.
    The loop generates, executes tools, and repeats. When the model stops
    calling tools, its output is checked for an exit promise. If none is
    found, *continuation_prompt* is injected as a user message and the loop
    continues (up to *max_continuations*).

    If ``exit_config.promises`` is empty, the agent exits as soon as it
    stops calling tools (no enforcement).

    If *compact_handler* is provided, messages are compacted before each
    generate() call to stay within the model's context window.
    """

    async def execute(state: AgentState) -> AgentState:
        if system_prompt:
            state.messages.insert(0, ChatMessageSystem(content=system_prompt))

        continuations = 0
        truncations = 0
        max_truncations = 5

        while True:
            if compact_handler:
                input_messages, summary = await compact_handler.compact_input(
                    state.messages
                )
                if summary:
                    state.messages.append(summary)
            else:
                input_messages = state.messages

            state.output = await get_model(model).generate(
                input=input_messages, tools=tools
            )
            if activity_tracker:
                activity_tracker.ping()
            state.messages.append(state.output.message)

            if compact_handler:
                compact_handler.record_output(state.output)

            if state.output.stop_reason == "model_length":
                truncations += 1
                if truncations >= max_truncations:
                    return state
                state.messages.append(
                    ChatMessageUser(
                        content=(
                            "Your previous response was truncated due to context length limits. "
                            "Continue where you left off."
                        )
                    )
                )
                continue

            if state.output.message.tool_calls:
                tool_result = await execute_tools(state.messages, tools)
                if activity_tracker:
                    activity_tracker.ping()
                state.messages.extend(tool_result.messages)
                continue

            if not exit_config.promises:
                return state

            text = state.output.message.text or ""
            matched = find_promise(text, exit_config.promises)

            if matched:
                errors = await _run_file_checks(
                    exit_config.file_checks, exit_config.working_dir, matched
                )
                if not errors:
                    return state
                file_error_msg = "\n\n".join(errors)
            else:
                file_error_msg = ""

            continuations += 1
            if continuations >= exit_config.max_continuations:
                return state

            nudge = exit_config.continuation_prompt
            if file_error_msg:
                nudge = f"{nudge}\n\n{file_error_msg}"
            state.messages.append(ChatMessageUser(content=nudge))

    return execute


# ---------------------------------------------------------------------------
# Compaction helper
# ---------------------------------------------------------------------------


def make_compact_handler(
    system_prompt: str,
    tools: list[Tool],
    model: str | None = None,
    threshold: float = 0.9,
) -> Compact:
    """Create a CompactionAuto handler for use in scaffold_loop."""
    prefix = [ChatMessageSystem(content=system_prompt)] if system_prompt else []
    return compaction(
        strategy=CompactionAuto(threshold=threshold),
        prefix=prefix,
        tools=tools,
        model=model,
    )


# ---------------------------------------------------------------------------
# Resumption and forking
# ---------------------------------------------------------------------------


async def resume(
    state: AgentState,
    user_message: str,
    tools: list[Tool],
    exit_config: ExitConfig,
    model: str | None = None,
    compact_handler: Compact | None = None,
    activity_tracker: ActivityTracker | None = None,
) -> AgentState:
    """Append a user message to an existing state and run the loop."""
    state.messages.append(ChatMessageUser(content=user_message))
    loop = scaffold_loop(
        tools=tools,
        exit_config=exit_config,
        model=model,
        compact_handler=compact_handler,
        activity_tracker=activity_tracker,
    )
    return await loop(state)


async def fork(
    state: AgentState,
    user_message: str,
    tools: list[Tool],
    exit_config: ExitConfig,
    model: str | None = None,
    compact_handler: Compact | None = None,
    activity_tracker: ActivityTracker | None = None,
) -> AgentState:
    """Deep-copy state, append a user message, and run the loop."""
    return await resume(
        copy.deepcopy(state),
        user_message,
        tools,
        exit_config,
        model=model,
        compact_handler=compact_handler,
        activity_tracker=activity_tracker,
    )


# ---------------------------------------------------------------------------
# Agent factories
# ---------------------------------------------------------------------------


def worker(
    working_dir: str,
    tools: list[Tool],
    *,
    instructions: str = "",
    simple: bool = False,
    software_task: bool = True,
    subsidized: bool = False,
    extra_guidance: str = "",
    extra_checklist_items: list[str] | None = None,
    max_continuations: int = 30,
    model: str | None = None,
    compaction_threshold: float = 0.9,
    skills: list[str] | None = None,
    activity_tracker: ActivityTracker | None = None,
) -> Agent:
    """Create a worker agent with anti-stopping prompt and checklist.

    The worker reads its task from ``INITIAL_INSTRUCTIONS.md`` in its working
    directory.  If *instructions* is provided, it is inlined in the system
    prompt instead.

    If *skills* is provided, the ``skill()`` tool is added so the agent can
    load skill instructions on demand.  Defaults to all bundled skills.
    """
    if skills is None:
        skills = ALL_SKILLS
    if skills:
        tools = [*tools, skill(skills)]

    promise = PROMISE_SIMPLE if simple else PROMISE_CHECKLIST

    parts = [load_prompt("advanced/worker/anti_stopping.jinja2", subsidized=subsidized)]

    if instructions:
        task_section = (
            f"# Task Instructions\n\n{instructions}\n\n"
            "You are operating autonomously."
            f"\n\nYour current working directory is {working_dir}."
        )
    else:
        task_section = (
            f"Your current working directory is {working_dir}. "
            f"Read `{INITIAL_INSTRUCTIONS_FILE}` in your working directory "
            f"for your task instructions.\n\n"
            "You are operating autonomously."
        )
    parts.append(task_section)

    if not simple:
        parts.append(
            load_prompt(
                "advanced/worker/checklist.jinja2",
                exit_promise=promise,
                software_task=software_task,
                extra_checklist_items=extra_checklist_items or [],
            )
        )

    if extra_guidance:
        parts.append(extra_guidance)

    sys_prompt = "\n\n".join(parts)
    return scaffold_loop(
        tools=tools,
        exit_config=ExitConfig(
            promises=[promise],
            continuation_prompt=load_prompt(
                "advanced/worker/continuation.jinja2",
                simple=simple,
                exit_promise=promise,
            ),
            max_continuations=max_continuations,
        ),
        system_prompt=sys_prompt,
        model=model,
        compact_handler=make_compact_handler(
            sys_prompt,
            tools,
            model,
            compaction_threshold,
        ),
        activity_tracker=activity_tracker,
    )


def basic_planner(
    working_dir: str,
    tools: list[Tool],
    *,
    max_continuations: int = 30,
    model: str | None = None,
    compaction_threshold: float = 0.9,
    skills: list[str] | None = None,
    activity_tracker: ActivityTracker | None = None,
) -> Agent:
    """Basic-mode planner: writes ``GOALS.md`` with an exhaustive list of
    project goals (and a verification step for each) for the executor agent.
    """
    if skills is None:
        skills = ALL_SKILLS
    if skills:
        tools = [*tools, skill(skills)]

    sys_prompt = load_prompt(
        "basic/planner/system.jinja2",
        working_dir=working_dir,
        instructions_file=INITIAL_INSTRUCTIONS_FILE,
        goals_file=BASIC_GOALS_FILE,
        exit_promise=PROMISE_BASIC_PLAN,
    )
    return scaffold_loop(
        tools=tools,
        exit_config=ExitConfig(
            promises=[PROMISE_BASIC_PLAN],
            continuation_prompt=load_prompt(
                "basic/planner/continuation.jinja2",
                instructions_file=INITIAL_INSTRUCTIONS_FILE,
                goals_file=BASIC_GOALS_FILE,
                exit_promise=PROMISE_BASIC_PLAN,
            ),
            max_continuations=max_continuations,
            file_checks=[check_files_exist(BASIC_GOALS_FILE), check_git_clean()],
            working_dir=working_dir,
        ),
        system_prompt=sys_prompt,
        model=model,
        compact_handler=make_compact_handler(
            sys_prompt,
            tools,
            model,
            compaction_threshold,
        ),
        activity_tracker=activity_tracker,
    )


def basic_agent(
    working_dir: str,
    tools: list[Tool],
    *,
    max_continuations: int = 30,
    model: str | None = None,
    compaction_threshold: float = 0.9,
    skills: list[str] | None = None,
    activity_tracker: ActivityTracker | None = None,
) -> Agent:
    """Basic-mode executor: reads ``INITIAL_INSTRUCTIONS.md`` and ``GOALS.md``,
    completes the project, and exits only when every goal in ``GOALS.md`` has
    been verified achieved.
    """
    if skills is None:
        skills = ALL_SKILLS
    if skills:
        tools = [*tools, skill(skills)]

    sys_prompt = load_prompt(
        "basic/agent/system.jinja2",
        working_dir=working_dir,
        instructions_file=INITIAL_INSTRUCTIONS_FILE,
        goals_file=BASIC_GOALS_FILE,
        exit_promise=PROMISE_BASIC,
    )
    return scaffold_loop(
        tools=tools,
        exit_config=ExitConfig(
            promises=[PROMISE_BASIC],
            continuation_prompt=load_prompt(
                "basic/agent/continuation.jinja2",
                goals_file=BASIC_GOALS_FILE,
                exit_promise=PROMISE_BASIC,
            ),
            max_continuations=max_continuations,
            file_checks=[
                check_goals_checklist_complete(BASIC_GOALS_FILE),
                check_git_clean(),
            ],
            working_dir=working_dir,
        ),
        system_prompt=sys_prompt,
        model=model,
        compact_handler=make_compact_handler(
            sys_prompt,
            tools,
            model,
            compaction_threshold,
        ),
        activity_tracker=activity_tracker,
    )


def planner(
    working_dir: str,
    tools: list[Tool],
    *,
    has_initial_dir: bool = False,
    max_continuations: int = 30,
    model: str | None = None,
    compaction_threshold: float = 0.9,
    skills: list[str] | None = None,
    activity_tracker: ActivityTracker | None = None,
) -> Agent:
    """Create a main planner agent that decomposes a task into segments."""
    if skills is None:
        skills = ALL_SKILLS
    if skills:
        tools = [*tools, skill(skills)]

    sys_prompt = load_prompt(
        "advanced/planner/system.jinja2",
        working_dir=working_dir,
        has_initial_dir=has_initial_dir,
    )
    return scaffold_loop(
        tools=tools,
        exit_config=ExitConfig(
            promises=[PROMISE_PLAN],
            continuation_prompt=load_prompt(
                "advanced/planner/continuation.jinja2",
                exit_promise=PROMISE_PLAN,
            ),
            max_continuations=max_continuations,
            file_checks=[check_planner_files(), check_git_clean()],
            working_dir=working_dir,
        ),
        system_prompt=sys_prompt,
        model=model,
        compact_handler=make_compact_handler(
            sys_prompt,
            tools,
            model,
            compaction_threshold,
        ),
        activity_tracker=activity_tracker,
    )


def phase_planner_prompt(
    segment_idx: int,
    phase_idx: int,
    phase_dir: str,
    planner_dir: str,
    completed_phase_name: str,
    allow_stop: bool = True,
) -> tuple[str, ExitConfig]:
    """Build the prompt and exit config for a phase planner.

    Returns (user_message, exit_config) — the caller forks the main planner
    state and passes these to ``fork()`` or ``resume()``.
    """
    promises = list(PHASE_DECISIONS) if allow_stop else PHASE_DECISIONS[:2]

    prompt_kwargs = dict(
        segment_idx=segment_idx,
        phase_idx=phase_idx,
        phase_dir=phase_dir,
        planner_dir=planner_dir,
        completed_phase_name=completed_phase_name,
        allow_stop=allow_stop,
        promise_more_work=PROMISE_PHASE_MORE_WORK,
        promise_next_segment=PROMISE_PHASE_NEXT_SEGMENT,
        promise_all_complete=PROMISE_PHASE_ALL_COMPLETE,
    )

    return (
        load_prompt("advanced/phase_planner/system.jinja2", **prompt_kwargs),
        ExitConfig(
            promises=promises,
            continuation_prompt=load_prompt(
                "advanced/phase_planner/continuation.jinja2", **prompt_kwargs
            ),
            file_checks=[
                check_phase_planner_files(segment_idx, phase_idx),
                check_git_clean(),
            ],
            working_dir=planner_dir,
        ),
    )


def planner_review_prompt(
    segment_idx: int,
    phase_idx: int,
    completed_phase_name: str,
    working_dir: str,
    ctx_file: str,
    instr_file: str | None = None,
    is_all_complete: bool = False,
    iteration: int = 0,
    phase_planner_message_file: str = "",
    message_file: str = "",
) -> tuple[str, ExitConfig]:
    """Build the prompt and exit config for main planner review.

    Returns (user_message, exit_config) — the caller passes these to
    ``resume()`` on the main planner's state.
    """
    return (
        load_prompt(
            "advanced/planner/review.jinja2",
            segment_idx=segment_idx,
            phase_idx=phase_idx,
            completed_phase_name=completed_phase_name,
            working_dir=working_dir,
            context_file=ctx_file,
            instructions_file=instr_file,
            is_all_complete=is_all_complete,
            iteration=iteration,
            phase_planner_message_file=phase_planner_message_file,
            message_file=message_file,
            approve_promise=PROMISE_APPROVE,
            reject_promise=PROMISE_REJECT,
        ),
        ExitConfig(
            promises=[PROMISE_APPROVE, PROMISE_REJECT],
            continuation_prompt=load_prompt(
                "advanced/planner/review_continuation.jinja2",
                approve_promise=PROMISE_APPROVE,
                reject_promise=PROMISE_REJECT,
            ),
        ),
    )
