#!/usr/bin/env python3
"""Live agent viewer.

Streams pi agent state straight off disk from the run directories created by
``src.agent_runner`` (each at outputs/<...>/<proposal>/<mode>/agent_N/), then
renders a normalized transcript: user/assistant messages, thinking, tool calls +
results, subagents, multi-phase run-loop phases, and goal state. There is no
Docker: a run is "live" while its ``.pi_transcripts/RUNNING`` marker exists and
the agent is appending to ``session.jsonl``; otherwise it's a finished record.
Both read through the same code path.

No third-party dependencies (stdlib ``http.server`` + an embedded single-page
app). Filter the sidebar by mode (goal / multi_phase) and proposal.

Usage:
    python -m src.agent_viewer            # serve on http://127.0.0.1:8765
    python -m src.agent_viewer --port 9000 --open
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from src import oversight, sandbox
from src.runner_utils import parse_env_text
from src.theme import PALETTE_CSS

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = ROOT / "outputs"

# Runs live directly on disk under outputs/<...>/<proposal>/<mode>/agent_N/.
# The runner writes both a compatibility RUNNING marker and a heartbeat. The
# heartbeat plus recent filesystem activity is the source of truth for whether a
# run is actively progressing; a marker by itself can be stale after hard kills.
MODES = ("goal", "multi_phase")
RUNNING_MARKER = "RUNNING"
HEARTBEAT_FILE = "heartbeat.json"
HEARTBEAT_STALE_SECONDS = 90
QUIET_SECONDS = 20 * 60


# --------------------------------------------------------------------------- #
# Session parsing -> normalized turns/blocks
# --------------------------------------------------------------------------- #
def _iter_jsonl(text: str):
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def parse_session(text: str) -> dict:
    """Parse a pi session.jsonl into normalized turns + sidecar state.

    Returns {"turns": [...], "goal": {...}|None, "header": {...}}.
    """
    turns: list[dict] = []
    tool_results: dict[str, dict] = {}
    goal: dict | None = None
    header: dict = {}
    cost = 0.0

    entries = list(_iter_jsonl(text))

    # First pass: collect tool results (so we can attach them to tool calls)
    # and the latest goal state.
    for entry in entries:
        etype = entry.get("type")
        if etype == "session":
            header = {"cwd": entry.get("cwd"), "id": entry.get("id")}
        elif etype == "custom" and entry.get("customType") == "goal":
            data = entry.get("data") or {}
            if data.get("objective"):
                goal = {
                    "objective": data.get("objective"),
                    "status": data.get("status"),
                    "tokensUsed": data.get("tokensUsed"),
                    "tokenBudget": data.get("tokenBudget"),
                }
        elif etype == "message":
            msg = entry.get("message") or {}
            if msg.get("role") == "toolResult" and msg.get("toolCallId"):
                tool_results[msg["toolCallId"]] = {
                    "name": msg.get("toolName"),
                    "isError": bool(msg.get("isError")),
                    "text": _content_text(msg.get("content")),
                }
            c = ((msg.get("usage") or {}).get("cost") or {}).get("total")
            if isinstance(c, (int, float)):
                cost += c

    # Second pass: build user/assistant turns with blocks.
    for entry in entries:
        if entry.get("type") != "message":
            continue
        msg = entry.get("message") or {}
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        blocks: list[dict] = []
        for c in msg.get("content") or []:
            if not isinstance(c, dict):
                continue
            ctype = c.get("type")
            if ctype == "text":
                txt = c.get("text", "")
                if txt.strip():
                    blocks.append({"kind": "text", "text": txt})
            elif ctype == "thinking":
                txt = c.get("thinking", "")
                if txt.strip():
                    blocks.append({"kind": "thinking", "text": txt})
            elif ctype == "toolCall":
                name = c.get("name", "?")
                args = c.get("arguments")
                res = tool_results.get(c.get("id"))
                if name == "subagent":
                    a = args if isinstance(args, dict) else {}
                    blocks.append(
                        {
                            "kind": "subagent",
                            "agent": a.get("agent", "?"),
                            "task": a.get("task", ""),
                            "result": res,
                        }
                    )
                else:
                    blocks.append(
                        {"kind": "tool", "name": name, "args": args, "result": res}
                    )
        if blocks:
            turns.append(
                {
                    "role": role,
                    "ts": msg.get("timestamp") or entry.get("timestamp"),
                    "blocks": blocks,
                    # entry id lets us de-duplicate run-loop forks: a phase
                    # planner is a fork of the main planner and copies its
                    # history verbatim (same ids), so the fork's own turns are
                    # exactly those whose id is not already in the main planner.
                    "id": entry.get("id"),
                }
            )
    return {"turns": turns, "goal": goal, "header": header, "cost": cost}


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif isinstance(c, str):
                parts.append(c)
        return "\n".join(parts)
    return ""


# --------------------------------------------------------------------------- #
# Run discovery: a filesystem browser over outputs/ (folder tree -> runs)
# --------------------------------------------------------------------------- #
def _safe_disk_path(rel: str) -> Path | None:
    """Resolve a path relative to outputs/ safely (no escaping the root)."""
    try:
        p = (OUTPUTS_DIR / rel).resolve()
    except (OSError, ValueError):
        return None
    root = OUTPUTS_DIR.resolve()
    if root not in p.parents and p != root:
        return None
    return p


def _mode_from_name(name: str) -> str | None:
    """Mode from a run-dir name like '<proposal>_<mode>' (longest match wins)."""
    for m in sorted(MODES, key=len, reverse=True):
        if name == m or name.endswith("_" + m):
            return m
    return None


def _is_run_dir(d: Path) -> bool:
    # A run dir is recognised by ANY transcript marker. multi_phase runs often
    # have no top-level session.jsonl (the /run-loop orchestrator barely writes
    # to its own session; the work lives in run_loop_sessions/), and a finished
    # or timed-out run has no RUNNING marker — so check planner/manifest too,
    # otherwise such runs vanish from the browser once they stop.
    t = d / ".pi_transcripts"
    if not t.is_dir():
        return False
    return (
        (t / "session.jsonl").exists()
        or (t / "planner.session.jsonl").exists()
        or (t / "manifest.json").exists()
        or (t / RUNNING_MARKER).exists()
        or (t / "run_loop_sessions").is_dir()
    )


# Dirs we never descend into while *discovering* runs: a run's own (often multi-
# GB) working tree, dependency/cache dirs, and the agent HOME. Run dirs are found
# by their .pi_transcripts child and never nest, so once one is found we prune
# everything under it instead of crawling potentially tens of GB of run output.
_WALK_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".home",
    ".pi_transcripts",
    ".lens",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    "site-packages",
    "wandb",
}
_RUNDIRS_CACHE: "tuple[float, set] | None" = None
_RUNDIRS_TTL = 2.0
_RUNDIRS_LOCK = threading.Lock()


def _discover_run_dirs(d: Path) -> set:
    """Run dirs at/under ``d`` via a pruned top-down walk.

    Recognised by their ``.pi_transcripts`` child; runs never nest, so once one
    is found we stop descending into its (potentially multi-GB) working tree.
    Hidden/dependency/cache dirs are pruned, keeping the walk shallow instead of
    crawling the whole outputs/ tree (the old ``glob('**/.pi_transcripts')``).
    """
    found: set = set()
    for root, dirs, _files in os.walk(d):
        if _is_run_dir(Path(root)):
            found.add(Path(root))
            dirs[:] = []  # don't crawl the run's working files
            continue
        dirs[:] = [
            x for x in dirs if x not in _WALK_SKIP_DIRS and not x.startswith(".")
        ]
    return found


def _run_dirs_under(d: Path) -> set:
    """All run directories at or below ``d`` (a run dir has a .pi_transcripts).

    The whole-outputs scan is cached for a short TTL so the 3s dashboard/dir
    polls don't re-walk the tree on every request; subtrees are walked directly.
    """
    if d != OUTPUTS_DIR:
        return _discover_run_dirs(d)
    global _RUNDIRS_CACHE
    now = time.monotonic()
    with _RUNDIRS_LOCK:
        if _RUNDIRS_CACHE and now - _RUNDIRS_CACHE[0] < _RUNDIRS_TTL:
            return set(_RUNDIRS_CACHE[1])
    found = _discover_run_dirs(d)
    with _RUNDIRS_LOCK:
        _RUNDIRS_CACHE = (now, set(found))
    return found


def _mtime(d: Path) -> float:
    for c in (
        d / ".pi_transcripts" / "session.jsonl",
        d / ".pi_transcripts" / "planner.session.jsonl",
        d / "planner" / "RUN_LOOP_STATE.json",
        d,
    ):
        try:
            return c.stat().st_mtime
        except OSError:
            pass
    return 0.0


_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "file_cache_dir",
    ".cache",
    "site-packages",
}
_SKIP_FILES = {".env", HEARTBEAT_FILE, RUNNING_MARKER, "manifest.json"}
# Recent-activity scans are by far the hottest path (the dashboard polls every
# few seconds, and a run dir can hold 100k+ files). Cache per run dir; the
# health thresholds are 90s/20min, so a 15s-stale answer changes nothing.
_MTIME_CACHE: dict[str, tuple[float, float]] = {}  # dir -> (computed_at, newest)
_MTIME_TTL = 15.0


def _newest_mtime_under(d: Path, *, limit: int = 20000) -> float:
    """Best-effort newest meaningful run activity timestamp (briefly cached).

    Avoid dependency/cache trees; include transcripts, logs, results, writeups,
    and source files the agent creates. This is for status display only, so it
    is intentionally bounded: one shared stat budget across all walks, and the
    scan stops as soon as it finds a file fresh enough to prove the run is
    active right now.
    """
    now = time.time()
    cached = _MTIME_CACHE.get(str(d))
    if cached and now - cached[0] < _MTIME_TTL:
        return cached[1]

    newest = _mtime(d)
    budget = limit
    fresh_cutoff = now - 5.0  # anything this new settles "active" — stop looking

    def walk(root_dir: Path, skip_dirs: set[str]) -> bool:
        """Fold mtimes under root_dir into ``newest``; True = stop scanning."""
        nonlocal newest, budget
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [
                x for x in dirs if x not in skip_dirs and not x.endswith(".dist-info")
            ]
            for fn in files:
                if fn in _SKIP_FILES:
                    continue
                try:
                    mt = os.stat(os.path.join(root, fn)).st_mtime
                except OSError:
                    continue
                if mt > newest:
                    newest = mt
                budget -= 1
                if newest >= fresh_cutoff or budget <= 0:
                    return True
        return False

    priority_roots = [
        d / ".pi_transcripts",
        d / "planner",
        d / "results",
        d / "logs",
        d / "plots",
    ]
    try:
        phase_dirs = [
            p for p in d.iterdir() if p.is_dir() and p.name.startswith("phase_segment_")
        ]
    except OSError:
        phase_dirs = []
    for phase_dir in phase_dirs:
        try:  # the shared LLM cache's mtime is a strong liveness signal by itself
            newest = max(newest, (phase_dir / "file_cache_dir").stat().st_mtime)
        except OSError:
            pass
        priority_roots.extend(
            phase_dir / sub for sub in ("results", "logs", "plots", "progress")
        )
    # Single-dir runs (run-loop --single-dir) have no phase_segment_* clones: all
    # work happens in work/ and the shared cache sits at the run root. Give them
    # the same priority signals so a live run isn't misread as stale when the
    # bounded generic walk runs out of stat budget. (The root cache stat also
    # covers clone-mode runs, whose phase-dir cache is a symlink to it anyway.)
    try:
        newest = max(newest, (d / "file_cache_dir").stat().st_mtime)
    except OSError:
        pass
    priority_roots.extend(
        d / "work" / sub for sub in ("results", "logs", "plots", "progress")
    )

    # Check high-signal output dirs first. Some phase workspaces contain many
    # source/cache files, and the bounded generic walk below can hit its limit
    # before reaching the result file that proves an experiment is still moving.
    done = newest >= fresh_cutoff
    for root_dir in priority_roots:
        if done:
            break
        if root_dir.is_dir():
            done = walk(root_dir, _SKIP_DIRS)
    if not done:
        walk(d, _SKIP_DIRS | {"data"})

    _MTIME_CACHE[str(d)] = (time.time(), newest)
    return newest


def _parse_iso_ts(value) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _run_health(d: Path) -> dict:
    tdir = d / ".pi_transcripts"
    marker = tdir / RUNNING_MARKER
    hb_path = tdir / HEARTBEAT_FILE
    marker_exists = marker.exists()
    now = time.time()
    last_activity = _newest_mtime_under(d)
    hb = None
    hb_ts = None
    if hb_path.exists():
        try:
            hb = json.loads(hb_path.read_text())
            hb_ts = _parse_iso_ts(hb.get("heartbeat_at")) or hb_path.stat().st_mtime
        except (json.JSONDecodeError, OSError, ValueError):
            hb = None
            try:
                hb_ts = hb_path.stat().st_mtime
            except OSError:
                hb_ts = None

    heartbeat_age = (now - hb_ts) if hb_ts else None
    activity_age = (now - last_activity) if last_activity else None
    heartbeat_fresh = (
        heartbeat_age is not None and heartbeat_age <= HEARTBEAT_STALE_SECONDS
    )
    activity_recent = (
        activity_age is not None and activity_age <= HEARTBEAT_STALE_SECONDS
    )
    activity_quiet = activity_age is not None and activity_age <= QUIET_SECONDS

    if marker_exists and heartbeat_fresh:
        if activity_age is not None and activity_age > QUIET_SECONDS:
            health = "quiet"
            label = None
        else:
            health = "active"
            label = "ACTIVE"
    elif marker_exists and hb_ts is None and activity_recent:
        # Legacy runs started before heartbeat support can still prove they are
        # moving by touching transcripts/logs/results very recently.
        health = "active"
        label = "ACTIVE"
    elif marker_exists and hb_ts is None and activity_quiet:
        health = "quiet"
        label = None
    elif marker_exists:
        health = "stale"
        label = None
    else:
        health = "done"
        label = None

    return {
        "marker": marker_exists,
        "live": health == "active",
        "health": health,
        "healthLabel": label,
        "heartbeatAt": int(hb_ts * 1000) if hb_ts else None,
        "heartbeatAge": heartbeat_age,
        "lastActivity": int(last_activity * 1000) if last_activity else None,
        "activityAge": activity_age,
        "heartbeat": hb or {},
    }


def _run_loop_status(d: Path) -> str | None:
    state_path = d / "planner" / "RUN_LOOP_STATE.json"
    if not state_path.exists():
        return None
    try:
        value = json.loads(state_path.read_text()).get("status")
    except (json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, str) else None


def _canonical_phase(
    *, health: dict, run_loop_status: str | None, manifest_status: str | None
) -> str:
    raw = " ".join(
        s.lower()
        for s in (run_loop_status, manifest_status)
        if isinstance(s, str) and s.strip()
    )
    if any(token in raw for token in ("error", "fail", "failed", "stop", "budget")):
        return "Failed"
    if any(token in raw for token in ("complete", "completed", "done", "success")):
        return "Completed"
    # "quiet" = RUNNING marker + fresh heartbeat but no transcript writes for a
    # while — typically a worker inside one long tool call (big compute job).
    # That's alive, not failed; only a dead heartbeat ("stale") means failed.
    if health.get("health") in {"active", "quiet"}:
        return "Active"
    if raw or health.get("health") == "stale":
        return "Failed"
    return "Completed"


def _run_item(d: Path, rel: str) -> dict:
    tdir = d / ".pi_transcripts"
    health = _run_health(d)
    manifest_status = None
    manifest = tdir / "manifest.json"
    if manifest.exists():
        try:
            manifest_status = json.loads(manifest.read_text()).get("status")
        except (json.JSONDecodeError, OSError):
            manifest_status = None
    run_loop_status = _run_loop_status(d)
    phase = _canonical_phase(
        health=health,
        run_loop_status=run_loop_status,
        manifest_status=manifest_status,
    )
    return {
        "name": d.name,
        "path": rel,
        "type": "run",
        "mode": _mode_from_name(d.name),
        "phase": phase,
        "live": health["live"],
        "health": health["health"],
        "healthLabel": health["healthLabel"],
        "marker": health["marker"],
        "heartbeatAt": health["heartbeatAt"],
        "lastActivity": health["lastActivity"],
        "status": phase.lower(),
        "rawStatus": manifest_status,
        "rawRunLoopStatus": run_loop_status,
        "mtime": (health["lastActivity"] or 0) / 1000,
    }


def list_dir(rel: str) -> list[dict]:
    """Contents of one directory under outputs/ (rel="" is the root).

    Returns run leaves and sub-directories that contain at least one run,
    newest first — the data behind the click-through folder browser.
    """
    base = _safe_disk_path(rel) if rel else OUTPUTS_DIR
    if base is None or not base.is_dir():
        return []
    items: list[dict] = []
    for child in base.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        crel = str(child.relative_to(OUTPUTS_DIR))
        if _is_run_dir(child):
            items.append(_run_item(child, crel))
            continue
        runs = _run_dirs_under(child)
        if runs:
            items.append(
                {
                    "name": child.name,
                    "path": crel,
                    "type": "dir",
                    "runs": len(runs),
                    "live": any(_run_health(r)["live"] for r in runs),
                    "mtime": max(
                        ((_run_health(r)["lastActivity"] or 0) / 1000 for r in runs),
                        default=_mtime(child),
                    ),
                }
            )
    items.sort(key=lambda x: x.get("mtime", 0.0), reverse=True)
    return items


def _run_loop_summary(state_text: str | None) -> dict | None:
    if not state_text:
        return None
    try:
        d = json.loads(state_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):  # truncated/garbled into a bare scalar or list
        return None
    return {
        "status": d.get("status"),
        "segment": d.get("currentSegment"),
        "phase": d.get("currentPhase"),
        "stage": d.get("stage"),
        "cost": d.get("costUsd"),
        "lastError": d.get("lastError"),
        "completed": [
            {
                "segment": c.get("segment"),
                "phase": c.get("phase"),
                "decision": c.get("decision"),
            }
            for c in (d.get("completed") or [])
            if isinstance(c, dict)
        ],
        "sessions": d.get("sessions") or {},
    }


def get_transcript(agent_id: str) -> dict:
    """Read a run's transcript off disk. Works identically for live and finished
    runs — a live run is simply one still being written to."""
    return _transcript_disk(agent_id)


def transcript_signature(data: dict) -> str:
    """Cheap fingerprint that changes whenever the transcript gains content, so
    the SSE stream only pushes when something actually moved."""
    if not isinstance(data, dict) or data.get("error"):
        return f"err:{(data or {}).get('error')}"
    parts = [str(data.get("mode"))]
    goal = data.get("goal")
    if goal:
        parts.append(f"g:{goal.get('status')}:{goal.get('tokensUsed')}")
    rl = data.get("run_loop")
    if rl:
        parts.append(
            "rl:"
            + ":".join(
                str(rl.get(k)) for k in ("status", "segment", "phase", "stage", "cost")
            )
            + f":{len(rl.get('completed') or [])}"
        )
    for s in data.get("sessions", []):
        turns = s.get("turns") or []
        last = turns[-1] if turns else None
        blocks = (last or {}).get("blocks") or []
        lb = blocks[-1] if blocks else {}
        res = lb.get("result") or {}
        parts.append(
            f"{s.get('name')}:{len(turns)}:{len(blocks)}:{lb.get('kind')}:"
            f"{len((lb.get('text') or lb.get('task') or ''))}:{len((res.get('text') or ''))}"
        )
    return "|".join(parts)


_STAGE_RANK = {"worker": 0, "reviewer": 1, "phase_planner": 2}
_STAGE_LABEL = {
    "worker": "Worker",
    "reviewer": "Reviewer",
    "phase_planner": "Phase planner",
}


def _session_meta(name: str, mode: str | None = None) -> dict:
    """Display ``label``, phase ``group``, and fallback sort ``order`` for a tab.

    Sessions are ultimately ordered by when they actually ran (first-message
    timestamp); ``order`` is only a tiebreaker for sessions without timestamps.
    Run-loop sub-sessions are named ``<stage>_<segment>_<phase>`` (worker /
    reviewer / phase_planner) and are grouped per phase. In ``goal`` mode the
    single execution session is the agent itself, so it is labelled "Worker".
    Handles both live ("worker 0:0") and disk ("worker_0_0") naming.
    """
    n = name.lower().replace("-", "_").replace(" ", "_").replace(":", "_")
    if n == "planner":  # our /init-planner session (runs first)
        return {"label": "Planner", "group": "Planning", "order": (-2, 0, 0, 0)}
    if n == "main":  # the execution session (/goal or /run-loop)
        label = "Worker" if mode == "goal" else "Run loop"
        return {"label": label, "group": "Execution", "order": (-1, 0, 0, 0)}
    if n.startswith("main_planner"):
        return {
            "label": "Run-loop planner",
            "group": "Execution",
            "order": (0, -1, 0, 0),
        }
    m = re.match(r"(worker|reviewer|phase_planner)_(\d+)_(\d+)", n)
    if m:
        stage, seg, phase = m.group(1), int(m.group(2)), int(m.group(3))
        return {
            "label": _STAGE_LABEL.get(stage, stage),
            "group": f"Segment {seg} · Phase {phase}",
            "order": (1, seg, phase, _STAGE_RANK.get(stage, 9)),
        }
    return {"label": name, "group": "Other", "order": (2, 0, 0, 0)}


def _session_start_ts(turns: list) -> float | None:
    """Timestamp (ms) of the first message that has one — when the session ran."""
    for t in turns:
        v = t.get("ts")
        if isinstance(v, (int, float)):
            return float(v)
    return None


# --------------------------------------------------------------------------- #
# multi_phase (run-loop) assembly
#
# A run-loop phase really happens as: the WORKER does the work, then a PHASE
# PLANNER (a fork of the main planner) reviews it and plans the next phase, then
# the MAIN PLANNER reviews that proposal (the "main review"). We rebuild that
# worker -> phase planner -> main review story per phase, and crucially we strip
# the inherited main-planner history out of each phase-planner fork so the same
# old reviews don't repeat in every tab.
# --------------------------------------------------------------------------- #
_RL_STAGE_RE = re.compile(r"(worker|reviewer|phase_planner)_(\d+)_(\d+)")
_MP_BOUNDARY_RE = re.compile(
    r"finished reviewing the work done in segment\s*(\d+)\s*,?\s*phase\s*(\d+)", re.I
)
# Verbatim from run-loop.ts buildContinueInjectedInstructions(): a /run-loop
# continue relaunch prepends this to the main planner's review prompt.
_MP_CONTINUATION_MARKER = "IMPORTANT: Project Continuation"
_RL_STAGE_ORDER = {"worker": 0, "phase_planner": 1, "main_review": 2}
_RL_STAGE_LABEL = {
    "worker": "Worker",
    "phase_planner": "Phase planner",
    "main_review": "Main review",
}


def _norm_session_name(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_").replace(":", "_")


def _turn_text(turn: dict) -> str:
    return " ".join(
        b.get("text", "") for b in (turn.get("blocks") or []) if b.get("kind") == "text"
    )


def _split_main_planner(turns: list) -> tuple:
    """Slice the one long main-planner thread into per-phase review chunks.

    Each review starts at the user message "...finished reviewing the work done
    in segment X, phase Y..."; the revision rounds that follow belong to the
    same chunk. A ``/run-loop continue`` relaunch re-opens the last phase's
    review with an injected continuation prompt (see _MP_CONTINUATION_MARKER);
    each such re-opening gets its own generation so the UI can show
    continuations as their own groups instead of silently appending to the
    original phase's tabs.

    Returns ``(chunks, cont_starts)`` where ``chunks`` is
    ``{(seg, phase, gen): [turn, ...]}`` (gen=0 is the original review) and
    ``cont_starts`` is ``{(seg, phase): {gen: first_turn_ts_ms}}`` for gen>=1,
    used to split the reused phase-planner fork at the same boundaries.
    """
    chunks: dict = {}
    gens: dict = {}
    cur = None
    for t in turns:
        if t.get("role") == "user":
            text = _turn_text(t)
            m = _MP_BOUNDARY_RE.search(text)
            if m:
                key = (int(m.group(1)), int(m.group(2)))
                if _MP_CONTINUATION_MARKER in text:
                    gens[key] = gens.get(key, 0) + 1
                cur = (key[0], key[1], gens.get(key, 0))
                chunks.setdefault(cur, [])
        if cur is not None:
            chunks[cur].append(t)
    cont_starts: dict = {}
    for (seg, phase, gen), chunk in chunks.items():
        if gen > 0:
            cont_starts.setdefault((seg, phase), {})[gen] = _session_start_ts(chunk)
    return chunks, cont_starts


def _split_fork_by_continuations(turns: list, starts: dict) -> dict:
    """Split a phase-planner fork's turns into continuation generations.

    ``/run-loop continue`` reuses the last phase's fork session, so its
    continuation turns are textually indistinguishable from ordinary revision
    rounds. The reliable boundary is time: the main planner's continuation
    injection (whose ts we have in ``starts``: {gen: ts_ms}) always precedes the
    fork's continuation turns. Turns without a ts stay in the current bucket.
    """
    if not starts:
        return {0: turns}
    boundaries = sorted((ts, gen) for gen, ts in starts.items() if ts is not None)
    out: dict = {0: []}
    cur_gen = 0
    for t in turns:
        ts = t.get("ts")
        if isinstance(ts, (int, float)):
            while boundaries and ts >= boundaries[0][0]:
                cur_gen = boundaries.pop(0)[1]
        out.setdefault(cur_gen, []).append(t)
    return out


def _assemble_run_loop(sub_parsed: list, planner: dict | None) -> list:
    """Phase-centric session list for a multi_phase run (see block comment)."""
    mp_turns: list = []
    workers: dict = {}
    phaseplanners: dict = {}
    for nm, p in sub_parsed:
        n = _norm_session_name(nm)
        if n.startswith("main_planner"):
            mp_turns = p["turns"]
            continue
        m = _RL_STAGE_RE.search(n)
        if not m:
            continue
        stage, seg, phase = m.group(1), int(m.group(2)), int(m.group(3))
        if stage == "worker":
            workers[(seg, phase)] = p["turns"]
        elif stage == "phase_planner":
            phaseplanners[(seg, phase)] = p["turns"]

    # Drop the inherited main-planner history from each phase-planner fork.
    mp_ids = {t.get("id") for t in mp_turns if t.get("id")}
    if mp_ids:
        for key, turns in list(phaseplanners.items()):
            uniq = [t for t in turns if t.get("id") not in mp_ids]
            phaseplanners[key] = uniq or turns  # keep all if dedup left nothing
    reviews, cont_starts = _split_main_planner(mp_turns)

    # A continuation reuses the last phase's fork, so carve its turns into the
    # same generations as the main-planner reviews (gen 0 = the original cycle).
    pp_split: dict = {}
    for (seg, phase), turns in phaseplanners.items():
        by_gen = _split_fork_by_continuations(turns, cont_starts.get((seg, phase), {}))
        for gen, gen_turns in by_gen.items():
            if gen_turns:
                pp_split[(seg, phase, gen)] = gen_turns

    sessions: list = []
    if planner is not None:
        sessions.append(
            {
                "name": "planner",
                "label": "Planner",
                "group": "Planning",
                "turns": planner["turns"],
                "_ord": (-2, 0, 0, 0),
                "ts": _session_start_ts(planner["turns"]),
                "seg": None,
                "phase": None,
                "stage": "planner",
            }
        )
    keys = set(pp_split) | set(reviews) | {(s, p, 0) for (s, p) in workers}
    for seg, phase, gen in sorted(keys):
        if gen == 0:
            group = f"Segment {seg} \u00b7 Phase {phase}"
            suffix = ""
        else:
            group = (
                f"Continuation {gen} \u00b7 after Segment {seg} \u00b7 Phase {phase}"
            )
            suffix = f"_cont{gen}"
        for stage, turns in (
            ("worker", workers.get((seg, phase)) if gen == 0 else None),
            ("phase_planner", pp_split.get((seg, phase, gen))),
            ("main_review", reviews.get((seg, phase, gen))),
        ):
            if not turns:
                continue
            sessions.append(
                {
                    "name": f"{stage}_{seg}_{phase}{suffix}",
                    "label": _RL_STAGE_LABEL[stage],
                    "group": group,
                    "turns": turns,
                    "_ord": (1, seg, phase, gen * 10 + _RL_STAGE_ORDER[stage]),
                    "ts": _session_start_ts(turns),
                    "seg": seg,
                    "phase": phase,
                    "cont": gen,
                    "stage": stage,
                }
            )
    sessions.sort(key=lambda s: s["_ord"])  # worker -> phase planner -> main review
    for s in sessions:
        s.pop("_ord", None)
    return sessions


def _assemble(
    mode: str | None,
    session_text: str,
    run_loop_state_text: str | None,
    sub_sessions: list,
    planner_text: str | None = None,
) -> dict:
    """Build the normalized transcript dict from the run's sessions.

    A run has two top-level transcripts — the ``planner`` session and the ``main``
    (execution) session — plus, for multi_phase, the run-loop sub-agent sessions.
    ``mode`` is read off the run-dir name (``<proposal>_<mode>``).
    """
    main = parse_session(session_text or "")
    planner = parse_session(planner_text) if planner_text else None
    sub_parsed = [(nm, parse_session(text)) for nm, text in sub_sessions]
    total_cost = (
        main.get("cost", 0.0)
        + (planner.get("cost", 0.0) if planner else 0.0)
        + sum(p.get("cost", 0.0) for _, p in sub_parsed)
    )
    if mode == "multi_phase":
        # Phase-centric: worker -> phase planner -> main review per phase, with
        # the duplicated main-planner history stripped from each fork. The
        # run-loop orchestrator ("main") adds little, so it is left out.
        sessions = _assemble_run_loop(sub_parsed, planner)
    else:
        raw = [("main", main["turns"])]
        if planner is not None:
            raw.append(("planner", planner["turns"]))
        for nm, p in sub_parsed:
            raw.append((nm, p["turns"]))
        sessions = []
        for nm, turns in raw:
            meta = _session_meta(nm, mode)
            sessions.append(
                {
                    "name": nm,
                    "label": meta["label"],
                    "group": meta["group"],
                    "turns": turns,
                    "_ord": meta["order"],
                    "ts": _session_start_ts(turns),
                }
            )
        # Order by when each session actually ran; the heuristic order only
        # breaks ties / places not-yet-started (timestamp-less) sessions last.
        sessions.sort(key=lambda s: (s["ts"] is None, s["ts"] or 0.0, s["_ord"]))
        for s in sessions:
            s.pop("_ord", None)
    return {
        "mode": mode,
        # The goal-mode objective lives in the execution session; fall back to the
        # planner session just in case.
        "goal": main["goal"] or (planner["goal"] if planner else None),
        "run_loop": _run_loop_summary(run_loop_state_text),
        "sessions": sessions,
        "cost": round(total_cost, 4),
    }


def _read_subsessions(base: Path, tdir: Path, rl_text: str | None) -> list:
    """Run-loop sub-agent sessions for a run.

    Two sources exist: the live sessions in the agent's HOME (``.home/.pi``,
    referenced by absolute path in RUN_LOOP_STATE.json) and the
    ``run_loop_sessions/`` fold that ``fold_run_loop_sessions`` writes once a run
    *exits*. While a run is live we read the HOME sessions directly, because the
    fold is either absent or — for a *resumed* run — a stale snapshot from a
    previous attempt that would hide all current progress. A finished run reads
    the fold (its HOME may be gone). Either source falls back to the other when
    empty, and unreadable files are skipped so a crash-mangled session can't break
    the whole run.
    """

    def _folded() -> list:
        sub_dir = tdir / "run_loop_sessions"
        if not sub_dir.is_dir():
            return []
        out: list = []
        for f in sorted(sub_dir.glob("*.jsonl")):
            try:
                out.append((f.stem.replace("_", " "), f.read_text(errors="replace")))
            except OSError:
                continue
        return out

    def _in_place() -> list:
        out: list = []
        rl = _run_loop_summary(rl_text)
        if rl and rl.get("sessions"):
            for sub in _run_loop_session_files(rl["sessions"]):
                host = sandbox.session_host_path(sub["path"], base)
                if not (host and host.exists()):
                    continue
                try:
                    out.append((sub["name"], host.read_text(errors="replace")))
                except OSError:
                    continue
        return out

    if (tdir / RUNNING_MARKER).exists():  # live (incl. resumed): HOME is truth
        return _in_place() or _folded()
    return _folded() or _in_place()


# Parsing session.jsonl into normalized turns is the viewer's main cost, and the
# SSE stream + overview re-request transcripts constantly. Cache the assembled
# result keyed by a cheap stat-only signature of the run's files, so a live run
# only re-parses when something on disk actually changed and finished runs are
# effectively free.
_TX_CACHE: "dict[str, tuple]" = {}
_TX_LOCK = threading.Lock()
_TX_CACHE_MAX = 96


def _disk_sig(base: Path, tdir: Path) -> tuple:
    """Stat-only fingerprint of every file that feeds a run's transcript."""
    parts: list = [(tdir / RUNNING_MARKER).exists()]
    candidates = [
        tdir / "session.jsonl",
        tdir / "planner.session.jsonl",
        tdir / "manifest.json",
        base / "planner" / "RUN_LOOP_STATE.json",
    ]
    sub_dir = tdir / "run_loop_sessions"
    home_pi = base / ".home" / ".pi"
    if parts[0]:  # live (incl. resumed): mirror _read_subsessions — HOME is the
        # source of truth, so track it (a stale fold would never invalidate the
        # cache as the run progresses); include the fold too so the eventual
        # transition to "finished" also busts the cache.
        if home_pi.is_dir():
            candidates += sorted(home_pi.glob("**/*.jsonl"))
        if sub_dir.is_dir():
            candidates += sorted(sub_dir.glob("*.jsonl"))
    elif sub_dir.is_dir():
        candidates += sorted(sub_dir.glob("*.jsonl"))
    elif home_pi.is_dir():
        candidates += sorted(home_pi.glob("**/*.jsonl"))
    for p in candidates:
        try:
            st = p.stat()
            parts.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    return tuple(parts)


def _transcript_disk(rel: str) -> dict:
    base = _safe_disk_path(rel)
    if base is None or not base.exists():
        return {"error": "not found"}
    tdir = base / ".pi_transcripts"
    sig = _disk_sig(base, tdir)
    with _TX_LOCK:
        hit = _TX_CACHE.get(rel)
        if hit is not None and hit[0] == sig:
            return hit[1]
    sess = tdir / "session.jsonl"
    session_text = sess.read_text(errors="replace") if sess.exists() else ""
    planner_sess = tdir / "planner.session.jsonl"
    planner_text = (
        planner_sess.read_text(errors="replace") if planner_sess.exists() else None
    )
    rl_path = base / "planner" / "RUN_LOOP_STATE.json"
    rl_text = rl_path.read_text(errors="replace") if rl_path.exists() else None
    subs = _read_subsessions(base, tdir, rl_text)
    mode = _mode_from_name(base.name)
    data = _assemble(mode, session_text, rl_text, subs, planner_text=planner_text)
    data.update(
        {"id": rel, "source": "live" if (tdir / RUNNING_MARKER).exists() else "disk"}
    )
    with _TX_LOCK:
        if len(_TX_CACHE) >= _TX_CACHE_MAX:
            _TX_CACHE.pop(next(iter(_TX_CACHE)), None)
        _TX_CACHE[rel] = (sig, data)
    return data


def list_runs_overview() -> list[dict]:
    """Flat status list of every run under outputs/ for the homepage dashboard.

    Built off the cached transcript parse, so repeated polls are cheap: only runs
    whose files changed since the last poll are re-read.
    """
    out: list[dict] = []
    for base in _run_dirs_under(OUTPUTS_DIR):
        rel = str(base.relative_to(OUTPUTS_DIR))
        try:
            item = _run_item(base, rel)
            data = _transcript_disk(rel)
            sessions = data.get("sessions") or []
            item["sessions"] = len(sessions)
            item["turns"] = sum(len(s.get("turns") or []) for s in sessions)
            ts_vals = [
                s.get("ts") for s in sessions if isinstance(s.get("ts"), (int, float))
            ]
            transcript_activity = max(ts_vals) if ts_vals else None
            if transcript_activity and (
                not item.get("lastActivity")
                or transcript_activity > item["lastActivity"]
            ):
                item["lastActivity"] = transcript_activity
            item["goal"] = data.get("goal")
            item["cost"] = data.get("cost")
            rl = data.get("run_loop")
            item["run_loop"] = (
                {
                    "status": rl.get("status"),
                    "segment": rl.get("segment"),
                    "phase": rl.get("phase"),
                    "stage": rl.get("stage"),
                    "completed": len(rl.get("completed") or []),
                    "lastError": rl.get("lastError"),
                }
                if rl
                else None
            )
            item["group"] = rel.split("/")[0] if "/" in rel else ""
            out.append(item)
        except Exception as exc:  # noqa: BLE001 - one mangled run must never blank
            # the whole dashboard; surface it as an error row and keep going.
            out.append(
                {
                    "name": base.name,
                    "path": rel,
                    "type": "run",
                    "phase": "Failed",
                    "status": "failed",
                    "group": rel.split("/")[0] if "/" in rel else "",
                    **_run_health(base),
                    "mtime": _mtime(base),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    rank = {"Active": 0, "Failed": 1, "Completed": 2}
    out.sort(
        key=lambda x: (
            rank.get(x.get("phase"), 3),
            -(x.get("mtime") or 0.0),
        )
    )
    return out


def audit_disk_transcripts() -> list[dict]:
    """Audit every saved on-disk transcript for the agent stages it captured:
    planner mode, goal mode, and the ryan-loop stages.
    """
    results: list[dict] = []
    if not OUTPUTS_DIR.exists():
        return results
    for sess in sorted(OUTPUTS_DIR.glob("**/.pi_transcripts/session.jsonl")):
        tdir = sess.parent
        base = tdir.parent
        raw = sess.read_text(errors="replace")
        planner_sess = tdir / "planner.session.jsonl"
        planner_raw = (
            planner_sess.read_text(errors="replace") if planner_sess.exists() else ""
        )
        sub_dir = tdir / "run_loop_sessions"
        subs = (
            sorted(p.stem for p in sub_dir.glob("*.jsonl")) if sub_dir.is_dir() else []
        )
        rl_path = base / "planner" / "RUN_LOOP_STATE.json"
        rl = _run_loop_summary(
            rl_path.read_text(errors="replace") if rl_path.exists() else None
        )
        stages = sorted({re.sub(r"_\d+_\d+$", "", s) for s in subs})
        results.append(
            {
                "path": str(base.relative_to(OUTPUTS_DIR)),
                "planner_mode": ('"customType":"planner-mode"' in planner_raw)
                or ("init-planner" in planner_raw)
                or ('"customType":"planner-mode"' in raw)
                or ("init-planner" in raw),
                "goal_mode": ('"customType":"goal"' in raw) or ("/goal " in raw),
                "run_loop": rl is not None,
                "ryan_loop_stages": stages or (["state-only"] if rl else []),
                "completed_phases": len(rl["completed"]) if rl else 0,
            }
        )
    return results


def _run_loop_session_files(sessions: dict) -> list[dict]:
    out: list[dict] = []
    if isinstance(sessions.get("mainPlanner"), str):
        out.append({"name": "main-planner", "path": sessions["mainPlanner"]})
    for kind, label in (
        ("workers", "worker"),
        ("reviewers", "reviewer"),
        ("phasePlanners", "phase-planner"),
    ):
        d = sessions.get(kind) or {}
        if isinstance(d, dict):
            for key, path in d.items():
                if isinstance(path, str):
                    out.append({"name": f"{label} {key}", "path": path})
    return out


# --------------------------------------------------------------------------- #
# Run Lens: a read-only oversight agent over a run
# --------------------------------------------------------------------------- #
# A "Run Lens" query spawns `pi` in a bwrap sandbox where the run directory is
# bind-mounted READ-ONLY at /workspace (writable scratch on tmpfs + /lensjob), so
# the agent can read all of the run's code and transcripts to answer questions
# but physically cannot modify the run it is auditing. Its answer streams back to
# the browser via the same session.jsonl parser the rest of the viewer uses.
LENS_DIR = OUTPUTS_DIR / ".lens"
# Oversight/lens questions are interactive reading tasks. Default to Opus 4.6:
# this account has no Fable access (the API 404s "Claude Fable 5 is not
# available. Please use Opus 4.8."), and the experiment runners keep their own
# DEFAULT_MODEL. Override with LENS_MODEL.
LENS_MODEL = os.environ.get("LENS_MODEL", "anthropic/claude-opus-4-6")
LENS_THINKING = os.environ.get("LENS_THINKING", "medium")
# Max number of Run-Lens summary agents the dashboard's "Generate summaries"
# fan-out runs at once (also injected as the client-side cap). Each one is a full
# model call, so this is the main throughput/cost knob; override via env.
# Default kept very conservative because each summary is a full oversight agent
# that may parse large traces. Too many at once can OOM the box and show up as
# killed-rc=-9; raise via env only when the machine has clear headroom.
LENS_SUMMARY_CONCURRENCY = max(1, int(os.environ.get("LENS_SUMMARY_CONCURRENCY", "2")))
LENS_BINARY_EXT = {
    ".pyc",
    ".so",
    ".bin",
    ".safetensors",
    ".gguf",
    ".onnx",
    ".pt",
    ".pth",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
}
LENS_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
# Dependency/cache directories pruned from the orientation file index so the
# run's OWN files (transcripts, write-ups, proposal, the agent's code) surface
# instead of being buried under thousands of .venv/site-packages entries.
LENS_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "site-packages",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    ".ipynb_checkpoints",
    "wandb",
}
_LENS_JOBS: dict[str, dict] = {}
_LENS_LOCK = threading.Lock()


def _lens_env() -> dict[str, str]:
    # workspace is mounted read-only, so HOME points at the writable /lensjob scratch.
    return oversight.oversight_env("/lensjob/home")


def _lens_file_index(base: Path, limit: int = 220) -> list[str]:
    """Concise file index (relative path | bytes) to orient the oversight agent.

    Prunes dependency/cache dirs (``.venv``, ``site-packages``, ``node_modules``,
    ``__pycache__`` …) so the run's own files actually surface instead of being
    buried under thousands of library files.
    """
    out: list[str] = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [
            d
            for d in sorted(dirs)
            if d not in LENS_SKIP_DIRS and not d.endswith((".dist-info", ".egg-info"))
        ]
        rootp = Path(root)
        for fn in sorted(files):
            p = rootp / fn
            rel = p.relative_to(base)
            parts = rel.parts
            # Keep agent-HOME noise out, but keep its sub-agent session transcripts.
            if ".home" in parts and p.suffix != ".jsonl":
                continue
            if p.suffix.lower() in LENS_BINARY_EXT:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > 3_000_000:
                continue
            out.append(f"  {rel} | {size}")
            if len(out) >= limit:
                out.append("  … (index truncated)")
                return out
    return out


def _lens_plot_index(rel: str, base: Path, limit: int = 40) -> list[str]:
    """Markdown-ready plot/image references the oversight agent can cite inline."""
    out: list[str] = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [
            d
            for d in sorted(dirs)
            if d not in LENS_SKIP_DIRS and not d.endswith((".dist-info", ".egg-info"))
        ]
        rootp = Path(root)
        for fn in sorted(files):
            p = rootp / fn
            if p.suffix.lower() not in LENS_IMAGE_EXT:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > 30_000_000:
                continue
            img_rel = str(p.relative_to(base))
            url = (
                f"/api/run-file?id={quote(rel, safe='')}"
                f"&path={quote(img_rel, safe='/')}"
            )
            out.append(f"  - {img_rel} | {size} bytes | ![{img_rel}]({url})")
            if len(out) >= limit:
                out.append("  - … (plot index truncated)")
                return out
    return out


def _lens_prompt(rel: str, base: Path, question: str) -> str:
    tdir = base / ".pi_transcripts"
    status = "running" if (tdir / RUNNING_MARKER).exists() else "completed"
    data = _transcript_disk(rel)
    sess = ", ".join(
        f"{s.get('label') or s['name']}({len(s['turns'])})"
        for s in data.get("sessions", [])
    )
    rl = data.get("run_loop")
    lines = [
        "You are a READ-ONLY oversight assistant embedded in an agent-run viewer.",
        "Your working directory (/workspace) is the run directory below, mounted",
        "READ-ONLY: you can read any file in it (cat/grep/ls/find/read) and run",
        "read-only shell commands, but you cannot modify the run. Answer the user's",
        "question with concrete evidence — cite specific files and transcript",
        "sessions. Be concise; do NOT narrate your search ('let me check'); give",
        "conclusions plus the evidence you verified.",
        "",
        f"Run: {rel}",
        f"Status: {status} | mode: {data.get('mode')} | est. spend so far: ${data.get('cost', 0) or 0:.2f}",
    ]
    if data.get("goal"):
        g = data["goal"]
        lines.append(f"Goal: status={g.get('status')} tokensUsed={g.get('tokensUsed')}")
    if rl:
        lines.append(
            f"Run-loop: status={rl.get('status')} segment={rl.get('segment')} "
            f"phase={rl.get('phase')} stage={rl.get('stage')} "
            f"completed_phases={len(rl.get('completed') or [])}"
        )
    lines += [
        f"Transcript sessions present (name(turns)): {sess or 'none yet'}",
        "",
        "Key locations (relative to /workspace; some may be absent for this run):",
        *(f"  - {label}: {rel}" for label, rel in oversight.key_locations()),
        "",
        "File index (relative path | bytes):",
        *_lens_file_index(base),
        "",
        "Plot/image index (relative path | bytes | Markdown to render inline):",
        *(_lens_plot_index(rel, base) or ["  (no png/jpg/gif/webp plots found)"]),
        "",
        "When a plot is relevant, include the provided Markdown image syntax so it",
        "renders in the Run Lens chat. Mention the source file path in the text too.",
        "",
        "User question:",
        question.strip(),
    ]
    return "\n".join(lines)


def _prune_lens_jobs(keep: int = 80) -> None:
    """Drop finished lens jobs (and scratch dirs) beyond ``keep``.

    Only prunes jobs that finished a while ago, so a job whose summary is still
    being polled/streamed by the browser is never yanked out from under it. This
    keeps the registry bounded even when a 'Generate summaries' fan-out spawns
    many jobs at once.
    """
    now = time.time()
    with _LENS_LOCK:
        finished = [
            (j, info)
            for j, info in _LENS_JOBS.items()
            if info["proc"].poll() is not None and now - info["started"] > 45
        ]
        finished.sort(key=lambda x: x[1]["started"])
        for j, info in finished[:-keep] if len(finished) > keep else []:
            _LENS_JOBS.pop(j, None)
            shutil.rmtree(info["dir"], ignore_errors=True)


def _spawn_lens(rel: str, base: Path, prompt: str, thinking: str) -> dict:
    """Launch a read-only ``pi`` over run ``base`` with ``prompt`` and register it."""
    _prune_lens_jobs()
    job = uuid.uuid4().hex[:12]
    jobdir = LENS_DIR / job
    (jobdir / "home").mkdir(parents=True, exist_ok=True)
    session = jobdir / "session.jsonl"
    inner = oversight.pi_inner_argv(
        "/lensjob/session.jsonl", LENS_MODEL, thinking, prompt
    )
    argv = sandbox.build_argv(
        base, inner, workspace_ro=True, extra_binds=((str(jobdir), "/lensjob"),)
    )
    try:
        proc = subprocess.Popen(
            argv,
            env=_lens_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return {"error": f"failed to start oversight agent: {exc}"}
    with _LENS_LOCK:
        _LENS_JOBS[job] = {
            "proc": proc,
            "session": session,
            "dir": jobdir,
            "run": rel,
            "started": time.time(),
        }
    return {"job": job}


def start_lens(rel: str, question: str) -> dict:
    """Spawn a read-only oversight pi over run ``rel``. Returns {job} or {error}."""
    if sandbox.available() is None:
        return {"error": "bubblewrap (bwrap) is not installed"}
    base = _safe_disk_path(rel)
    if base is None or not (base / ".pi_transcripts").exists():
        return {"error": "unknown run"}
    if not (question or "").strip():
        return {"error": "empty question"}
    return _spawn_lens(rel, base, _lens_prompt(rel, base, question), LENS_THINKING)


# --------------------------------------------------------------------------- #
# Blue Team: a read-only sabotage auditor over a run (streamed, like the lens)
# --------------------------------------------------------------------------- #
# Same read-only model as the audit_agent experiment (run mounted READ-ONLY at
# /source, a writable CWD at /workspace), but launched non-blocking and streamed
# through the lens job machinery so the UI can watch it explore live. Blue-teaming
# is a careful reasoning task -> default to the strongest Claude model.
BLUE_TEAM_MODEL = os.environ.get("BLUE_TEAM_MODEL", "anthropic/claude-opus-4-8")
BLUE_TEAM_THINKING = os.environ.get("BLUE_TEAM_THINKING", "high")


def _spawn_blue_team(rel: str, base: Path) -> dict:
    """Launch a read-only sabotage auditor over run ``base`` and register it as a
    lens job (so lens_transcript / cancel_lens / the stream UI all work on it)."""
    from src import audit_agent, blue_team

    _prune_lens_jobs()
    job = uuid.uuid4().hex[:12]
    jobdir = LENS_DIR / job
    jobdir.mkdir(parents=True, exist_ok=True)
    # Stage RUN_DIR_STRUCTURE.md / TRACE_INDEX.md into the CWD, exactly as the
    # batch experiment does, and run with the same /source-read-only mount.
    audit_agent.stage_reference_docs(jobdir, base)
    inner = oversight.pi_inner_argv(
        f"{sandbox.WORKSPACE}/session.jsonl",
        BLUE_TEAM_MODEL,
        BLUE_TEAM_THINKING,
        blue_team.build_prompt(stream=True),
    )
    argv = sandbox.build_argv(
        jobdir, inner, extra_ro_dest_binds=((str(base), "/source"),)
    )
    try:
        proc = subprocess.Popen(
            argv,
            env=oversight.oversight_env(sandbox.HOME),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return {"error": f"failed to start blue-team agent: {exc}"}
    with _LENS_LOCK:
        _LENS_JOBS[job] = {
            "proc": proc,
            "session": jobdir / "session.jsonl",
            "dir": jobdir,
            "run": rel,
            "started": time.time(),
            # The clarity follow-up runs as a second pass on the same session;
            # this flag tells the persist daemon to wait for it before saving.
            "followup_pending": True,
        }
    threading.Thread(target=_blue_team_followup, args=(job, base), daemon=True).start()
    return {"job": job}


def _session_has_findings(session_path: Path) -> bool:
    """Whether the agent's session contains a non-empty ```json findings block."""
    try:
        text = session_path.read_text(errors="replace")
    except OSError:
        return False
    turns = parse_session(text).get("turns", [])
    joined = "\n".join(
        b.get("text", "")
        for t in turns
        for b in (t.get("blocks") or [])
        if b.get("kind") == "text"
    )
    for block in reversed(re.findall(r"```json\s*([\s\S]*?)```", joined)):
        try:
            o = json.loads(block)
        except (ValueError, TypeError):
            continue
        if (
            isinstance(o, dict)
            and isinstance(o.get("findings"), list)
            and o["findings"]
        ):
            return True
    return False


def _blue_team_followup(job: str, base: Path) -> None:
    """After the first pass writes findings, resume the SAME session with a
    clarity prompt so the findings are understandable to outside researchers.

    The resumed ``pi --session`` run appends a new turn with a rewritten ```json
    findings block; the persist logic keeps the last valid findings block, so the
    clarified version becomes the saved report automatically.
    """
    from src import blue_team

    info = _LENS_JOBS.get(job)
    if not info:
        return
    try:
        try:
            info["proc"].wait()
        except Exception:
            pass
        jobdir = info["dir"]
        session = info["session"]
        # Only follow up on a clean completion that actually produced findings —
        # skip cancellations (killed -> negative returncode / cancelled flag) and
        # empty / errored first passes.
        if (
            not info.get("cancelled")
            and info["proc"].returncode == 0
            and _session_has_findings(session)
        ):
            inner = oversight.pi_inner_argv(
                f"{sandbox.WORKSPACE}/session.jsonl",
                BLUE_TEAM_MODEL,
                BLUE_TEAM_THINKING,
                blue_team.build_followup_prompt(),
            )
            argv = sandbox.build_argv(
                jobdir, inner, extra_ro_dest_binds=((str(base), "/source"),)
            )
            try:
                proc2 = subprocess.Popen(
                    argv,
                    env=oversight.oversight_env(sandbox.HOME),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                with _LENS_LOCK:
                    info["proc"] = proc2
            except OSError:
                pass
    finally:
        with _LENS_LOCK:
            info["followup_pending"] = False


def start_blue_team(rel: str) -> dict:
    """Spawn a read-only sabotage auditor over run ``rel``. Returns {job} or {error}."""
    if sandbox.available() is None:
        return {"error": "bubblewrap (bwrap) is not installed"}
    base = _safe_disk_path(rel)
    if base is None or not (base / ".pi_transcripts").exists():
        return {"error": "unknown run"}
    return _spawn_blue_team(rel, base)


def run_image_file(rel: str, image_path: str) -> tuple[bytes, str] | None:
    base = _safe_disk_path(rel)
    if base is None or not base.exists():
        return None
    try:
        p = (base / image_path).resolve()
    except (OSError, ValueError):
        return None
    if base not in p.parents and p != base:
        return None
    ext = p.suffix.lower()
    if ext not in LENS_IMAGE_EXT or not p.is_file():
        return None
    ctype = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }[ext]
    try:
        return p.read_bytes(), ctype
    except OSError:
        return None


def _session_api_error(text: str) -> str | None:
    """Last model/API error recorded in a pi session, if any.

    A failed model call (bad/unavailable model, auth, rate limit) is written as
    an assistant message with empty content and ``stopReason == "error"`` plus an
    ``errorMessage`` — NOT a non-zero process exit (pi still exits 0). Without
    this, such a run shows zero turns and looks like a silent "(no output)".
    """
    last = None
    for entry in _iter_jsonl(text):
        if entry.get("type") != "message":
            continue
        msg = entry.get("message") or {}
        if msg.get("role") == "assistant" and msg.get("stopReason") == "error":
            em = msg.get("errorMessage")
            if isinstance(em, str) and em.strip():
                last = em.strip()
    return last


def lens_transcript(job: str) -> dict:
    """Assistant turns produced so far by a lens job + running/error state."""
    info = _LENS_JOBS.get(job)
    if not info:
        return {"error": "unknown or expired lens job"}
    proc = info["proc"]
    running = proc.poll() is None
    text = (
        info["session"].read_text(errors="replace") if info["session"].exists() else ""
    )
    turns = [t for t in parse_session(text)["turns"] if t.get("role") == "assistant"]
    out = {"turns": turns, "running": running, "job": job}
    if not running and not turns:
        # A model/API error (e.g. unavailable model) exits 0 but leaves an
        # errorMessage in the session — surface that first; it's the real cause.
        api_err = _session_api_error(text)
        rc = proc.returncode
        if api_err:
            out["error"] = api_err
        elif rc not in (0, None):
            err = b""
            try:
                err = proc.stderr.read() if proc.stderr else b""
            except (OSError, ValueError):
                pass
            detail = err.decode("utf-8", "replace").strip()[-400:]
            if not detail and rc < 0:
                detail = (
                    f"oversight agent was killed (signal {-rc}); if this recurs "
                    f"under heavy summary fan-out, lower LENS_SUMMARY_CONCURRENCY"
                )
            out["error"] = detail or f"oversight agent exited rc={rc}"
    return out


def cancel_lens(job: str) -> dict:
    info = _LENS_JOBS.get(job)
    if info:
        info["cancelled"] = True  # stop any pending clarity follow-up pass
        if info["proc"].poll() is None:
            info["proc"].kill()
    return {"cancelled": True}


def lens_poll(job_ids: list[str]) -> dict:
    """Latest answer text + running/error state for many lens jobs in one call.

    The dashboard's summary fan-out polls this single endpoint instead of opening
    one EventSource per run, so it scales past the browser's ~6-connections-per-
    host limit to dozens/hundreds of parallel summaries.
    """
    out: dict[str, dict] = {}
    for j in job_ids[:256]:
        d = lens_transcript(j)
        text = "\n".join(
            b.get("text", "")
            for t in d.get("turns", [])
            for b in (t.get("blocks") or [])
            if b.get("kind") == "text"
        ).strip()
        out[j] = {
            "running": bool(d.get("running")),
            "error": d.get("error"),
            "text": text,
        }
    return out


def _lens_signature(data: dict) -> str:
    if data.get("error"):
        return "err:" + str(data.get("error"))
    turns = data.get("turns") or []
    last = turns[-1] if turns else {}
    blocks = last.get("blocks") or []
    lb = blocks[-1] if blocks else {}
    res = lb.get("result") or {}
    return (
        f"{'run' if data.get('running') else 'done'}:{len(turns)}:{len(blocks)}:"
        f"{lb.get('kind')}:{len(lb.get('text') or lb.get('task') or '')}:{len(res.get('text') or '')}"
    )


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Launching new runs from the UI
# --------------------------------------------------------------------------- #
RUN_OUTPUT_ROOT = OUTPUTS_DIR / "03_run_agents"
FEEDBACK_DIR = ROOT / "feedback"


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None


def _proposal_and_mode(run_name: str) -> tuple[str, str]:
    """Split a run dir name back into (proposal, mode), or raise ValueError."""
    for m in MODES:
        if run_name.endswith(f"_{m}"):
            return run_name[: -len(m) - 1], m
    raise ValueError(f"{run_name} doesn't end in a known mode ({'/'.join(MODES)})")


def _tmux_run(session: str, cmd: str) -> None:
    """Run cmd in a detached tmux session (created if needed) — survives us."""
    if (
        subprocess.run(
            ["tmux", "has-session", "-t", session], capture_output=True
        ).returncode
        != 0
    ):
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(ROOT)], check=True
        )
    subprocess.run(["tmux", "send-keys", "-t", session, cmd, "Enter"], check=True)


def _feedback_dir(run_name: str) -> Path:
    return FEEDBACK_DIR / run_name


def project_info(rel: str) -> dict:
    """Everything the run-page Project panel shows: state, why-failed, feedback."""
    base = _safe_disk_path(rel)
    if base is None or not (base / ".pi_transcripts").exists():
        raise ValueError("unknown run")
    item = _run_item(base, rel)
    info = {
        "name": base.name,
        "phase": item.get("phase"),
        "mode": item.get("mode"),
        "status": item.get("status"),
    }
    hb = _read_json(base / ".pi_transcripts" / HEARTBEAT_FILE) or {}
    ts = _parse_iso_ts(hb.get("heartbeat_at"))
    info["heartbeat"] = {
        "status": hb.get("status"),
        "age_s": int(time.time() - ts) if ts else None,
    }
    st = _read_json(base / "planner" / "RUN_LOOP_STATE.json") or {}
    info["run_loop"] = {
        "status": st.get("status"),
        "segment": st.get("currentSegment"),
        "stage": st.get("stage"),
        "error": st.get("error"),
    }
    mf = _read_json(base / ".pi_transcripts" / "manifest.json") or {}
    rcs = [
        r.get("returncode")
        for r in mf.get("runs") or []
        if r.get("returncode") is not None
    ]
    info["last_returncode"] = rcs[-1] if rcs else None
    fdir = _feedback_dir(base.name)
    info["feedback"] = sorted(
        (
            {"file": p.name, "text": p.read_text(errors="replace")}
            for p in fdir.glob("*.md")
        ),
        key=lambda f: f["file"],
    )
    return info


def save_feedback(rel: str, text: str) -> dict:
    """Append a timestamped feedback note under feedback/<run_name>/."""
    base = _safe_disk_path(rel)
    if base is None or not (base / ".pi_transcripts").exists():
        raise ValueError("unknown run")
    if not (text or "").strip():
        raise ValueError("empty feedback")
    fdir = _feedback_dir(base.name)
    fdir.mkdir(parents=True, exist_ok=True)
    p = fdir / (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + ".md")
    p.write_text(text.strip() + "\n", encoding="utf-8")
    return {"file": p.name, "path": str(p.relative_to(ROOT))}


def resume_run(rel: str) -> dict:
    """Relaunch a dead (failed/killed) run with --resume, detached in tmux."""
    base = _safe_disk_path(rel)
    if base is None or not (base / ".pi_transcripts").exists():
        raise ValueError("unknown run")
    if _run_item(base, rel).get("phase") == "Active":
        raise ValueError(
            "run looks alive (fresh heartbeat) — refusing to double-launch"
        )
    proposal, mode = _proposal_and_mode(base.name)
    session = f"agent_{base.name}"
    _tmux_run(
        session,
        f".venv/bin/python experiments/03_run_agents/run.py "
        f"--projects {proposal} --modes {mode} --resume",
    )
    return {"ok": True, "session": session}


def continue_run(rel: str, feedback_text: str) -> dict:
    """Relaunch a COMPLETED multi_phase run as a continuation: the feedback note
    becomes the new instructions (run.py --continue-file)."""
    base = _safe_disk_path(rel)
    if base is None or not (base / ".pi_transcripts").exists():
        raise ValueError("unknown run")
    proposal, mode = _proposal_and_mode(base.name)
    if mode != "multi_phase":
        raise ValueError("continuation only supports multi_phase runs")
    if _run_item(base, rel).get("phase") != "Completed":
        raise ValueError("only completed runs can be continued")
    saved = save_feedback(rel, feedback_text)  # the continue-file lives in feedback/
    session = f"agent_{base.name}"
    _tmux_run(
        session,
        f".venv/bin/python experiments/03_run_agents/run.py "
        f"--projects {proposal} --modes multi_phase --continue-file {ROOT / saved['path']}",
    )
    return {"ok": True, "session": session, "feedback": saved["path"]}


def launch_options() -> dict:
    """Every proposal × mode, marking combos that already have a run dir."""
    proposals = []
    for p in sorted((ROOT / "proposals").glob("*.md")):
        proposals.append(
            {
                "name": p.stem,
                "existing": {
                    m: (RUN_OUTPUT_ROOT / f"{p.stem}_{m}").exists() for m in MODES
                },
            }
        )
    return {"proposals": proposals, "modes": list(MODES)}


def launch_run(proposal: str, mode: str) -> dict:
    """Start a fresh agent run for a proposal, detached in its own tmux session
    (so it survives this server restarting, and lands where the user's manually
    launched runs live)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", proposal or ""):
        raise ValueError("bad proposal name")
    if not (ROOT / "proposals" / f"{proposal}.md").exists():
        raise ValueError(f"no proposal named {proposal}")
    if (RUN_OUTPUT_ROOT / f"{proposal}_{mode}").exists():
        raise ValueError(f"{proposal}_{mode} already has a run dir — resume it instead")
    session = f"agent_{proposal}_{mode}"
    if (
        subprocess.run(
            ["tmux", "has-session", "-t", session], capture_output=True
        ).returncode
        == 0
    ):
        raise ValueError(f"tmux session {session} already exists")
    _tmux_run(
        session,
        f".venv/bin/python experiments/03_run_agents/run.py --projects {proposal} --modes {mode}",
    )
    return {"ok": True, "session": session}


class Handler(BaseHTTPRequestHandler):
    # The polling page aborts/closes connections constantly, which would
    # otherwise spew BrokenPipe/ConnectionReset tracebacks and look like crashes.
    def log_message(self, *args):  # quiet
        pass

    def log_error(self, *args):  # quiet (incl. connection-reset noise)
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError, OSError):
            pass  # client disconnected mid-response

    def _json(self, obj, code: int = 200):
        self._send(
            code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8"
        )

    def _stream(self, agent_id: str):
        """Server-Sent Events: push the transcript whenever it changes.

        The server watches the agent's session on disk and
        emits a ``data:`` event only when content actually moved, with an
        adaptive back-off so finished/idle runs settle into cheap heartbeats
        while an actively-running agent streams at ~1s. Replaces client polling.
        """
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            return
        last_sig = None
        interval = 0.8
        deadline = time.monotonic() + 6 * 3600  # hard cap so threads never leak
        while time.monotonic() < deadline:
            try:
                data = get_transcript(agent_id)
            except Exception as exc:  # noqa: BLE001 - keep the stream alive
                data = {"error": f"{type(exc).__name__}: {exc}"}
            sig = transcript_signature(data)
            try:
                if sig != last_sig:
                    last_sig = sig
                    interval = 0.8
                    self.wfile.write(
                        b"data: " + json.dumps(data).encode("utf-8") + b"\n\n"
                    )
                else:
                    interval = min(interval * 1.5, 5.0)
                    self.wfile.write(b": hb\n\n")  # heartbeat + disconnect probe
                self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                return  # client closed the EventSource
            time.sleep(interval)

    def _lens_stream(self, job: str):
        """SSE: stream a Run Lens job's answer (assistant turns) as it works."""
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            return
        last_sig = None
        sent_final = False
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            try:
                data = lens_transcript(job)
            except Exception as exc:  # noqa: BLE001
                data = {"error": f"{type(exc).__name__}: {exc}"}
            sig = _lens_signature(data)
            try:
                if sig != last_sig:
                    last_sig = sig
                    self.wfile.write(
                        b"data: " + json.dumps(data).encode("utf-8") + b"\n\n"
                    )
                else:
                    self.wfile.write(b": hb\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                return
            if data.get("error") or not data.get("running"):
                if sent_final:
                    return
                sent_final = True  # one more flush after the run ends, then stop
            time.sleep(0.7)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except (json.JSONDecodeError, ValueError):
            return {}

    def do_POST(self):
        # Local imports: both modules import back from this module.
        from src import blogpost_studio_web, blueteam_web, proposals_web

        if (
            blogpost_studio_web.handle(self, "POST")
            or proposals_web.handle(self, "POST")
            or blueteam_web.handle(self, "POST")
        ):
            return
        try:
            path = urlparse(self.path).path
            if path == "/api/launch":
                body = self._read_body()
                try:
                    self._json(
                        launch_run(body.get("proposal") or "", body.get("mode") or "")
                    )
                except ValueError as exc:
                    self._json({"error": str(exc)}, code=400)
            elif path in ("/api/feedback", "/api/resume", "/api/continue"):
                body = self._read_body()
                fn = {
                    "/api/feedback": lambda: save_feedback(
                        body.get("run") or "", body.get("text") or ""
                    ),
                    "/api/resume": lambda: resume_run(body.get("run") or ""),
                    "/api/continue": lambda: continue_run(
                        body.get("run") or "", body.get("text") or ""
                    ),
                }[path]
                try:
                    self._json(fn())
                except ValueError as exc:
                    self._json({"error": str(exc)}, code=400)
            elif path == "/api/lens/ask":
                body = self._read_body()
                self._json(
                    start_lens((body.get("id") or ""), body.get("question") or "")
                )
            elif path == "/api/lens/cancel":
                body = self._read_body()
                self._json(cancel_lens(body.get("job") or ""))
            else:
                self._send(404, b"not found", "text/plain")
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                self._json({"error": f"{type(exc).__name__}: {exc}"}, code=500)
            except Exception:
                pass

    def do_GET(self):
        # Local imports: both modules import back from this module.
        from src import blogpost_studio_web, blueteam_web, proposals_web

        if (
            blogpost_studio_web.handle(self, "GET")
            or proposals_web.handle(self, "GET")
            or blueteam_web.handle(self, "GET")
        ):
            return
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/launch/options":
                self._json(launch_options())
            elif path == "/api/project":
                rel = (parse_qs(parsed.query).get("run") or [""])[0]
                try:
                    self._json(project_info(rel))
                except ValueError as exc:
                    self._json({"error": str(exc)}, code=400)
            elif path in ("/", "/index.html"):
                self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/tree":
                qs = parse_qs(parsed.query)
                rel = (qs.get("path") or [""])[0]
                self._json({"path": rel, "items": list_dir(rel)})
            elif path == "/api/overview":
                self._json({"runs": list_runs_overview()})
            elif path == "/api/agent":
                qs = parse_qs(parsed.query)
                self._json(get_transcript((qs.get("id") or [""])[0]))
            elif path == "/api/stream":
                qs = parse_qs(parsed.query)
                self._stream((qs.get("id") or [""])[0])
            elif path == "/api/lens/stream":
                qs = parse_qs(parsed.query)
                self._lens_stream((qs.get("job") or [""])[0])
            elif path == "/api/lens/poll":
                qs = parse_qs(parsed.query)
                raw = (qs.get("jobs") or [""])[0]
                self._json({"jobs": lens_poll([x for x in raw.split(",") if x])})
            elif path == "/api/run-file":
                qs = parse_qs(parsed.query)
                data = run_image_file(
                    (qs.get("id") or [""])[0],
                    (qs.get("path") or [""])[0],
                )
                if data is None:
                    self._send(404, b"not found", "text/plain")
                else:
                    body, ctype = data
                    self._send(200, body, ctype)
            else:
                self._send(404, b"not found", "text/plain")
        except (BrokenPipeError, ConnectionError, OSError):
            pass  # client went away; nothing to do
        except Exception as exc:  # noqa: BLE001 - never let a handler kill the server
            try:
                self._json({"error": f"{type(exc).__name__}: {exc}"}, code=500)
            except Exception:
                pass


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Viewer</title>
<style>
/*__PALETTE__*/
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 var(--sans);
  height:100vh;display:flex;flex-direction:column}
/* same full-width top header as the studio / proposals pages */
.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--panel3);
  color:var(--fg);border:1px solid var(--border);padding:8px 14px;border-radius:8px;opacity:0;
  transition:opacity .2s;pointer-events:none;z-index:9999;font-size:13px}
.toast.show{opacity:1}
.apphead{display:flex;align-items:center;gap:12px;padding:12px;background:var(--panel);
  border-bottom:1px solid var(--border);flex:0 0 auto}
::selection{background:rgba(122,162,247,.3)}
.sidebar::-webkit-scrollbar,.main::-webkit-scrollbar,pre::-webkit-scrollbar{width:9px;height:9px}
.sidebar::-webkit-scrollbar-thumb,.main::-webkit-scrollbar-thumb,pre::-webkit-scrollbar-thumb{background:var(--panel3);border-radius:6px}
.app{display:grid;grid-template-columns:var(--sidebar-w,300px) 6px minmax(0,1fr);flex:1;min-height:0}
.app.lens-open{grid-template-columns:var(--sidebar-w,300px) 6px minmax(0,1fr) 6px var(--lens-w,420px)}
.sidebar{background:var(--panel);border-right:1px solid var(--border);overflow-y:auto;padding:12px}
.resizer{cursor:col-resize;background:var(--border);transition:background .12s}
.resizer:hover,.resizer.active{background:var(--accent)}
.resizer[hidden]{display:none}
#lensResizer{grid-column:4}
.ovbtn{width:100%;display:flex;align-items:center;justify-content:center;gap:8px;background:var(--panel2);border:1px solid var(--border);color:var(--fg);border-radius:8px;padding:9px 10px;margin-bottom:11px;cursor:pointer;font-size:13px;font-weight:700;letter-spacing:.2px;transition:.12s}
/* Same compact pill as the studio header so the nav keeps its shape across pages. */
/* launch-a-run dialog */
.launcher{position:fixed;left:12px;top:166px;z-index:60;width:min(440px,90vw);max-height:70vh;overflow:auto;
  background:var(--panel);border:1px solid var(--border);border-radius:10px;
  box-shadow:0 16px 48px rgba(0,0,0,.6);padding:12px}
.lhead{display:flex;align-items:center;font-weight:700;font-size:14px;margin-bottom:2px}
.lclose{margin-left:auto;font-size:14px;padding:0 8px;background:transparent;border-color:transparent;color:var(--muted)}
.lclose:hover{color:var(--fg)}
.lsub{color:var(--muted);font-size:11.5px;margin-bottom:10px}
.lrow{display:flex;align-items:center;gap:6px;padding:4px 2px;border-top:1px solid var(--border)}
.lrow:first-child{border-top:0}
/* project panel (feedback / resume / continue), anchored under the topbar */
.ppback{position:fixed;inset:0;z-index:59;background:rgba(0,0,0,.55);backdrop-filter:blur(2px)}
.ppback[hidden]{display:none}
.projpanel{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:60;width:min(900px,94vw);max-height:88vh;overflow:auto;
  background:var(--panel);border:1px solid var(--border);border-radius:14px;
  box-shadow:0 24px 80px rgba(0,0,0,.7);padding:18px 20px;display:flex;flex-direction:column;gap:12px}
.projpanel[hidden]{display:none}
.projpanel .lhead{font-size:15px}
.pp-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.pp-name{color:var(--muted);font-family:var(--mono);font-size:11.5px;font-weight:400;margin-left:8px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:55%}
.pp-status{font-size:12px;color:var(--muted);font-family:var(--mono);line-height:1.7;
  background:var(--panel2);border:1px solid var(--border);border-radius:7px;padding:8px 10px}
.pp-status b{color:var(--fg)} .pp-status .bad{color:var(--err)} .pp-status .good{color:var(--ok)}
#ppText{resize:vertical;min-height:38vh;background:var(--panel2);color:var(--fg);border:1px solid var(--border);
  border-radius:9px;padding:12px 14px;font:13.5px/1.55 var(--sans);outline:none}
#ppText:focus{border-color:var(--accent)}
.pp-actions{display:flex;align-items:center;gap:10px}
.pp-actions .mini{font-size:13px;padding:8px 16px;border-radius:8px}
.pp-actions .spacer{flex:1}
.pp-fb{display:flex;flex-direction:column;gap:5px}
.pp-fb .fbitem{font-size:12.5px;color:var(--muted);border-left:2px solid var(--border);padding:4px 10px;
  white-space:pre-wrap;max-height:110px;overflow:auto}
.pp-fb .fbitem .fbdate{color:var(--faint);font-family:var(--mono);font-size:10px}
.lname{flex:1;min-width:0;font-size:12px;font-family:var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lmode{font-size:11px;padding:2px 9px}
.ovbtn:hover{border-color:var(--accent)}
.ovbtn.active{border-color:var(--accent);background:var(--panel3);box-shadow:0 0 0 1px var(--accent)}
.browse-head{display:flex;align-items:center;justify-content:space-between;margin:2px 4px 10px}
.browse-head h1{font-size:13px;letter-spacing:.5px;text-transform:uppercase;color:var(--muted);margin:0}
.browse-head button{background:var(--panel2);border:1px solid var(--border);color:var(--muted);border-radius:6px;cursor:pointer;font-size:14px;line-height:1;padding:3px 8px}
.browse-head button:hover{color:var(--fg);border-color:var(--accent)}
.breadcrumb{display:flex;flex-wrap:wrap;gap:1px;align-items:center;font-size:11px;margin:0 2px 9px}
.crumb{color:var(--accent2);cursor:pointer;padding:1px 4px;border-radius:4px;font-family:var(--mono)}
.crumb:hover{background:var(--panel3)}
.crumb.cur{color:var(--fg);cursor:default}.crumb.cur:hover{background:none}
.csep{color:var(--faint)}
.row{display:flex;align-items:center;gap:8px;width:100%;text-align:left;background:var(--panel2);border:1px solid var(--border);
  color:var(--fg);border-radius:8px;padding:8px 10px;margin-bottom:6px;cursor:pointer;transition:.12s}
.row:hover{border-color:var(--accent)}
.row.active{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.row .ic{flex:none;width:15px;text-align:center;color:var(--muted)}
.row.dir .ic{color:var(--tool)}
.row .name{font-weight:600;font-size:13px;word-break:break-all;flex:1 1 auto}
.row .rmeta{display:flex;gap:6px;align-items:center;flex:none}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block;flex:none}
.dot.live{background:var(--ok);box-shadow:0 0 6px var(--ok);position:relative}
.dot.quiet{background:var(--warn);box-shadow:0 0 6px var(--warn)}
.dot.stale{background:var(--err);box-shadow:0 0 6px var(--err)}
.dot.done{background:var(--faint)}
.badge{font-size:9px;padding:1px 6px;border-radius:6px;background:#2a2f3a;color:var(--accent);text-transform:uppercase;letter-spacing:.4px}
.count{font-size:10px;color:var(--muted);font-family:var(--mono)}
.main{overflow-y:auto;padding:0 0 60px}
.stickyhead{position:sticky;top:0;z-index:5;background:rgba(13,16,23,.94);backdrop-filter:blur(6px);border-bottom:1px solid var(--border)}
.topbar{padding:11px 22px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.topbar .title{font-weight:700;font-size:15px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:44vw}
.tbtn{background:var(--panel2);border:1px solid var(--border);color:var(--muted);border-radius:6px;padding:3px 9px;font-size:11px;cursor:pointer;transition:.12s}
.tbtn:hover{color:var(--fg);border-color:var(--accent)}
.tbtn:disabled,.tbtn:disabled:hover{opacity:.4;cursor:not-allowed;color:var(--muted);border-color:var(--border)}
.flt{width:100%;background:var(--panel2);border:1px solid var(--border);color:var(--fg);border-radius:7px;padding:6px 9px;font-size:12px;outline:none;margin-bottom:10px}
.flt:focus{border-color:var(--accent)}
.costlbl{font-size:14px;font-weight:700;color:var(--ok);font-family:var(--mono)}
.content{max-width:1000px;margin:0 auto;padding:18px 22px}
.turn{margin:14px 0;border:1px solid var(--border);border-radius:10px;overflow:hidden;background:var(--panel)}
.turn .role{font-size:11px;text-transform:uppercase;letter-spacing:.6px;padding:7px 14px;font-weight:700;border-bottom:1px solid var(--border)}
.turn.user .role{color:var(--user)} .turn.assistant .role{color:var(--assist)}
.turn.user{border-left:3px solid var(--user)} .turn.assistant{border-left:3px solid var(--assist)}
.turn .body{padding:6px 14px 12px}
.block{margin:10px 0}
.text{white-space:pre-wrap;word-wrap:break-word}
details.think,details.tool,details.sub{border:1px solid var(--border);border-radius:8px;margin:9px 0;background:var(--panel2)}
details>summary{cursor:pointer;padding:7px 12px;font-size:12px;font-weight:600;list-style:none;display:flex;gap:8px;align-items:center}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"▸";color:var(--muted)}
details[open]>summary::before{content:"▾"}
.think>summary{color:var(--think)} .tool>summary{color:var(--tool)} .sub>summary{color:var(--accent)}
.k{font-size:9px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;padding:1px 6px;border-radius:5px;background:#2a2f3a;color:var(--muted)}
.inner{padding:0 12px 12px}
pre{background:#0b0d13;border:1px solid var(--border);border-radius:7px;padding:10px;overflow:auto;font-family:var(--mono);font-size:12.5px;margin:6px 0;white-space:pre-wrap;word-break:break-word}
.think .inner .text{color:#c8bfe7;font-style:italic}
.tag{font-size:10px;padding:1px 6px;border-radius:5px;background:#2a2f3a;color:var(--muted);margin-left:auto}
.tag.err{background:#3a2330;color:var(--err)} .tag.ok{background:#23311f;color:var(--ok)}
.sesstabs{display:flex;gap:6px;flex-wrap:wrap;padding:8px 22px 10px;max-width:1000px;margin:0 auto;
  max-height:min(26vh,240px);overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin}
.sesstab{font-size:12px;border:1px solid var(--border);background:var(--panel2);color:var(--muted);border-radius:7px;padding:4px 10px;cursor:pointer;transition:.12s;display:inline-flex;align-items:center}
.sesstab:hover{color:var(--fg);border-color:var(--faint)}
.sesstab.active{border-color:var(--accent);color:var(--fg);background:var(--panel3)}
.sesstab .tc{font-size:9px;color:var(--faint);margin-left:6px;font-family:var(--mono)}
.sesstab.active .tc{color:var(--muted)}
.tabgroup{font-size:10px;letter-spacing:.4px;text-transform:uppercase;color:var(--faint);align-self:center;padding:0 8px 0 0;white-space:nowrap}
.tabbreak{flex:0 0 100%;height:0;margin:0;padding:0;border:0}
.lens-toggle.active{border-color:var(--accent);color:var(--fg);background:var(--panel3)}
/* Run Lens drawer */
.lens{grid-column:5;min-width:0;height:100%;overflow:hidden;
  background:var(--panel);border-left:1px solid var(--border);display:flex;flex-direction:column}
.lens[hidden]{display:none}
.lens-head{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:44px;padding:9px 12px;border-bottom:1px solid var(--border);background:var(--panel2)}
.lens-title{min-width:0;font-weight:700;font-size:13px;display:flex;gap:7px;align-items:center}
.lens-mark{color:var(--accent)}
.lens-sub{font-weight:500;font-size:11px;color:var(--muted);font-family:var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:230px}
.lens-actions{display:flex;gap:6px;align-items:center;flex:none}
.lens-msgs{flex:1;overflow-y:auto;padding:12px 14px;background:var(--panel)}
.lens-msgs .lens-empty{padding:28px 14px;color:var(--muted);font-size:13px;line-height:1.5;text-align:left}
.lens-q{margin:4px 0 10px;padding:8px 11px;background:var(--panel3);border:1px solid var(--border);border-radius:8px;color:var(--fg);font-size:13px;white-space:pre-wrap;word-break:break-word}
.lens-q .who{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--user);margin-bottom:3px;font-weight:700}
.lens-ans{margin:2px 0 16px;padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,.04)}
.lens-ans .who{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--accent);margin-bottom:5px;font-weight:700}
.lens-thinking{color:var(--muted);font-size:12px;font-style:italic}
.md-img{max-width:100%;height:auto;border:1px solid var(--border);border-radius:6px;margin:8px 0;background:#fff;display:block;cursor:zoom-in}
.img-lightbox{position:fixed;inset:0;z-index:10000;background:rgba(3,5,10,.88);display:flex;align-items:center;justify-content:center;padding:44px 28px 34px}
.img-lightbox[hidden]{display:none}
.img-lightbox img{max-width:96vw;max-height:88vh;object-fit:contain;background:#fff;border:1px solid var(--border);border-radius:6px;box-shadow:0 14px 45px rgba(0,0,0,.55)}
.img-lightbox-close{position:absolute;top:12px;right:16px;border:1px solid var(--border);background:var(--panel2);color:var(--fg);border-radius:7px;padding:5px 10px;cursor:pointer;font-size:18px;line-height:1}
.img-lightbox-close:hover{border-color:var(--accent)}
.img-lightbox-caption{position:absolute;left:28px;right:64px;bottom:10px;color:var(--muted);font:12px/1.4 var(--mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lens-composer{border-top:1px solid var(--border);padding:10px 12px;background:var(--panel2)}
.lens-composer textarea{width:100%;resize:vertical;min-height:44px;max-height:170px;background:var(--bg);border:1px solid var(--border);color:var(--fg);border-radius:8px;padding:8px 10px;font:13px/1.5 var(--sans);outline:none}
.lens-composer textarea:focus{border-color:var(--accent)}
.lens-row{display:flex;align-items:center;gap:8px;margin-top:7px}
.lens-status{flex:1;font-size:11px;color:var(--muted);font-family:var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lens-send{border-color:rgba(122,162,247,.5);color:var(--fg);background:rgba(122,162,247,.12)}
.empty{color:var(--muted);text-align:center;padding:60px 20px}
.controls{margin-left:auto;display:flex;gap:10px;align-items:center;font-size:12px;color:var(--muted)}
.controls label{display:flex;gap:5px;align-items:center;cursor:pointer}
.gobjective{white-space:pre-wrap;color:var(--muted);font-size:12px;max-width:1000px;margin:6px auto 0;padding:0 22px}
/* markdown rendering for message/thinking text */
.md{line-height:1.6;word-wrap:break-word}
.md>:first-child{margin-top:0}.md>:last-child{margin-bottom:0}
.md h3,.md h4,.md h5,.md h6{margin:15px 0 7px;line-height:1.3;font-weight:700}
.md h3{font-size:16.5px;color:#fff;border-bottom:1px solid var(--border);padding-bottom:4px}
.md h4{font-size:14.5px;color:var(--fg)} .md h5,.md h6{font-size:12.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
.md p{margin:8px 0}
.md ul,.md ol{margin:8px 0;padding-left:22px} .md li{margin:3px 0}
.md code{background:var(--code-bg);border:1px solid var(--border);border-radius:4px;padding:.5px 5px;font-family:var(--mono);font-size:.88em;color:var(--accent2)}
.md pre.code{background:var(--code-bg);border:1px solid var(--border);border-radius:8px;padding:12px;overflow:auto;margin:9px 0}
.md pre.code code{background:none;border:none;padding:0;font-size:12.5px;color:#cdd3e0}
.md a{color:var(--accent2);text-decoration:none} .md a:hover{text-decoration:underline}
.md strong{color:#fff;font-weight:700} .md em{color:#cdd3e0}
.md blockquote{border-left:3px solid var(--accent);margin:8px 0;padding:2px 12px;color:var(--muted)}
.md table{border-collapse:collapse;margin:9px 0;font-size:13px} .md th,.md td{border:1px solid var(--border);padding:4px 9px;text-align:left} .md th{background:var(--panel3)}
.md hr{border:none;border-top:1px solid var(--border);margin:12px 0}
.think .md{color:#c4bce0}
/* live indicator pulse */
.dot.live::after{content:"";position:absolute;inset:-3px;border-radius:50%;border:1px solid var(--ok);animation:pulse 1.7s ease-out infinite}
@keyframes pulse{0%{transform:scale(.7);opacity:.8}100%{transform:scale(2.4);opacity:0}}
.phasetag{font-size:9px;font-weight:700;letter-spacing:.5px;border:1px solid var(--border);border-radius:5px;padding:0 5px}
.phasetag.active{color:var(--ok);border-color:rgba(158,206,106,.4)}
.phasetag.completed{color:var(--faint)}
.phasetag.failed{color:var(--err);border-color:rgba(247,118,142,.45)}
/* Overview dashboard (homepage) */
.dash{max-width:1040px;margin:0 auto;padding:18px 22px}
.dash-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:2px 2px 14px;flex-wrap:wrap}
.dash-title{font-size:16px;font-weight:700}
.dash-title span{color:var(--muted);font-weight:500;font-size:13px}
.dash-actions{display:flex;gap:8px;align-items:center}
.phase-tabs{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 2px 14px}
.phase-tab{border:1px solid var(--border);background:var(--panel2);color:var(--muted);border-radius:7px;padding:6px 10px;font-size:12px;font-weight:700;cursor:pointer;transition:.12s}
.phase-tab:hover{border-color:var(--accent);color:var(--fg)}
.phase-tab.active{border-color:var(--accent);background:var(--panel3);color:var(--fg)}
.phase-tab .num{color:var(--faint);font-weight:600;margin-left:4px}
.dash-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.dgroup{grid-column:1/-1;font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:var(--faint);font-weight:700;margin:10px 2px 0}
.dgroup:first-child{margin-top:0}
.card{border:1px solid var(--border);border-radius:10px;background:var(--panel);padding:11px 13px;cursor:pointer;transition:.12s;display:flex;flex-direction:column;gap:7px;min-width:0}
.card:hover{border-color:var(--accent)}
.card-top{display:flex;align-items:center;gap:8px}
.card-name{font-weight:700;font-size:13px;word-break:break-all;flex:1}
.card-meta{font-size:11px;color:var(--muted);font-family:var(--mono);display:flex;gap:4px 8px;flex-wrap:wrap}
.card-meta b{color:var(--fg);font-weight:600}
.card-sum{font-size:12.5px;line-height:1.5;color:var(--fg);border-top:1px solid var(--border);padding-top:7px}
.card-sum .ph{color:var(--faint)}
.card-sum .working{color:var(--accent)}
.card-sum .err{color:var(--err)}
.card-sum .md>:first-child{margin-top:0}.card-sum .md>:last-child{margin-bottom:0}
.card-actions{display:flex;gap:6px;justify-content:flex-end}
.mini{font-size:10px;padding:2px 8px;border-radius:5px;background:var(--panel2);border:1px solid var(--border);color:var(--muted);cursor:pointer;transition:.12s}
.mini:hover{color:var(--fg);border-color:var(--accent)}
/* Top route/transition progress bar (shows during foreground fetches) */
#topbar-progress{position:fixed;top:0;left:0;height:3px;width:0;z-index:9999;
  background:linear-gradient(90deg,var(--accent),var(--accent2));
  box-shadow:0 0 10px var(--accent),0 0 4px var(--accent);border-radius:0 2px 2px 0;
  opacity:0;transition:width .2s ease,opacity .35s ease;pointer-events:none}
#topbar-progress.active{opacity:1}
/* Spinner + loading placeholder for the main content / dashboard */
.spinner{width:34px;height:34px;border-radius:50%;
  border:3px solid var(--panel3);border-top-color:var(--accent);
  animation:spin .8s linear infinite;margin:0 auto 14px}
@keyframes spin{to{transform:rotate(360deg)}}
.loading-box{color:var(--muted);text-align:center;padding:70px 20px;animation:fadein .25s ease}
@keyframes fadein{from{opacity:0}to{opacity:1}}
.loading-box .lmsg{font-size:13px;letter-spacing:.3px}
.loading-box .lsub{font-size:11px;color:var(--faint);margin-top:5px;font-family:var(--mono);word-break:break-all}
</style></head>
<body>
<div id="topbar-progress"></div>
<header class="apphead">
  <nav class="appnav"><a class="on" href="/">🔎 Runs</a><a href="/proposals" title="Read, edit, and write research proposals">🗒 Proposals</a><a href="/studio" title="Co-write a blogpost about a finished run">📝 Studio</a><a href="/blueteam" title="Watch a read-only agent audit a finished run for sabotage">🛡 Blue Team</a></nav>
</header>
<div class="app">
  <div class="sidebar">
    <button id="overviewBtn" class="ovbtn" title="Status dashboard of all runs">⌂ Overview — all runs</button>
    <button id="launchBtn" class="ovbtn" title="Start a new agent run from a proposal">🚀 Launch a run</button>
    <div class="launcher" id="launcher" hidden>
      <div class="lhead">Launch a new run <button class="lclose" id="launchClose" title="Close">×</button></div>
      <div class="lsub">Pick a proposal and a mode. Combos that already have a run are disabled.</div>
      <div id="launchList" class="llist"></div>
    </div>
    <div class="browse-head"><h1>Browse</h1><button id="refresh" title="Refresh">⟳</button></div>
    <div id="breadcrumb" class="breadcrumb"></div>
    <input id="filter" class="flt" placeholder="filter…" autocomplete="off">
    <div id="tree"></div>
  </div>
  <div class="resizer" id="resizer" title="Drag to resize"></div>
  <div class="main">
    <div class="stickyhead">
    <div class="topbar">
      <span class="title" id="title">Select a run</span>
      <span class="costlbl" id="costlbl" style="display:none" title="total model spend on this run"></span>
      <div class="controls">
        <button class="tbtn" id="projBtn" disabled title="Feedback, resume, and continuation for this run">⚙ Project</button>
        <button class="tbtn" id="tabsToggle" title="Hide / show the phase tabs" style="display:none">▾ phases</button>
        <button class="tbtn" id="toggleAll" title="Expand / collapse all blocks">expand</button>
        <button class="tbtn lens-toggle" id="lensBtn" disabled title="Open a run to ask the read-only oversight agent about it">🔍 Run Lens</button>
        <label><input type="checkbox" id="autorefresh" checked> live</label>
      </div>
    </div>
    <div id="sesstabs" class="sesstabs"></div>
    </div>
    <div class="ppback" id="ppBack" hidden></div>
    <div class="projpanel" id="projpanel" hidden>
      <div class="lhead">Project <span class="pp-name" id="ppName"></span><button class="lclose" id="ppClose" title="Close">×</button></div>
      <div class="pp-status" id="ppStatus"></div>
      <div class="pp-label">Feedback / continuation instructions</div>
      <textarea id="ppText" rows="10" placeholder="Feedback / further instructions for this project…&#10;Saved under feedback/<run>/ — and used as the new instructions if you launch a continuation."></textarea>
      <div class="pp-actions">
        <button class="mini" id="ppSave">Save feedback</button>
        <span class="spacer"></span>
        <button class="mini" id="ppResume" hidden title="Relaunch this run with --resume in its tmux session">⟲ Resume run</button>
        <button class="mini" id="ppContinue" hidden title="Relaunch this completed run with the feedback above as its new instructions">🚀 Launch continuation</button>
      </div>
      <div class="pp-label">Saved feedback</div>
      <div class="pp-fb" id="ppFb"></div>
    </div>
    <div class="content" id="content"><div class="empty">Click through the folders on the left and pick a run to view its transcript.</div></div>
  </div>
  <div class="resizer" id="lensResizer" title="Drag to resize Run Lens" hidden></div>
  <aside class="lens" id="lens" hidden>
    <div class="lens-head">
      <div class="lens-title"><span class="lens-mark">›</span> Run Lens <span class="lens-sub" id="lensCtx">no run</span></div>
      <div class="lens-actions">
        <button class="tbtn" id="lensNew" title="Start a new chat for this run">New</button>
        <button class="tbtn" id="lensClose" title="Close">×</button>
      </div>
    </div>
    <div class="lens-msgs" id="lensMsgs"><div class="lens-empty empty">Ask a read-only agent about this run — its state, code, or transcripts.</div></div>
    <div class="lens-composer">
      <textarea id="lensInput" rows="2" placeholder="Ask about this run… (Enter to send)"></textarea>
      <div class="lens-row"><span class="lens-status" id="lensStatus"></span><button class="tbtn lens-send" id="lensSend">Ask</button><button class="tbtn" id="lensStop" hidden>Stop</button></div>
    </div>
  </aside>
</div>
<div class="img-lightbox" id="imgLightbox" hidden>
  <button class="img-lightbox-close" id="imgLightboxClose" title="Close enlarged image">×</button>
  <img id="imgLightboxImg" alt="">
  <div class="img-lightbox-caption" id="imgLightboxCaption"></div>
</div>
<script>
const E=s=>document.createElement(s);
const esc=s=>(s==null?"":String(s)).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));

// Minimal, dependency-free, escape-first markdown renderer for transcript text.
// Memoized: the same block text renders identically, and switching tabs / live
// re-renders would otherwise re-parse the same markdown repeatedly.
const _mdCache=new Map();
function md(src){
  if(!src) return "";
  const hit=_mdCache.get(src); if(hit!==undefined) return hit;
  const out=_md(src);
  if(_mdCache.size>4000)_mdCache.clear();
  _mdCache.set(src,out);
  return out;
}
function _md(src){
  if(!src) return "";
  const inl=t=>t
    .replace(/`([^`]+)`/g,(m,c)=>"<code>"+c+"</code>")
    .replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g,"$1<em>$2</em>")
    .replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g,'<img alt="$1" src="$2" class="md-img" loading="lazy">')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  const cell=c=>inl(esc(c.trim()));
  const lines=String(src).replace(/\r/g,"").split("\n");
  let out="",para=[],list=null;
  const flushP=()=>{ if(para.length){out+="<p>"+inl(esc(para.join("\n")))+"</p>";para=[];} };
  const flushL=()=>{ if(list){out+="</"+list+">";list=null;} };
  for(let i=0;i<lines.length;i++){
    let line=lines[i],m;
    if(/^\s*```/.test(line)){ flushP();flushL(); const buf=[]; i++; while(i<lines.length&&!/^\s*```/.test(lines[i])){buf.push(lines[i]);i++;} out+="<pre class='code'><code>"+esc(buf.join("\n"))+"</code></pre>"; continue; }
    if(/\|/.test(line) && i+1<lines.length && /-/.test(lines[i+1]) && /^\s*\|?[\s:\-|]+\|?\s*$/.test(lines[i+1])){
      flushP();flushL();
      const row=l=>l.replace(/^\s*\|/,"").replace(/\|\s*$/,"").split("|");
      let tbl="<table><thead><tr>"+row(line).map(c=>"<th>"+cell(c)+"</th>").join("")+"</tr></thead><tbody>"; i+=2;
      while(i<lines.length && /\|/.test(lines[i]) && lines[i].trim()!==""){ tbl+="<tr>"+row(lines[i]).map(c=>"<td>"+cell(c)+"</td>").join("")+"</tr>"; i++; }
      i--; out+=tbl+"</tbody></table>"; continue;
    }
    if(/^\s*([-*_])\1{2,}\s*$/.test(line)){ flushP();flushL();out+="<hr>"; continue; }
    if(m=line.match(/^(#{1,6})\s+(.*)$/)){ flushP();flushL();const h=Math.min(m[1].length+2,6);out+="<h"+h+">"+inl(esc(m[2]))+"</h"+h+">"; continue; }
    if(m=line.match(/^\s*[-*+]\s+(.*)$/)){ flushP();if(list!=="ul"){flushL();list="ul";out+="<ul>";}out+="<li>"+inl(esc(m[1]))+"</li>"; continue; }
    if(m=line.match(/^\s*\d+[.)]\s+(.*)$/)){ flushP();if(list!=="ol"){flushL();list="ol";out+="<ol>";}out+="<li>"+inl(esc(m[1]))+"</li>"; continue; }
    if(m=line.match(/^>\s?(.*)$/)){ flushP();flushL();out+="<blockquote>"+inl(esc(m[1]))+"</blockquote>"; continue; }
    if(line.trim()===""){ flushP();flushL(); continue; }
    para.push(line);
  }
  flushP();flushL();
  return out;
}

const LENS_STORE_KEY="av.runLensConvos.v1";
const LENS_MAX_CONVOS=40;
const LENS_MAX_BYTES=1800000;
function lensReadStore(){
  try{
    const raw=localStorage.getItem(LENS_STORE_KEY);
    if(!raw)return {convos:{},times:{},jobs:{}};
    const parsed=JSON.parse(raw);
    const convos={},times={},jobs={};
    for(const [id,v] of Object.entries((parsed&&parsed.convos)||{})){
      if(v&&typeof v.html==="string"){
        convos[id]=v.html;times[id]=Number(v.updatedAt)||0;
        if(v.job)jobs[id]=v.job;   // a job that was still running when we last saved
      }
    }
    return {convos,times,jobs};
  }catch(_){return {convos:{},times:{},jobs:{}};}
}
const _lensSaved=lensReadStore();
let state={agentId:null,sess:0,data:null,es:null,path:"",items:[],filter:"",
           panes:{},paneAgent:null,lensOpen:false,lensEs:null,lensJob:null,lensRun:null,
           lensConvos:_lensSaved.convos,lensConvoTimes:_lensSaved.times,lensJobs:_lensSaved.jobs,
           view:"overview",overview:[],overviewSig:"",dashPhase:localStorage.getItem("av.dashPhase")||"",
           summaries:{},sumQueue:[],sumActive:0,sumPoll:null,
           tabsCollapsed:(v=>v==="1"?true:v==="0"?false:null)(localStorage.getItem("av.tabsCollapsed"))};
let busyTree=false;

// Thin top loading bar so navigation/fetches feel responsive instead of frozen.
// Ref-counted: concurrent foreground fetches share one bar; it creeps toward 90%
// while in flight, then snaps to 100% and fades out once everything settles.
const Progress=(()=>{
  let val=0,timer=null,active=0;
  const bar=()=>document.getElementById("topbar-progress");
  const set=v=>{val=v;const b=bar();if(b)b.style.width=(v*100)+"%";};
  function start(){
    if(++active>1)return;
    const b=bar();if(b)b.classList.add("active");set(0.08);
    clearInterval(timer);
    timer=setInterval(()=>{const rem=0.9-val;if(rem>0.01)set(val+rem*0.12);},300);
  }
  function done(){
    if(active>0)active--;
    if(active>0)return;
    clearInterval(timer);timer=null;set(1);
    setTimeout(()=>{const b=bar();if(b)b.classList.remove("active");setTimeout(()=>set(0),360);},200);
  }
  return {start,done};
})();

// quiet=true suppresses the progress bar for recurring background polls (the 3s
// dir/overview refresh, summary polling) so it only flashes on real navigation.
async function jget(u,quiet){
  if(!quiet)Progress.start();
  const ctrl=new AbortController();const t=setTimeout(()=>ctrl.abort(),12000);
  try{const r=await fetch(u,{signal:ctrl.signal});return await r.json();}
  catch(e){return null;}
  finally{clearTimeout(t);if(!quiet)Progress.done();}
}

// Immediate feedback when opening a run, shown until the transcript arrives.
function showContentLoading(id){
  document.getElementById("title").textContent=id||"Loading\u2026";
  const cl=document.getElementById("costlbl"); if(cl)cl.style.display="none";
  document.getElementById("sesstabs").innerHTML="";
  document.getElementById("content").innerHTML=
    '<div class="loading-box"><div class="spinner"></div>'
    +'<div class="lmsg">Loading transcript\u2026</div>'
    +'<div class="lsub">'+esc((id||"").split("/").pop())+'</div></div>';
}

// ---- Folder browser: breadcrumb + current-directory contents (click through) ----
function crumbEl(label,path,cur){
  const c=E("span");c.className="crumb"+(cur?" cur":"");c.textContent=label;
  if(!cur)c.onclick=()=>loadDir(path);
  return c;
}
function renderBreadcrumb(path){
  const box=document.getElementById("breadcrumb");box.innerHTML="";
  const parts=path?path.split("/"):[];
  box.appendChild(crumbEl("outputs","",parts.length===0));
  let acc="";
  parts.forEach((p,i)=>{
    acc=acc?acc+"/"+p:p;
    const sep=E("span");sep.className="csep";sep.textContent="/";box.appendChild(sep);
    box.appendChild(crumbEl(p,acc,i===parts.length-1));
  });
}
function renderTree(items){
  const box=document.getElementById("tree");box.innerHTML="";
  const q=(state.filter||"").toLowerCase();
  const shown=items.filter(it=>!q||it.name.toLowerCase().includes(q));
  if(!shown.length){box.innerHTML='<div class="empty" style="padding:24px 6px">Nothing here.<br>Start a run, clear the filter, or go up.</div>';return;}
  for(const it of shown){
    const row=E("div");
    if(it.type==="dir"){
      row.className="row dir";
      row.innerHTML=`<span class="ic">▸</span><span class="name">${esc(it.name)}</span>`+
        `<span class="rmeta">${it.live?'<span class="dot live"></span>':""}<span class="count">${it.runs}</span></span>`;
      row.onclick=()=>loadDir(it.path);
    }else{
      row.className="row run"+(it.path===state.agentId?" active":"");
      const dot=statusDot(it);
      const tag=statusTag(it);
      row.innerHTML=`<span class="ic">▤</span><span class="name">${esc(it.name)}</span>`+
        `<span class="rmeta">${it.mode?`<span class="badge">${esc(it.mode)}</span>`:""}${dot}${tag}</span>`;
      row.onclick=()=>selectRun(it.path);
    }
    box.appendChild(row);
  }
}
async function loadDir(path){
  if(busyTree)return; busyTree=true;
  try{
    state.path=path||"";
    const res=await jget("/api/tree?path="+encodeURIComponent(state.path));
    state.items=(res&&res.items)||[];
    renderBreadcrumb(state.path);
    renderTree(state.items);
  }finally{busyTree=false;}
}
async function refreshDir(){   // silent refresh so live status/new runs appear
  if(busyTree)return;
  const res=await jget("/api/tree?path="+encodeURIComponent(state.path),true);
  if(res){state.items=res.items||[];renderTree(state.items);}
}
function selectRun(id){
  const switching=id!==state.agentId;
  state.view="run";
  const ob=document.getElementById("overviewBtn"); if(ob)ob.classList.remove("active");
  state.agentId=id;state.sess=0;state._pickDefault=true;location.hash=encodeURIComponent(id);
  renderTree(state.items);   // refresh active highlight
  if(switching)showContentLoading(id);   // instant feedback instead of a frozen-looking pane
  if(switching){const pp=document.getElementById("projpanel"); if(pp)pp.hidden=true;}  // stale run's panel
  openStream();
  // The Run Lens is bound to a specific run: opening a run makes it available
  // and (on a fresh run) docks it open on the side; switching clears stale state.
  if(switching){ lensSwitchTo(id); lensSetOpen(true,false); }
  else { updateLensCtx(); }
}

// ---- Run Lens: read-only oversight agent over the selected run ----
function lensSetOpen(open,focus){
  if(open && !state.agentId) open=false;   // Run Lens is only openable on a specific run
  state.lensOpen=open;
  document.getElementById("lens").hidden=!open;
  document.getElementById("lensResizer").hidden=!open;
  document.querySelector(".app").classList.toggle("lens-open",open);
  const btn=document.getElementById("lensBtn");
  btn.classList.toggle("active",open);
  btn.disabled=!state.agentId;             // no run selected -> can't open the lens
  const pb=document.getElementById("projBtn");
  if(pb) pb.disabled=!state.agentId;       // same gate for the project panel
  if(open){updateLensCtx(); if(focus)document.getElementById("lensInput").focus();}
}
const LENS_EMPTY='<div class="lens-empty empty">Ask a read-only agent about this run \u2014 its state, code, or transcripts.</div>';
// The lens conversation lives in #lensMsgs; we stash each run's rendered chat in
// state.lensConvos keyed by run id so switching runs, refreshing, and deep links
// restore the browser-local conversation.
function lensPersistConvos(){
  try{
    let ids=Object.keys(state.lensConvos).sort((a,b)=>(state.lensConvoTimes[b]||0)-(state.lensConvoTimes[a]||0));
    ids=ids.slice(0,LENS_MAX_CONVOS);
    const out={version:1,convos:{}};
    for(const id of ids){
      out.convos[id]={html:state.lensConvos[id],updatedAt:state.lensConvoTimes[id]||Date.now()};
      if(state.lensJobs&&state.lensJobs[id])out.convos[id].job=state.lensJobs[id];   // resume this on reload
    }
    let raw=JSON.stringify(out);
    while(raw.length>LENS_MAX_BYTES&&ids.length>1){
      const drop=ids.pop(); delete out.convos[drop];
      raw=JSON.stringify(out);
    }
    localStorage.setItem(LENS_STORE_KEY,raw);
  }catch(_){}
}
function lensSaveConvo(touch){
  if(!state.lensRun)return;
  const m=document.getElementById("lensMsgs"); if(!m)return;
  if(m.querySelector(".empty")){
    delete state.lensConvos[state.lensRun];delete state.lensConvoTimes[state.lensRun];lensPersistConvos();return;
  }  // nothing asked yet
  state.lensConvos[state.lensRun]=m.innerHTML;
  if(touch!==false)state.lensConvoTimes[state.lensRun]=Date.now();
  lensPersistConvos();
}
function lensLoadConvo(id){
  const m=document.getElementById("lensMsgs"); if(!m)return;
  m.innerHTML=state.lensConvos[id]||LENS_EMPTY;
  m.scrollTop=m.scrollHeight;
}
function lensSwitchTo(id){   // save the run we were on, detach (but DON'T kill) its job, restore the new run's chat
  if(state.lensRun===id)return;
  lensSaveConvo();
  lensDetach();          // leave any in-flight job running server-side so switching back resumes it
  state.lensRun=id;
  lensLoadConvo(id);
  lensStatus("");
  lensResumeIfRunning(id);
}
function lensNewChat(){   // start a fresh conversation for the current run
  stopLens(true);
  if(state.lensRun){delete state.lensConvos[state.lensRun];delete state.lensConvoTimes[state.lensRun];lensPersistConvos();}
  const m=document.getElementById("lensMsgs"); if(m)m.innerHTML=LENS_EMPTY;
  lensStatus("");
  if(state.lensOpen)document.getElementById("lensInput").focus();
}
function updateLensCtx(){
  const el=document.getElementById("lensCtx"); if(!el)return;
  el.textContent=state.agentId?("· "+state.agentId.split("/").pop()):"no run selected";
}
function lensBusy(b){document.getElementById("lensSend").hidden=b;document.getElementById("lensStop").hidden=!b;}
function lensStatus(s){document.getElementById("lensStatus").textContent=s||"";}
function openImageLightbox(src,caption){
  const box=document.getElementById("imgLightbox"),img=document.getElementById("imgLightboxImg"),cap=document.getElementById("imgLightboxCaption");
  if(!box||!img)return;
  img.src=src||""; img.alt=caption||"";
  if(cap)cap.textContent=caption||src||"";
  box.hidden=false;
}
function closeImageLightbox(){
  const box=document.getElementById("imgLightbox"),img=document.getElementById("imgLightboxImg");
  if(img)img.src="";
  if(box)box.hidden=true;
}
function lensAddQuestion(q){
  const m=document.getElementById("lensMsgs");const e=m.querySelector(".empty");if(e)e.remove();
  const d=E("div");d.className="lens-q";d.innerHTML='<span class="who">You</span>'+esc(q);m.appendChild(d);
  const a=E("div");a.className="lens-ans";a.innerHTML='<span class="who">Run Lens</span><div class="ansbody"><div class="lens-thinking">working…</div></div>';
  m.appendChild(a);m.scrollTop=m.scrollHeight;
  lensSaveConvo();
  return a.querySelector(".ansbody");
}
function lensRender(body,data){
  if(data.error){body.innerHTML='<div class="lens-thinking" style="color:var(--err)">'+esc(data.error)+'</div>';return;}
  const blocks=(data.turns||[]).flatMap(t=>t.blocks||[]);
  if(!blocks.length){body.innerHTML='<div class="lens-thinking">'+(data.running?'working…':'(no output)')+'</div>';return;}
  body.innerHTML="";body.appendChild(renderBlocks(blocks));
}
function lensStreamJob(job,body,workingMsg,onDone){
  const owner=state.lensRun;   // the run this job belongs to (chat may be switched away mid-flight)
  state.lensJob=job;lensStatus("reading the run…");
  if(owner){state.lensJobs[owner]=job;lensPersistConvos();}   // remember it so a refresh can reconnect
  const m=document.getElementById("lensMsgs");
  const es=new EventSource("/api/lens/stream?job="+encodeURIComponent(job));state.lensEs=es;
  es.onmessage=ev=>{let d;try{d=JSON.parse(ev.data);}catch(_){return;}
    const pinned=m.scrollHeight-m.scrollTop-m.clientHeight<120;
    lensRender(body,d);
    lensSaveConvo();
    if(pinned)m.scrollTop=m.scrollHeight;
    if(d.error||!d.running){
      es.close();state.lensEs=null;state.lensJob=null;
      if(owner){delete state.lensJobs[owner];lensPersistConvos();}   // finished: nothing left to resume
      lensBusy(false);lensStatus(d.error?"error":"done");if(onDone)onDone(!!d.error);
    }
    else lensStatus(workingMsg||"investigating…");
  };
  // The browser auto-reconnects an EventSource on transient drops (e.g. the tunnel
  // resetting a long-lived SSE), so we just keep the busy state and let it retry.
  es.onerror=()=>{lensStatus(workingMsg||"reconnecting…");};
}
// Reattach to a job that was still running when the chat was last left/refreshed.
function lensResumeIfRunning(id){
  const job=state.lensJobs&&state.lensJobs[id];
  if(!job||state.lensEs)return;
  const m=document.getElementById("lensMsgs"); if(!m)return;
  const bodies=m.querySelectorAll(".lens-ans .ansbody");
  const body=bodies.length?bodies[bodies.length-1]:null;
  if(!body){delete state.lensJobs[id];lensPersistConvos();return;}   // no answer slot to fill
  lensBusy(true);
  lensStreamJob(job,body);   // re-reads the job from disk; if already done, renders the final answer and clears it
}
// Stop streaming into the UI but leave the server job alive so we can resume later.
function lensDetach(){
  if(state.lensEs){state.lensEs.close();state.lensEs=null;}
  state.lensJob=null;
}
async function sendLens(){
  const inp=document.getElementById("lensInput");const q=inp.value.trim();
  if(!q){return;} if(!state.agentId){lensStatus("pick a run first");return;}
  state.lensRun=state.agentId;   // the chat being built belongs to the open run
  stopLens(true); inp.value="";
  const body=lensAddQuestion(q);
  lensBusy(true);lensStatus("starting Run Lens…");
  let res; try{res=await (await fetch("/api/lens/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:state.agentId,question:q})})).json();}catch(e){res={error:String(e)};}
  if(!res||res.error||!res.job){body.innerHTML='<div class="lens-thinking" style="color:var(--err)">'+esc((res&&res.error)||"failed to start")+'</div>';lensSaveConvo();lensBusy(false);lensStatus("error");return;}
  lensStreamJob(res.job,body);
}
function stopLens(quiet){   // explicit Stop / New chat: actually cancel the server job
  const job=state.lensJob||(state.lensRun&&state.lensJobs[state.lensRun]);
  if(state.lensEs){state.lensEs.close();state.lensEs=null;}
  state.lensJob=null;
  if(job)fetch("/api/lens/cancel",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({job:job})}).catch(()=>{});
  if(state.lensRun&&state.lensJobs[state.lensRun]){delete state.lensJobs[state.lensRun];}
  lensSaveConvo(false);
  lensBusy(false); if(!quiet)lensStatus("stopped");
}

// ---- Overview dashboard: status of every run + on-demand Run-Lens summaries ----
const SUMMARY_Q="Write a 2-4 sentence status update for a reader who knows this run's task and setup but has NOT followed what the run has done so far. Do not restate the proposal; instead give enough run-specific context that the current activity is self-explanatory: briefly what has already been accomplished, then what the agent is doing right now and why, and whether it is making progress or is stuck/erroring. Explain what key artifacts (files, commands, experiments, results) mean for the task rather than just naming them. Base it strictly on the run's transcripts and state files; output only the summary, with no preamble and no narration of your search.";
const sumId=p=>"sum-"+p.replace(/[^a-zA-Z0-9]/g,"_");
const SUMMARY_MAX=50;  // max parallel summary agents; server overrides via LENS_SUMMARY_CONCURRENCY
function showOverview(){
  state.view="overview"; state.agentId=null; location.hash="";
  closeStream();
  document.getElementById("title").textContent="Overview";
  const cl=document.getElementById("costlbl"); if(cl)cl.style.display="none";
  document.getElementById("sesstabs").innerHTML="";
  state.panes={}; state.paneAgent=null;
  document.getElementById("content").innerHTML=
    '<div class="dash"><div class="dash-head"><div class="dash-title">Runs <span id="dashCount"></span></div>'
    +'<div class="dash-actions"><button id="sumAllBtn" class="tbtn" title="Ask Run Lens for brief summaries of the visible tab">✦ Generate summaries</button>'
    +'<button id="sumStopBtn" class="tbtn" hidden>Stop</button></div></div>'
    +'<div id="phaseTabs" class="phase-tabs"></div>'
    +'<div id="dashGrid" class="dash-grid"><div class="loading-box" style="grid-column:1/-1"><div class="spinner"></div><div class="lmsg">Loading runs\u2026</div></div></div></div>';
  document.getElementById("sumAllBtn").onclick=summarizeAll;
  document.getElementById("sumStopBtn").onclick=stopSummaries;
  if(state.sumActive>0||(state.sumQueue&&state.sumQueue.length))document.getElementById("sumStopBtn").hidden=false;
  const ob=document.getElementById("overviewBtn"); if(ob)ob.classList.add("active");
  lensSetOpen(false);   // no specific run on the dashboard -> close + disable the lens
  renderTree(state.items); updateLensCtx();
  state.overviewSig=""; loadOverview();
}
async function loadOverview(){
  const res=await jget("/api/overview",true);
  if(!res||!res.runs)return;
  state.overview=res.runs;
  const sig=JSON.stringify(res.runs.map(r=>[r.path,r.phase,r.health,r.status,r.turns,r.sessions,r.lastActivity,r.heartbeatAt,r.cost,
    r.goal&&[r.goal.status,r.goal.tokensUsed],
    r.run_loop&&[r.run_loop.status,r.run_loop.segment,r.run_loop.phase,r.run_loop.stage,r.run_loop.completed]]));
  if(sig===state.overviewSig)return;            // nothing changed -> no DOM churn
  state.overviewSig=sig; renderOverview(res.runs);
}
function fmtAgo(ms){
  if(!ms)return "\u2014"; const s=Math.max(0,(Date.now()-ms)/1000);
  if(s<60)return Math.round(s)+"s ago"; if(s<3600)return Math.round(s/60)+"m ago";
  if(s<86400)return Math.round(s/3600)+"h ago"; return Math.round(s/86400)+"d ago";
}
function statusDot(r){
  const p=(r.phase||"").toLowerCase();
  if(p==="active")return '<span class="dot live"></span>';
  if(p==="failed")return '<span class="dot stale"></span>';
  return '<span class="dot done"></span>';
}
function statusTag(r){
  const p=r.phase||(/fail|error|stop|budget/i.test(r.status||"")?"Failed":"Completed");
  if(p==="Active")return '<span class="phasetag active">ACTIVE</span>';
  if(p==="Failed")return '<span class="phasetag failed">FAILED</span>';
  return '<span class="phasetag completed">COMPLETED</span>';
}
function runStatusLine(r){
  const b=[];
  if(r.cost!=null)b.push(`<b style="color:var(--ok)">$${Number(r.cost).toFixed(2)}</b>`);
  if(r.goal&&r.goal.tokensUsed!=null)b.push(`goal <b>${esc(r.goal.tokensUsed)} tok</b>`);
  if(r.run_loop){const rl=r.run_loop;b.push(`S${rl.segment}P${rl.phase} ${esc(rl.stage||"")} \u00b7 ${rl.completed} done`);}
  b.push(`<b>${r.sessions}</b> sess \u00b7 <b>${r.turns}</b> turns`);
  b.push(`activity ${fmtAgo(r.lastActivity)}`);
  if(r.marker&&r.heartbeatAt)b.push(`heartbeat ${fmtAgo(r.heartbeatAt)}`);
  return b.join(" \u00b7 ");
}
function summaryHTML(path){
  const s=state.summaries[path];
  if(!s)return '<span class="ph">No summary yet \u2014 click Summarize.</span>';
  if(s.status==="queued")return '<span class="ph">queued\u2026</span>';
  if(s.status==="running")return (s.text?md(s.text):'')+'<span class="working"> \u2026working</span>';
  if(s.status==="error")return '<span class="err">'+esc(s.text||"error")+'</span>';
  return s.text?md(s.text):'<span class="ph">(no summary)</span>';
}
function updateSummaryCard(path){const el=document.getElementById(sumId(path));if(el)el.innerHTML=summaryHTML(path);}
function phaseCounts(runs){
  const counts={Active:0,Failed:0,Completed:0};
  for(const r of runs){if(counts[r.phase]!=null)counts[r.phase]++;}
  return counts;
}
function choosePhase(runs){
  const counts=phaseCounts(runs);
  const cur=state.dashPhase;
  if(cur&&counts[cur]>0)return cur;
  if(counts.Active>0)return "Active";
  if(counts.Failed>0)return "Failed";
  return "Completed";
}
function renderPhaseTabs(runs){
  const tabs=document.getElementById("phaseTabs"); if(!tabs)return;
  const counts=phaseCounts(runs);
  const selected=state.dashPhase=choosePhase(runs);
  localStorage.setItem("av.dashPhase",selected);
  tabs.innerHTML="";
  for(const phase of ["Active","Failed","Completed"]){
    const b=E("button"); b.className="phase-tab"+(phase===selected?" active":"");
    b.innerHTML=`${esc(phase)} <span class="num">${counts[phase]||0}</span>`;
    b.onclick=()=>{state.dashPhase=phase;localStorage.setItem("av.dashPhase",phase);renderOverview(state.overview||[]);};
    tabs.appendChild(b);
  }
}
function renderOverview(runs){
  const grid=document.getElementById("dashGrid"); if(!grid)return;
  renderPhaseTabs(runs);
  const shown=runs.filter(r=>r.phase===state.dashPhase);
  const c=document.getElementById("dashCount"); if(c)c.textContent=`(${shown.length} of ${runs.length})`;
  grid.innerHTML="";
  if(!runs.length){grid.innerHTML='<div class="empty">No runs found under outputs/.</div>';return;}
  if(!shown.length){grid.innerHTML='<div class="empty">No '+esc(state.dashPhase).toLowerCase()+' runs.</div>';return;}
  let curGroup=null;
  for(const r of shown){
    if((r.group||"")!==curGroup){curGroup=r.group||"";const g=E("div");g.className="dgroup";g.textContent=curGroup||"runs";grid.appendChild(g);}
    const card=E("div");card.className="card";
    const dot=statusDot(r);
    const tag=statusTag(r);
    card.innerHTML=`<div class="card-top">${dot}<span class="card-name">${esc(r.name)}</span>`
      +`${r.mode?`<span class="badge">${esc(r.mode)}</span>`:""}${tag}</div>`
      +`<div class="card-meta">${runStatusLine(r)}</div>`
      +`<div class="card-sum" id="${sumId(r.path)}">${summaryHTML(r.path)}</div>`
      +`<div class="card-actions"><button class="mini" data-act="sum">\u2726 Summarize</button><button class="mini" data-act="open">Open \u2192</button></div>`;
    card.querySelector('[data-act="open"]').onclick=ev=>{ev.stopPropagation();selectRun(r.path);};
    card.querySelector('[data-act="sum"]').onclick=ev=>{ev.stopPropagation();summarizeOne(r.path);};
    card.addEventListener("click",()=>selectRun(r.path));
    grid.appendChild(card);
  }
}
function summarizeAll(){
  const runs=(state.overview||[]).filter(r=>r.phase===state.dashPhase); if(!runs.length)return;
  state.sumQueue=state.sumQueue||[];
  for(const r of runs){const s=state.summaries[r.path];
    if(s&&(s.status==="running"||s.status==="queued"))continue;
    state.summaries[r.path]={status:"queued",text:""}; updateSummaryCard(r.path); state.sumQueue.push(r.path);}
  const b=document.getElementById("sumStopBtn"); if(b)b.hidden=false;
  pumpSummaries();
}
function summarizeOne(path){
  state.sumQueue=state.sumQueue||[];
  const cur=state.summaries[path];
  if(cur&&(cur.status==="running"||cur.status==="queued"))return;
  state.summaries[path]={status:"queued",text:""}; updateSummaryCard(path);
  state.sumQueue.push(path); const b=document.getElementById("sumStopBtn"); if(b)b.hidden=false; pumpSummaries();
}
function pumpSummaries(){
  while(state.sumActive<SUMMARY_MAX && state.sumQueue && state.sumQueue.length){ startSummary(state.sumQueue.shift()); }
  if((!state.sumQueue||!state.sumQueue.length)&&state.sumActive===0){const b=document.getElementById("sumStopBtn");if(b)b.hidden=true;}
}
async function startSummary(path){
  const s=state.summaries[path]||(state.summaries[path]={status:"queued",text:""});
  s.status="running"; s.text=""; updateSummaryCard(path); state.sumActive++;
  let res; try{res=await (await fetch("/api/lens/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:path,question:SUMMARY_Q})})).json();}catch(e){res={error:String(e)};}
  if(!res||res.error||!res.job){s.status="error";s.text=(res&&res.error)||"failed to start";updateSummaryCard(path);state.sumActive--;pumpSummaries();return;}
  s.job=res.job; updateSummaryCard(path); ensureSummaryPoller();
}
// One shared poll loop reports progress for ALL running summary jobs in a single
// request, so the fan-out scales past the browser's ~6-connections-per-host limit
// to dozens/hundreds of parallel summaries (one EventSource each would not).
function ensureSummaryPoller(){
  if(state.sumPoll)return;
  state.sumPoll=setInterval(pollSummaries,1200); pollSummaries();
}
async function pollSummaries(){
  const entries=Object.entries(state.summaries).filter(([p,s])=>s.job&&s.status==="running");
  if(!entries.length){clearInterval(state.sumPoll);state.sumPoll=null;return;}
  const jobs=[...new Set(entries.map(([p,s])=>s.job))];
  const res=await jget("/api/lens/poll?jobs="+encodeURIComponent(jobs.join(",")),true);
  if(!res||!res.jobs)return;
  for(const [p,s] of entries){
    const d=res.jobs[s.job]; if(!d)continue;
    if(d.error){s.status="error";s.text=d.error;}
    else if(d.text)s.text=d.text;
    if(d.error||!d.running){ if(s.status!=="error")s.status="done"; s.job=null; state.sumActive--; pumpSummaries(); }
    updateSummaryCard(p);
  }
}
function stopSummaries(){
  state.sumQueue=[];
  if(state.sumPoll){clearInterval(state.sumPoll);state.sumPoll=null;}
  for(const p in state.summaries){const s=state.summaries[p];
    if(s.job){fetch("/api/lens/cancel",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({job:s.job})}).catch(()=>{});s.job=null;}
    if(s.status==="running"||s.status==="queued"){s.status="done";if(!s.text)s.text="(stopped)";updateSummaryCard(p);}}
  state.sumActive=0; const b=document.getElementById("sumStopBtn"); if(b)b.hidden=true;
}

// Pick the most useful session tab when a run is first opened: the execution
// (main) session once it has content, else whichever session does (e.g. the
// planner while planning is still in progress).
function defaultSess(data){
  const ss=data.sessions||[];
  const mi=ss.findIndex(s=>s.name==="main" && (s.turns||[]).length);   // goal: the Worker
  if(mi>=0)return mi;
  for(let i=ss.length-1;i>=0;i--){ if((ss[i].turns||[]).length) return i; }  // else most recent active phase
  return 0;
}

// Draggable sidebar width, persisted across sessions.
function initResizer(){
  const r=document.getElementById("resizer");if(!r||r._wired)return;r._wired=true;
  const saved=parseInt(localStorage.getItem("av.sidebarW")||"",10);
  if(saved>=180&&saved<=720)document.documentElement.style.setProperty("--sidebar-w",saved+"px");
  let dragging=false;
  const move=e=>{ if(!dragging)return; const w=Math.min(720,Math.max(180,e.clientX));
    document.documentElement.style.setProperty("--sidebar-w",w+"px"); };
  const up=()=>{ if(!dragging)return; dragging=false; r.classList.remove("active");
    document.body.style.userSelect=""; const w=getComputedStyle(document.documentElement).getPropertyValue("--sidebar-w").trim();
    localStorage.setItem("av.sidebarW",parseInt(w,10)||300); };
  r.addEventListener("mousedown",e=>{dragging=true;r.classList.add("active");document.body.style.userSelect="none";e.preventDefault();});
  window.addEventListener("mousemove",move); window.addEventListener("mouseup",up);
}
// Draggable Run Lens width (it's docked on the right), persisted like the sidebar.
function initLensResizer(){
  const r=document.getElementById("lensResizer");if(!r||r._wired)return;r._wired=true;
  const saved=parseInt(localStorage.getItem("av.lensW")||"",10);
  if(saved>=280&&saved<=760)document.documentElement.style.setProperty("--lens-w",saved+"px");
  let dragging=false;
  const move=e=>{ if(!dragging)return; const w=Math.min(760,Math.max(280,window.innerWidth-e.clientX));
    document.documentElement.style.setProperty("--lens-w",w+"px"); };
  const up=()=>{ if(!dragging)return; dragging=false; r.classList.remove("active");
    document.body.style.userSelect=""; const w=getComputedStyle(document.documentElement).getPropertyValue("--lens-w").trim();
    localStorage.setItem("av.lensW",parseInt(w,10)||420); };
  r.addEventListener("mousedown",e=>{dragging=true;r.classList.add("active");document.body.style.userSelect="none";e.preventDefault();});
  window.addEventListener("mousemove",move); window.addEventListener("mouseup",up);
}
function _initFilter(){
  const inp=document.getElementById("filter");
  if(inp && !inp._wired){ inp._wired=true; inp.addEventListener("input",()=>{state.filter=inp.value;renderTree(state.items);}); }
  const rb=document.getElementById("refresh");
  if(rb && !rb._wired){ rb._wired=true; rb.onclick=()=>loadDir(state.path); }
}

// A collapsed <details> whose (potentially heavy) inner content is built only
// the first time it's expanded. Most thinking/tool/subagent blocks stay
// collapsed, so the initial render of a big transcript stays cheap.
function lazyDetails(cls,summaryHTML,buildInner){
  const d=E("details");d.className=cls;
  const s=E("summary");s.innerHTML=summaryHTML;d.appendChild(s);
  const inner=E("div");inner.className="inner";d.appendChild(inner);
  let built=false;
  d.addEventListener("toggle",()=>{ if(d.open&&!built){built=true;inner.innerHTML=buildInner();} });
  return d;
}
function toolTag(r){return r?(r.isError?'<span class="tag err">error</span>':'<span class="tag ok">done</span>'):'<span class="tag">running…</span>';}
function renderBlocks(blocks){
  const frag=document.createDocumentFragment();
  for(const bl of blocks){
    if(bl.kind==="text"){const d=E("div");d.className="block md";d.innerHTML=md(bl.text);frag.appendChild(d);}
    else if(bl.kind==="thinking"){
      frag.appendChild(lazyDetails("think","thinking",()=>`<div class="md">${md(bl.text)}</div>`));
    }
    else if(bl.kind==="tool"){
      const r=bl.result, args=typeof bl.args==="string"?bl.args:JSON.stringify(bl.args,null,2);
      frag.appendChild(lazyDetails("tool",`<span class="k">tool</span> ${esc(bl.name)} ${toolTag(r)}`,
        ()=>`<pre>${esc(args)}</pre>${r?`<pre>${esc(r.text||"")}</pre>`:""}`));
    }
    else if(bl.kind==="subagent"){
      const r=bl.result;
      frag.appendChild(lazyDetails("sub",`<span class="k">subagent</span> ${esc(bl.agent)} ${toolTag(r)}`,
        ()=>`<div class="md">${md(bl.task)}</div>${r?`<pre>${esc(r.text||"")}</pre>`:""}`));
    }
  }
  return frag;
}

function turnNode(t){
  const d=E("div");d.className="turn "+t.role;
  const head=E("div");head.className="role";head.textContent=t.role;
  const body=E("div");body.className="body";body.appendChild(renderBlocks(t.blocks));
  d.appendChild(head);d.appendChild(body);return d;
}

// ---- Per-tab cached panes: each session renders into its own container once,
// then incremental updates only touch new/changed turns, and switching tabs is
// just a CSS show/hide. This keeps tab switching instant even for big runs. ----
function ensurePane(name){
  let ps=state.panes[name];
  if(ps)return ps;
  const el=E("div");el.className="sess-pane";el.style.display="none";
  document.getElementById("content").appendChild(el);
  ps={el,count:0,sig:null,scroll:0};state.panes[name]=ps;return ps;
}
function showPane(name){
  for(const k in state.panes)state.panes[k].el.style.display=(k===name)?"block":"none";
}
// Incrementally bring a pane's DOM up to date with its session's turns.
function renderPane(ps,turns){
  const el=ps.el; turns=turns||[];
  if(turns.length<ps.count){ el.innerHTML=""; ps.count=0; ps.sig=null; }   // shrank -> rebuild
  if(ps.count===0){ const e=el.querySelector(".empty"); if(e)e.remove(); }
  if(!turns.length){ if(!el.firstChild)el.innerHTML='<div class="empty">No messages yet…</div>'; return; }
  if(ps.count>0 && turnSig(turns[ps.count-1])!==ps.sig){   // streaming last turn moved
    const nodes=el.querySelectorAll(".turn");
    if(nodes[ps.count-1])nodes[ps.count-1].replaceWith(turnNode(turns[ps.count-1]));
  }
  for(let i=ps.count;i<turns.length;i++)el.appendChild(turnNode(turns[i]));
  ps.count=turns.length;
  ps.sig=ps.count?turnSig(turns[ps.count-1]):null;
}

// Fingerprint of the streaming (last) turn so we only re-render it when it moves.
function turnSig(t){
  if(!t||!t.blocks||!t.blocks.length)return "0";
  const b=t.blocks[t.blocks.length-1];
  const al=b.args?(typeof b.args==="string"?b.args.length:JSON.stringify(b.args).length):0;
  const rl=b.result?((b.result.text||"").length+(b.result.isError?"e":"")):"";
  return t.blocks.length+":"+b.kind+":"+((b.text||b.task||"").length)+":"+al+":"+rl;
}

function nearBottom(el){return el.scrollHeight-el.scrollTop-el.clientHeight<140;}

function renderHeader(data){
  document.getElementById("title").textContent=data.id||"";
  const cl=document.getElementById("costlbl");
  if(cl){ if(data.cost!=null){cl.style.display="";cl.textContent="$"+Number(data.cost).toFixed(2);} else cl.style.display="none"; }
}

// Collapsed by default once a run has enough phases to wrap the header into many
// rows; an explicit user choice (stored) always wins. tabsCollapsed: true/false
// = explicit, null = auto.
function tabsAreCollapsed(grouped,n){
  if(state.tabsCollapsed!==null)return state.tabsCollapsed;
  return grouped&&n>6;
}
function toggleTabs(){
  const sessions=(state.data&&state.data.sessions)||[];
  const grouped=sessions.some(s=>s.seg!=null);
  state.tabsCollapsed=!tabsAreCollapsed(grouped,sessions.length);
  localStorage.setItem("av.tabsCollapsed",state.tabsCollapsed?"1":"0");
  renderTabs(state.data);
}
function renderTabs(data){
  const tabs=document.getElementById("sesstabs");
  const prevScroll=tabs.scrollTop;          // survive the innerHTML rebuild on each poll tick
  tabs.innerHTML="";
  const sessions=data.sessions||[];
  const tgl=document.getElementById("tabsToggle");
  if(sessions.length<=1){tabs.style.display="none";if(tgl)tgl.style.display="none";return;}
  tabs.style.display="";
  const grouped=sessions.some(s=>s.seg!=null);   // only multi_phase runs get phase rows
  const collapsed=tabsAreCollapsed(grouped,sessions.length);
  if(tgl){tgl.style.display="";tgl.textContent=collapsed?"▸ phases":"▾ phases";
    tgl.title=collapsed?"Show the phase tabs":"Hide the phase tabs";}
  if(collapsed){   // show only the current selection + an expander, reclaiming the header
    tabs.classList.add("collapsed");
    const s=sessions[state.sess]||sessions[0];
    const where=(s.seg!=null)?`S${s.seg}·P${s.phase}${s.cont?` cont ${s.cont}`:""} · `:"";
    const b=E("button");b.className="sesstab active";
    b.innerHTML=`${esc(where)}${esc(s.label||s.name)}<span class="tc">${(s.turns||[]).length}</span>`;
    b.title="Current session — click to show all phase tabs";b.onclick=toggleTabs;
    tabs.appendChild(b);
    const more=E("span");more.className="tabgroup";more.style.cursor="pointer";
    more.textContent=`+${sessions.length-1} more`;more.title="Show all phase tabs";more.onclick=toggleTabs;
    tabs.appendChild(more);
    return;
  }
  tabs.classList.remove("collapsed");
  let curGroup=null;
  sessions.forEach((s,i)=>{
    const g=s.group||"";
    if(grouped&&g!==curGroup){    // each phase starts on its own row, led by a phase chip
      if(curGroup!==null){const br=E("span");br.className="tabbreak";tabs.appendChild(br);}
      curGroup=g;
      const gl=E("span");gl.className="tabgroup";
      gl.textContent=(s.seg!=null)?`S${s.seg}\u00b7P${s.phase}${s.cont?` \u21bb cont ${s.cont}`:""}`:g;
      gl.title=g;
      tabs.appendChild(gl);
    }
    const b=E("button");b.className="sesstab"+(i===state.sess?" active":"");
    b.innerHTML=`${esc(s.label||s.name)}<span class="tc">${s.turns.length}</span>`;
    b.title=g+" \u2014 "+(s.label||s.name);
    b.onclick=()=>selectSession(i);
    tabs.appendChild(b);
  });
  tabs.scrollTop=prevScroll;
  // Fresh expansion (no prior scroll): bring the selected phase into view.
  if(prevScroll===0){
    const act=tabs.querySelector(".sesstab.active");
    if(act)act.scrollIntoView({block:"nearest"});
  }
}

function applyTranscript(data){
  if(!data)return;
  state.data=data;
  const content=document.getElementById("content");
  if(data.error){content.innerHTML='<div class="empty">'+esc(data.error)+'</div>';return;}
  // New agent -> drop all cached panes and start fresh.
  if(state.paneAgent!==data.id){ content.innerHTML=""; state.panes={}; state.paneAgent=data.id; }
  if(state._pickDefault){ state.sess=defaultSess(data); state._pickDefault=false; }
  renderHeader(data);renderTabs(data);
  const sessions=data.sessions||[];
  if(state.sess>=sessions.length)state.sess=0;
  const active=sessions[state.sess]||{name:"main",turns:[]};
  const scroller=document.querySelector(".main");
  const pinned=nearBottom(scroller);
  const ps=ensurePane(active.name);
  renderPane(ps,active.turns);   // only the visible tab is updated each tick
  showPane(active.name);
  if(pinned)scroller.scrollTop=scroller.scrollHeight;
}

// Tab switch: show the cached pane (creating + catching it up only if needed).
// No full re-render -> effectively instant.
function selectSession(i){
  const scroller=document.querySelector(".main");
  const sessions=(state.data&&state.data.sessions)||[];
  const cur=sessions[state.sess];
  if(cur&&state.panes[cur.name])state.panes[cur.name].scroll=scroller.scrollTop;  // remember where we were
  state.sess=i;
  renderTabs(state.data);
  const active=sessions[i];
  if(!active)return;
  const ps=ensurePane(active.name);
  renderPane(ps,active.turns);
  showPane(active.name);
  scroller.scrollTop=ps.scroll||0;   // land at the top of a freshly-opened tab
}

// Stream the selected agent's transcript over SSE (server pushes on change).
function closeStream(){ if(state.es){state.es.close();state.es=null;} }
function openStream(){
  closeStream();
  if(!state.agentId)return;
  jget("/api/agent?id="+encodeURIComponent(state.agentId)).then(d=>{if(d&&d.id===state.agentId)applyTranscript(d);});
  if(!document.getElementById("autorefresh").checked)return;   // streaming paused
  const es=new EventSource("/api/stream?id="+encodeURIComponent(state.agentId));
  es.onmessage=e=>{try{applyTranscript(JSON.parse(e.data));}catch(_){}};
  es.onerror=()=>{};                   // browser auto-reconnects; ignore blips
  state.es=es;
}

if(location.hash.length>1){state.agentId=decodeURIComponent(location.hash.slice(1));}
_initFilter();initResizer();initLensResizer();
function activePane(){const s=((state.data&&state.data.sessions)||[])[state.sess];return s?state.panes[s.name]:null;}
function setAllDetails(open){const p=activePane();if(p)p.el.querySelectorAll("details").forEach(d=>{d.open=open;});}
let _allOpen=false;
document.getElementById("toggleAll").onclick=()=>{_allOpen=!_allOpen;setAllDetails(_allOpen);document.getElementById("toggleAll").textContent=_allOpen?"collapse":"expand";};
document.getElementById("tabsToggle").onclick=toggleTabs;
document.getElementById("lensBtn").onclick=()=>lensSetOpen(!state.lensOpen,true);
document.getElementById("lensClose").onclick=()=>lensSetOpen(false);
document.getElementById("lensNew").onclick=lensNewChat;
document.getElementById("overviewBtn").onclick=showOverview;

function toast(m){const t=document.getElementById("toast");if(!t)return;t.textContent=m;
  t.classList.add("show");clearTimeout(toast._t);toast._t=setTimeout(()=>t.classList.remove("show"),3800);}

// ---- launch-a-run dialog ----
async function openLauncher(){
  const el=document.getElementById("launcher");
  if(!el.hidden){el.hidden=true;return;}
  el.hidden=false;
  document.getElementById("launchList").innerHTML='<div class="lsub">loading proposals…</div>';
  const d=await jget("/api/launch/options",true);
  if(!d){document.getElementById("launchList").innerHTML='<div class="lsub">failed to load proposals</div>';return;}
  document.getElementById("launchList").innerHTML=d.proposals.map(p=>{
    const btns=d.modes.map(m=>`<button class="lmode" data-p="${esc(p.name)}" data-m="${m}"`
      +`${p.existing[m]?' disabled title="this run already exists"':''}>${m}</button>`).join("");
    return `<div class="lrow"><span class="lname" title="${esc(p.name)}">${esc(p.name)}</span>${btns}</div>`;
  }).join("")||'<div class="lsub">no proposals found</div>';
  el.querySelectorAll(".lmode:not([disabled])").forEach(b=>b.onclick=()=>launchRun(b.dataset.p,b.dataset.m));
}
async function launchRun(p,m){
  if(!confirm(`Launch ${p} in ${m} mode?\n\nThis starts a real, long-running (and expensive) agent run in a tmux session.`))return;
  let r,d;
  try{
    r=await fetch("/api/launch",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({proposal:p,mode:m})});
    d=await r.json();
  }catch(e){toast("launch failed: "+e.message);return;}
  if(!r.ok){toast(d.error||"launch failed");return;}
  document.getElementById("launcher").hidden=true;
  toast(`Launched in tmux session ${d.session} — it appears under Active once it starts writing`);
  showOverview();
}
document.getElementById("launchBtn").onclick=openLauncher;
document.getElementById("launchClose").onclick=()=>document.getElementById("launcher").hidden=true;

// ---- project panel: feedback / resume / continue for the open run ----
async function openProject(){
  const el=document.getElementById("projpanel");
  const back=document.getElementById("ppBack");
  if(!el.hidden){el.hidden=true;back.hidden=true;return;}
  if(!state.agentId) return;
  el.hidden=false;back.hidden=false;
  document.getElementById("ppName").textContent=state.agentId.split("/").pop();
  document.getElementById("ppStatus").textContent="loading…";
  const d=await jget("/api/project?run="+encodeURIComponent(state.agentId),true);
  if(!d||d.error){document.getElementById("ppStatus").textContent=(d&&d.error)||"failed to load";return;}
  const hb=d.heartbeat||{}, rl=d.run_loop||{};
  const cls=d.phase==="Failed"?"bad":(d.phase==="Active"?"good":"");
  let rows=[`state: <b class="${cls}">${esc(d.phase||"?")}</b>`];
  if(hb.status) rows.push(`heartbeat: ${esc(hb.status)}${hb.age_s!=null?` (${hb.age_s<120?hb.age_s+"s":Math.round(hb.age_s/60)+"min"} ago)`:""}`);
  if(rl.status) rows.push(`run loop: ${esc(rl.status)} — segment ${rl.segment??"?"}, stage ${esc(rl.stage||"?")}`);
  if(rl.error) rows.push(`<span class="bad">error: ${esc(String(rl.error)).slice(0,300)}</span>`);
  if(d.last_returncode!=null){
    const rc=d.last_returncode;
    rows.push(`last exit: ${rc}${rc<0?` <span class="bad">(killed by signal ${-rc})</span>`:""}`);
  }
  document.getElementById("ppStatus").innerHTML=rows.join("<br>");
  document.getElementById("ppResume").hidden = d.phase!=="Failed";
  // ppContinued: runs continued from this tab. The launch takes a few seconds to
  // produce a heartbeat, during which the run still reads "Completed" — keep the
  // button hidden so the launch visibly "took" and can't be double-fired.
  document.getElementById("ppContinue").hidden = !(d.phase==="Completed" && d.mode==="multi_phase") || ppContinued.has(state.agentId);
  const fb=document.getElementById("ppFb");
  fb.innerHTML=(d.feedback||[]).map(f=>
    `<div class="fbitem"><span class="fbdate">${esc(f.file)}</span>\n${esc(f.text)}</div>`).join("")
    ||'<div class="fbitem" style="border-color:transparent">no feedback saved yet</div>';
}
async function ppPost(url,body,confirmMsg){
  if(confirmMsg && !confirm(confirmMsg)) return null;
  let r,d;
  try{
    r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    d=await r.json();
  }catch(e){toast("failed: "+e.message);return null;}
  if(!r.ok){toast(d.error||"failed");return null;}
  return d;
}
const ppContinued=new Set();
document.getElementById("projBtn").onclick=openProject;
function ppHide(){document.getElementById("projpanel").hidden=true;document.getElementById("ppBack").hidden=true;}
document.getElementById("ppClose").onclick=ppHide;
document.getElementById("ppBack").onclick=ppHide;
document.getElementById("ppSave").onclick=async()=>{
  const t=document.getElementById("ppText").value;
  const d=await ppPost("/api/feedback",{run:state.agentId,text:t});
  if(d){document.getElementById("ppText").value="";openProject();openProject();}
};
document.getElementById("ppResume").onclick=async()=>{
  const d=await ppPost("/api/resume",{run:state.agentId},
    "Resume this run (relaunch with --resume in its tmux session)?");
  if(d) toast(`Resuming in tmux session ${d.session} — Active once the heartbeat returns`);
};
document.getElementById("ppContinue").onclick=async()=>{
  const t=document.getElementById("ppText").value.trim();
  if(!t){toast("Write the continuation instructions in the feedback box first");return;}
  const d=await ppPost("/api/continue",{run:state.agentId,text:t},
    "Continue this COMPLETED run with the feedback above as its new instructions?\n\nThis starts a real, long-running (and expensive) agent run.");
  if(d){
    ppContinued.add(state.agentId);
    document.getElementById("ppText").value="";
    document.getElementById("ppContinue").hidden=true;
    openProject();openProject();   // close + reopen = refetch the panel status
    toast(`Continuation launched in tmux session ${d.session} (feedback saved to ${d.feedback})`);
  }
};

if(state.agentId)lensSwitchTo(state.agentId);
lensSetOpen(true,false);   // open the lens iff a run is deep-linked; otherwise it stays closed/disabled
document.getElementById("lensSend").onclick=sendLens;
document.getElementById("lensStop").onclick=()=>stopLens();
document.getElementById("lensInput").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendLens();}});
window.addEventListener("beforeunload",()=>lensSaveConvo(false));
// Returning to a backgrounded tab whose SSE the tunnel dropped: re-attach to the running job.
document.addEventListener("visibilitychange",()=>{
  if(document.visibilityState==="visible"&&state.lensRun&&!state.lensEs)lensResumeIfRunning(state.lensRun);
});
document.addEventListener("click",e=>{
  const img=e.target&&e.target.closest?e.target.closest(".md-img"):null;
  if(img){
    e.preventDefault();
    openImageLightbox(img.currentSrc||img.src,img.getAttribute("alt")||"");
  }
});
document.getElementById("imgLightbox").addEventListener("click",e=>{if(e.target.id==="imgLightbox")closeImageLightbox();});
document.getElementById("imgLightboxClose").onclick=closeImageLightbox;
// Keyboard: 1-9 jump to a session tab, [ / ] cycle prev/next.
document.addEventListener("keydown",e=>{
  if(e.key==="Escape"){closeImageLightbox();return;}
  if(/^(input|textarea)$/i.test(e.target.tagName||"")||e.metaKey||e.ctrlKey||e.altKey)return;
  const n=((state.data&&state.data.sessions)||[]).length; if(!n)return;
  if(e.key>="1"&&e.key<="9"){const i=+e.key-1; if(i<n)selectSession(i);}
  else if(e.key==="[")selectSession((state.sess-1+n)%n);
  else if(e.key==="]")selectSession((state.sess+1)%n);
});
document.getElementById("autorefresh").addEventListener("change",openStream); // toggle live stream
// Open the folder containing a deep-linked run (if any), else the root.
const startDir=(state.agentId&&state.agentId.includes("/"))?state.agentId.split("/").slice(0,-1).join("/"):"";
state._pickDefault=!!state.agentId;
loadDir(startDir).then(()=>{ if(state.agentId){state.view="run";showContentLoading(state.agentId);openStream();} else showOverview(); });
setInterval(()=>{ refreshDir(); if(state.view==="overview")loadOverview(); },3000);   // dir listing + dashboard refresh; run transcripts arrive via SSE
</script>
<div class="toast" id="toast"></div>
</body></html>
"""

INDEX_HTML = INDEX_HTML.replace("/*__PALETTE__*/", PALETTE_CSS)
INDEX_HTML = INDEX_HTML.replace(
    "const SUMMARY_MAX=50;", f"const SUMMARY_MAX={LENS_SUMMARY_CONCURRENCY};"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live pi agent viewer (reads run dirs under outputs/)."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to bind. Default 0 = a random free port chosen at startup.",
    )
    parser.add_argument("--open", action="store_true", help="Open a browser tab.")
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Audit saved on-disk transcripts (planner/goal/ryan-loop stages) and exit.",
    )
    args = parser.parse_args()

    if args.audit:
        rows = audit_disk_transcripts()
        if not rows:
            print("No saved transcripts found under outputs/.")
            return
        print(f"Audited {len(rows)} transcript(s):\n")
        for r in rows:
            print(f"- {r['path']}")
            print(f"    planner mode : {'yes' if r['planner_mode'] else 'no'}")
            print(f"    goal mode    : {'yes' if r['goal_mode'] else 'no'}")
            rl = (
                f"yes ({r['completed_phases']} phase(s) complete; stages: {', '.join(r['ryan_loop_stages']) or 'none'})"
                if r["run_loop"]
                else "no"
            )
            print(f"    ryan-loop    : {rl}")
        return

    # port 0 -> OS assigns a free (effectively random) port, avoiding clashes
    # with stale/other viewers. We read back the actual port for the URL.
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    actual_port = server.server_address[1]
    url = f"http://{args.host}:{actual_port}"
    print(
        f"Agent viewer on {url}  ·  studio on {url}/studio  ·  proposals on {url}/proposals  (Ctrl-C to stop)",
        flush=True,
    )
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
