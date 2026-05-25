from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Literal

from inspect_ai import Task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import SandboxEnvironmentType, sandbox

PiAgentMode = Literal["prompt", "init-planner", "goal-mode", "ryan-loop"]

SNAPSHOT_PATTERN_EXCLUDES = (
    "__pycache__",
    "*.pyc",
    ".venv",
    "venv",
    "node_modules",
    ".cache",
    "huggingface",
    "models--*",
    "*.safetensors",
    "*.bin",
    "*.gguf",
    "*.onnx",
)
SNAPSHOT_MAX_FILE_SIZE_MB = 100


def default_goal_prompt(proposal_file: str) -> str:
    return (
        f"/goal Complete the project described in {proposal_file}. Use the planner artifacts in ./planner "
        "as guidance. Continue iterating autonomously until the project is complete, write useful reviewable "
        "artifacts, and verify the result before stopping."
    )


def _shell_join(args: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in args)


def _source_env_prefix(env_path: str) -> str:
    quoted = shlex.quote(env_path)
    return f"if [ -f {quoted} ]; then set -a; . {quoted}; set +a; fi; "


async def _file_exists(path: str) -> bool:
    result = await sandbox().exec(["test", "-f", path], timeout=5)
    return result.success


def _docker_sandbox():
    from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
    from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy

    sb = sandbox()
    sb_inner = sb._sandbox if isinstance(sb, SandboxEnvironmentProxy) else sb
    return sb_inner if isinstance(sb_inner, DockerSandboxEnvironment) else None


async def copy_from_sandbox(sandbox_path: str, host_path: Path) -> bool:
    if not await _file_exists(sandbox_path):
        return False

    host_path.parent.mkdir(parents=True, exist_ok=True)
    docker_sandbox = _docker_sandbox()
    if docker_sandbox is not None:
        from inspect_ai.util._sandbox.docker.compose import compose_cp

        try:
            await compose_cp(
                src=f"{docker_sandbox._service}:{sandbox_path}",
                dest=host_path.name,
                project=docker_sandbox._project,
                cwd=str(host_path.parent),
                output_limit=None,
            )
            return True
        except RuntimeError:
            return False

    host_path.write_text(await sandbox().read_file(sandbox_path, text=True))
    return True


async def snapshot_workspace(working_dir: str, dest: Path) -> bool:
    from inspect_ai.util._sandbox.docker.compose import compose_cp

    docker_sandbox = _docker_sandbox()
    if docker_sandbox is None:
        return False

    sb = sandbox()
    tar_path = "/tmp/workspace_snapshot.tar.gz"
    size_excludes = "/tmp/workspace_snapshot_size_excludes.txt"
    size_list = await sb.exec(
        [
            "bash",
            "-lc",
            (
                f"cd {shlex.quote(working_dir)} && "
                f"find . -type f -size +{SNAPSHOT_MAX_FILE_SIZE_MB}M "
                f"-printf '%P\\n' > {shlex.quote(size_excludes)}"
            ),
        ],
        timeout=60,
    )
    if not size_list.success:
        return False

    tar_cmd = ["tar", "czf", tar_path, "--exclude-from", size_excludes]
    for pattern in SNAPSHOT_PATTERN_EXCLUDES:
        tar_cmd.append(f"--exclude={pattern}")
    tar_cmd += ["-C", working_dir, "."]

    result = await sb.exec(tar_cmd, timeout=120)
    if not result.success:
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        await compose_cp(
            src=f"{docker_sandbox._service}:{tar_path}",
            dest=dest.name,
            project=docker_sandbox._project,
            cwd=str(dest.parent),
            output_limit=None,
        )
    except RuntimeError:
        return False
    return True


def _commands_for_mode(
    mode: PiAgentMode,
    prompt: str | None,
    run_loop_args: str,
    proposal_file: str,
) -> list[str]:
    if mode == "prompt":
        if not prompt:
            raise ValueError("prompt mode requires a prompt")
        return [prompt]
    if mode == "init-planner":
        return ["/init-planner"]
    if mode == "goal-mode":
        return ["/init-planner", prompt or default_goal_prompt(proposal_file)]
    return ["/init-planner", f"/run-loop {run_loop_args}".strip()]


def planner_initial_instructions(proposal_file: str) -> str:
    return (
        "# Initial Instructions\n\n"
        f"Read {proposal_file}. Create a concrete Ryan-style execution plan for completing the project. "
        "The plan should identify the core objective, decompose the work into useful segments/phases, "
        "call out risks and likely failure modes, and produce a strong first phase that makes real progress "
        "without trying to complete the entire project shallowly.\n"
    )


async def _write_inputs(
    working_dir: str,
    proposal: str,
    proposal_file: str,
    env_contents: str | None,
) -> None:
    sb = sandbox()
    await sb.exec(["mkdir", "-p", working_dir, f"{working_dir}/planner"], timeout=10)
    await sb.write_file(f"{working_dir}/{proposal_file}", proposal)
    await sb.write_file(
        f"{working_dir}/planner/INITIAL_INSTRUCTIONS.md",
        planner_initial_instructions(proposal_file),
    )
    if env_contents:
        await sb.write_file(f"{working_dir}/.env", env_contents)


@solver
def pi_agent_solver(
    *,
    mode: PiAgentMode,
    model: str,
    working_dir: str = "/workspace",
    env_contents: str | None = None,
    pi_bin: str = "pi",
    thinking: str = "xhigh",
    transcript_dir: str | None = None,
    snapshot_dir: str | None = None,
    proposal_file: str = "proposal.md",
    prompt: str | None = None,
    run_loop_args: str = "",
    command_timeout: int | None = None,
) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await _write_inputs(working_dir, state.input_text, proposal_file, env_contents)

        session_path = f"{working_dir}/.pi_transcripts/session.jsonl"
        html_path = f"{working_dir}/.pi_transcripts/session.html"
        await sandbox().exec(
            ["mkdir", "-p", f"{working_dir}/.pi_transcripts"], timeout=10
        )

        host_transcript_dir = (
            Path(transcript_dir) / f"agent_{state.sample_id}"
            if transcript_dir
            else None
        )
        if host_transcript_dir:
            host_transcript_dir.mkdir(parents=True, exist_ok=True)

        commands = _commands_for_mode(mode, prompt, run_loop_args, proposal_file)
        runs = []
        status = "completed"
        for index, prompt in enumerate(commands):
            cmd = [
                pi_bin,
                "-p",
                "--session",
                session_path,
                "--model",
                model,
                "--thinking",
                thinking,
                "--mode",
                "json",
                prompt,
            ]
            shell = (
                f"cd {shlex.quote(working_dir)}; "
                f"{_source_env_prefix(f'{working_dir}/.env')}"
                f"{_shell_join(cmd)}"
            )
            exec_kwargs = (
                {"timeout": command_timeout} if command_timeout is not None else {}
            )
            result = await sandbox().exec(["bash", "-lc", shell], **exec_kwargs)
            run = {
                "index": index,
                "prompt": prompt,
                "returncode": getattr(result, "returncode", 0 if result.success else 1),
                "success": result.success,
            }
            runs.append(run)

            if host_transcript_dir:
                (host_transcript_dir / f"command_{index:02d}.events.jsonl").write_text(
                    result.stdout
                )
                (host_transcript_dir / f"command_{index:02d}.stderr.log").write_text(
                    result.stderr
                )

            if not result.success:
                status = "failed"
                break

        session_copied = False
        html_copied = False
        if host_transcript_dir:
            session_copied = await copy_from_sandbox(
                session_path,
                host_transcript_dir / "session.jsonl",
            )
            export_cmd = [pi_bin, "--export", session_path, html_path]
            export_shell = (
                f"cd {shlex.quote(working_dir)}; "
                f"{_source_env_prefix(f'{working_dir}/.env')}"
                f"{_shell_join(export_cmd)}"
            )
            export_result = await sandbox().exec(
                ["bash", "-lc", export_shell], timeout=120
            )
            if export_result.success:
                html_copied = await copy_from_sandbox(
                    html_path,
                    host_transcript_dir / "session.html",
                )
            (host_transcript_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "mode": mode,
                        "model": model,
                        "runs": runs,
                        "proposal_file": proposal_file,
                        "status": status,
                        "session_copied": session_copied,
                        "html_copied": html_copied,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )

        if snapshot_dir:
            snapshot_path = Path(snapshot_dir) / f"agent_{state.sample_id}.tar.gz"
            if await snapshot_workspace(working_dir, snapshot_path):
                state.metadata["snapshot"] = str(snapshot_path)

        state.metadata["pi_status"] = status
        state.metadata["pi_mode"] = mode
        state.metadata["proposal_file"] = proposal_file
        state.metadata["pi_runs"] = runs
        if host_transcript_dir:
            state.metadata["pi_transcript_dir"] = str(host_transcript_dir)
            state.metadata["pi_session_copied"] = session_copied
            state.metadata["pi_html_copied"] = html_copied
        return state

    return solve


def create_pi_agent_task(
    task_instructions: str | list[str],
    *,
    mode: PiAgentMode,
    model: str,
    name: str | None = None,
    sandbox: SandboxEnvironmentType | None = None,
    env_file: str | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    working_dir: str = "/workspace",
    pi_bin: str = "pi",
    thinking: str = "xhigh",
    transcript_dir: str | None = None,
    snapshot_dir: str | None = None,
    proposal_file: str = "proposal.md",
    prompt: str | None = None,
    run_loop_args: str = "",
    command_timeout: int | None = None,
) -> Task:
    if isinstance(task_instructions, str):
        task_instructions = [task_instructions]

    env_contents = Path(env_file).read_text() if env_file else None
    samples = [
        Sample(input=instruction, id=i)
        for i, instruction in enumerate(task_instructions)
    ]

    return Task(
        name=name,
        dataset=samples,
        solver=pi_agent_solver(
            mode=mode,
            model=model,
            working_dir=working_dir,
            env_contents=env_contents,
            pi_bin=pi_bin,
            thinking=thinking,
            transcript_dir=transcript_dir,
            snapshot_dir=snapshot_dir,
            proposal_file=proposal_file,
            prompt=prompt,
            run_loop_args=run_loop_args,
            command_timeout=command_timeout,
        ),
        sandbox=sandbox,
        token_limit=token_limit,
        time_limit=time_limit,
    )
