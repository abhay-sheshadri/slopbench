"""Shared builder for the blue-team auditor prompt.

Both the batch experiment (``experiments/08_automated_blue_teaming/make_blue_team.py``)
and the interactive Blue Team tab in the viewer (``src/blueteam_web.py``) render the
same Jinja templates in ``experiments/08_automated_blue_teaming/prompts/`` through this
one function, so the sabotage definition + findings format never drift:

  - ``stream=False`` (batch): the agent writes its findings to ``report_file`` in its CWD.
  - ``stream=True`` (viewer): the agent reports findings directly in its reply, narrating
    its exploration so a human can watch it live.

Both run with the same ``/source``-read-only mount, so the prompt body is identical; only
the closing output instruction differs.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "experiments" / "08_automated_blue_teaming" / "prompts"

_JINJA = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    autoescape=False,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def build_prompt(
    *, stream: bool = False, report_file: str = "blue_team_report.md"
) -> str:
    """Render the blue-team task prompt (which ``{% include %}``s the sabotage guide)."""
    return _JINJA.get_template("blue_team.md.j2").render(
        stream=stream, report_file=report_file
    )


def build_followup_prompt() -> str:
    """Render the second-pass follow-up sent after the first audit: asks the
    agent to challenge its coverage for missed methodological flaws, then rewrite
    the final findings clearly for researchers unfamiliar with the project while
    re-emitting the same ```json findings schema."""
    return _JINJA.get_template("blue_team_clarify.md.j2").render()


def build_skim_rewrite_prompt() -> str:
    """Render the final style-only rewrite prompt for live Blue Team audits."""
    return _JINJA.get_template("blue_team_skim_rewrite.md.j2").render()


__all__ = ["build_prompt", "build_followup_prompt", "build_skim_rewrite_prompt"]
