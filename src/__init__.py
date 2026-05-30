"""Slopbench shared package.

Single source of truth for things shared across experiments.
"""

from __future__ import annotations

import os

# Default model ids used by every experiment runner unless explicitly
# overridden via --model / --claude-model / --gpt-model or the matching
# environment variables.
DEFAULT_MODEL: str = os.environ.get("DEFAULT_MODEL", "anthropic/claude-opus-4-8")
DEFAULT_GPT_MODEL: str = os.environ.get("DEFAULT_GPT_MODEL", "openai/gpt-5.5-pro")

__all__ = ["DEFAULT_MODEL", "DEFAULT_GPT_MODEL"]
