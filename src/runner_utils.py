"""Small shared helpers for the experiment runners (env loading, output cleaning)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def parse_env_text(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines from .env-style text into a dict.

    Skips blanks/comments, tolerates a leading ``export``, and strips one layer
    of surrounding quotes. Used both to load .env onto the host and to inject
    secrets into the agent sandbox as environment variables (the bwrap runner no
    longer writes a .env file into the workspace).
    """
    out: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def load_env_file(path: Path, *, override: bool = True) -> None:
    """Load ``KEY=VALUE`` pairs from a .env file into ``os.environ``.

    Used by experiments that run the agent on the host (e.g. 01_eval_planning);
    the sandbox runner injects these into the sandbox as environment variables
    instead.

    With ``override=True`` (the default) values from the .env file take
    precedence over any pre-existing environment variables. This prevents a
    stale/invalid key left in the ambient shell environment (e.g. an old
    ``OPENAI_API_KEY``) from silently shadowing the correct value in .env, which
    otherwise surfaces as confusing 401 errors at run time.

    Pass ``override=False`` to keep any existing environment values instead.
    """
    if not path.exists():
        return
    for key, value in parse_env_text(path.read_text()).items():
        if override or not os.environ.get(key):
            os.environ[key] = value


def clean_output_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
        print(f"Cleaned previous output: {path}")


__all__ = ["load_env_file", "parse_env_text", "clean_output_dir"]
