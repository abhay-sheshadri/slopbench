"""Slopbench shared package.

Single source of truth for things shared across experiments.
"""

from __future__ import annotations

import os

# Default model id used by every experiment runner unless explicitly overridden
# via --model or a task-specific environment variable.
DEFAULT_MODEL: str = os.environ.get("DEFAULT_MODEL", "anthropic/claude-opus-4-8")

__all__ = ["DEFAULT_MODEL"]
