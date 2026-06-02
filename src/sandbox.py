"""Filesystem/GPU sandbox for agent runs, using bubblewrap (``bwrap``).

Replaces the old per-run Docker container. The model is deliberately small:

  - the run's output directory is bind-mounted read-write as ``/workspace`` and
    is the agent's cwd; the rest of the host root is hidden,
  - the host toolchain (OS dirs, node, the pi agent cloned at ``<repo>/abhay-pi``
    plus its ``scripts/abhay-pi`` launcher, and the project venv + its
    interpreter) is bind-mounted **read-only**,
  - a fresh ``/dev`` (``--dev``) means the sandbox never sees the host's
    ``/dev/nvidia*`` devices, so CPU-only runs can't touch the GPUs,
  - ``HOME`` lives inside the workspace (``/workspace/.home``) so the agent's
    ``~/.pi`` sub-agent sessions land in the run dir automatically — no copy-out.

Teardown is automatic: ``--unshare-pid`` makes bwrap PID 1 of a private PID
namespace and ``--die-with-parent`` tears the whole process tree down when the
launcher (or the per-command ``timeout``) exits. There is no daemon, no image to
build, and no ``docker rm -f`` — killing the bwrap process reaps everything.

Network is intentionally *shared* with the host (no ``--unshare-net``): the agent
needs outbound HTTPS to reach the model APIs, exactly as the Docker runner did.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WORKSPACE = "/workspace"
HOME = "/workspace/.home"
ABHAY_PI_DIR = Path(os.environ.get("ABHAY_PI_DIR", str(ROOT / "abhay-pi")))

# The `pi`/`abhay-pi` launchers in /usr/local/bin are symlinks to this wrapper;
# bind it so those symlinks resolve inside the sandbox (where the agent runs
# `pi` directly). /usr/local itself is covered by the /usr read-only bind.
_PI_WRAPPER = ROOT / "scripts" / "abhay-pi"

# Read-only host OS paths bound into every sandbox (only those that exist are
# used). These provide bash, coreutils (`timeout`), node, the `pi` launcher under
# /usr/local, CA certs + DNS config under /etc, and the shared libraries.
_OS_RO_PATHS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32", "/etc")


def available() -> str | None:
    """Return the bwrap executable path, or ``None`` if it isn't installed."""
    return shutil.which("bwrap")


def _venv_dir() -> Path | None:
    venv = ROOT / ".venv"
    return venv if (venv / "bin").exists() else None


def _interpreter_store() -> Path | None:
    """Bind the uv-managed Python *store* if the running interpreter lives there.

    uv venvs symlink ``.venv/bin/python`` out to ``.../uv/python/cpython-X/bin``,
    and that target is itself a version-alias symlink. Binding the whole
    ``.../uv/python`` directory makes every such symlink resolve inside the
    sandbox. Returns ``None`` for a self-contained / system interpreter.
    """
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.name == "python" and parent.parent.name == "uv":
            return parent
    return None


def toolchain_ro_binds() -> list[Path]:
    """Host paths (outside the standard OS dirs) the agent needs, read-only."""
    binds = [ABHAY_PI_DIR, _PI_WRAPPER, _venv_dir(), _interpreter_store()]
    seen: list[Path] = []
    for b in binds:
        if b and b.exists() and b not in seen:
            seen.append(b)
    return seen


def default_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for the sandboxed agent.

    Curated PATH (venv first, so ``python``/``pip`` resolve to the project env),
    ``IS_SANDBOX=1`` so pi runs autonomously, ``HOME`` inside the workspace, and
    cache redirects to the ephemeral tmpfs ``/tmp`` so large/transient caches
    (HF models, pip, npm) never get persisted into the browsable run dir.
    ``extra`` (e.g. parsed .env secrets) is merged last and wins.
    """
    path_parts = ["/usr/local/sbin", "/usr/local/bin"]
    venv = _venv_dir()
    if venv:
        path_parts.append(str(venv / "bin"))
    path_parts += ["/usr/sbin", "/usr/bin", "/sbin", "/bin"]
    env = {
        "HOME": HOME,
        "PATH": ":".join(path_parts),
        "IS_SANDBOX": "1",
        "TMPDIR": "/tmp",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "ABHAY_PI_DIR": str(ABHAY_PI_DIR),
        # Keep big/ephemeral caches out of the persisted run dir (tmpfs /tmp).
        "XDG_CACHE_HOME": "/tmp/cache",
        "HF_HOME": "/tmp/cache/huggingface",
        "PIP_CACHE_DIR": "/tmp/cache/pip",
        "NPM_CONFIG_CACHE": "/tmp/cache/npm",
    }
    if extra:
        env.update(extra)
    return env


def build_argv(
    workspace: Path,
    inner: list[str],
    *,
    extra_ro_binds: tuple[str, ...] = (),
    workspace_ro: bool = False,
    extra_binds: tuple[tuple[str, str], ...] = (),
    extra_ro_dest_binds: tuple[tuple[str, str], ...] = (),
) -> list[str]:
    """Build the ``bwrap … -- <inner>`` argv for a sandboxed command.

    ``workspace`` is bind-mounted as ``/workspace`` (read-write, or read-only when
    ``workspace_ro`` is set — used by the read-only Run Lens oversight agent) and
    is the cwd. ``extra_binds`` are ``(host, dest)`` read-write mounts (e.g. a
    writable scratch dir when the workspace is mounted read-only).

    The sandbox environment is *not* put on the command line (that would leak
    secrets into ``ps``/``/proc``): bwrap forwards its own process environment
    into the sandbox, so the caller passes :func:`default_env` via the child
    process's ``env=`` instead.
    """
    argv = [available() or "bwrap"]
    for path in (*_OS_RO_PATHS, *extra_ro_binds):
        if Path(path).exists():
            argv += ["--ro-bind", path, path]
    for path in toolchain_ro_binds():
        argv += ["--ro-bind", str(path), str(path)]
    # DNS: /etc/resolv.conf is typically a symlink into /run (systemd-resolved),
    # which we don't bind, so it dangles inside the sandbox and name resolution
    # fails. Bind the resolved real file at its own canonical path so the symlink
    # (preserved by the /etc bind) resolves. Network itself is shared with the
    # host (no --unshare-net), so the resolver (e.g. 127.0.0.53) is reachable.
    resolv = Path("/etc/resolv.conf")
    if resolv.exists():
        real = resolv.resolve()
        argv += ["--ro-bind", str(real), str(real)]
    argv += [
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--proc",
        "/proc",
        # Fresh minimal /dev: standard devices + /dev/shm, but NO /dev/nvidia* —
        # this is what hard-disables GPU access on a GPU host.
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        ("--ro-bind" if workspace_ro else "--bind"),
        str(workspace),
        WORKSPACE,
    ]
    for host, dest in extra_binds:
        argv += ["--bind", str(host), dest]
    # Read-only ``(host, dest)`` mounts (e.g. the source run at /run for the
    # write-up meta-agent, whose CWD/workspace is instead a writable output dir).
    for host, dest in extra_ro_dest_binds:
        argv += ["--ro-bind", str(host), dest]
    argv += ["--chdir", WORKSPACE, "--die-with-parent", "--"]
    argv += inner
    return argv


def session_host_path(container_path: str, workspace: Path) -> Path | None:
    """Map a ``/workspace/...`` path recorded inside the sandbox to its host path.

    Sub-agent session files are recorded (in RUN_LOOP_STATE.json) with their
    in-sandbox absolute paths; on the host they live under ``workspace`` because
    the run dir *is* ``/workspace`` (and HOME is ``/workspace/.home``).
    """
    if container_path == WORKSPACE:
        return workspace
    prefix = WORKSPACE + "/"
    if container_path.startswith(prefix):
        return workspace / container_path[len(prefix) :]
    return None


__all__ = [
    "WORKSPACE",
    "HOME",
    "available",
    "default_env",
    "build_argv",
    "toolchain_ro_binds",
    "session_host_path",
]
