"""Shared visual theme for the project's web viewers (single source of truth).

The agent viewer (``src/agent_viewer.py``) and the blogpost studio
(``experiments/06_blogpost_studio/app.py``) embed :data:`PALETTE_CSS` so they
share one dark color scheme. Each page keeps its own component/layout CSS, but
every color is driven by these variables, so changing a hue here changes it
everywhere. Pages insert the palette by replacing the ``/*__PALETTE__*/`` token
in their ``<style>`` block.

The variable set is a superset of what any page uses, including a few aliases
(``--text`` == ``--fg``, ``--line`` == ``--border``, ``--bad`` == ``--err``) so
existing rules resolve without renaming.
"""

from __future__ import annotations

PALETTE_CSS = """:root{
  color-scheme: dark;
  /* surfaces (back -> front) */
  --bg:#0d1017; --panel:#13161f; --panel2:#1a1e2a; --panel3:#222735;
  --border:#2b3142; --line:#2b3142;
  /* text */
  --fg:#e8ebf2; --text:#e8ebf2; --muted:#8a93a8; --faint:#5c6478;
  /* accents */
  --accent:#7aa2f7; --accent2:#7dcfff;
  --user:#9ece6a; --assist:#7aa2f7; --think:#bb9af7; --tool:#e0af68;
  /* status */
  --ok:#9ece6a; --warn:#e0af68; --err:#f7768e; --bad:#f7768e;
  --code-bg:#0a0c12;
  /* typography */
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,sans-serif;
}"""

__all__ = ["PALETTE_CSS"]
