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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src import DEFAULT_MODEL, sandbox
from src.runner_utils import parse_env_text
from src.theme import PALETTE_CSS

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = ROOT / "outputs"

# Runs live directly on disk under outputs/<...>/<proposal>/<mode>/agent_N/. A run
# is "live" while its .pi_transcripts/RUNNING marker exists (written by the
# sandbox runner for the duration of the run); otherwise it's a finished record.
MODES = ("goal", "multi_phase")
RUNNING_MARKER = "RUNNING"


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


def _run_dirs_under(d: Path) -> set:
    """All run directories at or below ``d`` (a run dir has a .pi_transcripts)."""
    found = set()
    for t in d.glob("**/.pi_transcripts"):
        rd = t.parent
        if _is_run_dir(rd):
            found.add(rd)
    return found


def _mtime(d: Path) -> float:
    for c in (d / ".pi_transcripts" / "session.jsonl", d):
        try:
            return c.stat().st_mtime
        except OSError:
            pass
    return 0.0


def _run_item(d: Path, rel: str) -> dict:
    tdir = d / ".pi_transcripts"
    live = (tdir / RUNNING_MARKER).exists()
    status = None
    manifest = tdir / "manifest.json"
    if manifest.exists():
        try:
            status = json.loads(manifest.read_text()).get("status")
        except (json.JSONDecodeError, OSError):
            status = None
    return {
        "name": d.name,
        "path": rel,
        "type": "run",
        "mode": _mode_from_name(d.name),
        "live": live,
        "status": "running" if live else (status or "done"),
        "mtime": _mtime(d),
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
                    "live": any(
                        (r / ".pi_transcripts" / RUNNING_MARKER).exists() for r in runs
                    ),
                    "mtime": max((_mtime(r) for r in runs), default=_mtime(child)),
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
    raw = [("main", main["turns"])]
    if planner is not None:
        raw.append(("planner", planner["turns"]))
    for nm, p in sub_parsed:
        raw.append((nm, p["turns"]))
    total_cost = (
        main.get("cost", 0.0)
        + (planner.get("cost", 0.0) if planner else 0.0)
        + sum(p.get("cost", 0.0) for _, p in sub_parsed)
    )
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
    # Order by when each session actually ran; the heuristic order only breaks
    # ties / places not-yet-started (timestamp-less) sessions last.
    sessions.sort(key=lambda s: (s["ts"] is None, s["ts"] or 0.0, s["_ord"]))
    for s in sessions:
        s.pop("_ord", None)
    if mode == "multi_phase":
        # The run-loop orchestrator + its planner (the "Execution" group) add
        # little beyond the per-phase tabs, so hide them for multi_phase runs;
        # the planner tab and each phase's worker/reviewer/phase-planner remain.
        sessions = [s for s in sessions if s["group"] != "Execution"]
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

    Finished runs have them folded into ``run_loop_sessions/``. Live runs don't
    yet, so fall back to reading them in place from the agent's HOME (under the
    run dir at ``.home/.pi``) using the paths recorded in RUN_LOOP_STATE.json.
    """
    sub_dir = tdir / "run_loop_sessions"
    if sub_dir.is_dir():
        files = sorted(sub_dir.glob("*.jsonl"))
        if files:
            return [
                (f.stem.replace("_", " "), f.read_text(errors="replace")) for f in files
            ]
    out: list = []
    rl = _run_loop_summary(rl_text)
    if rl and rl.get("sessions"):
        for sub in _run_loop_session_files(rl["sessions"]):
            host = sandbox.session_host_path(sub["path"], base)
            if host and host.exists():
                out.append((sub["name"], host.read_text(errors="replace")))
    return out


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
    if sub_dir.is_dir():
        candidates += sorted(sub_dir.glob("*.jsonl"))
    else:  # live multi_phase: sub-agent sessions still live in the agent's HOME
        home_pi = base / ".home" / ".pi"
        if home_pi.is_dir():
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
        item = _run_item(base, rel)
        data = _transcript_disk(rel)
        sessions = data.get("sessions") or []
        item["sessions"] = len(sessions)
        item["turns"] = sum(len(s.get("turns") or []) for s in sessions)
        ts_vals = [
            s.get("ts") for s in sessions if isinstance(s.get("ts"), (int, float))
        ]
        item["lastActivity"] = max(ts_vals) if ts_vals else None
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
    out.sort(key=lambda x: (not x.get("live"), -(x.get("mtime") or 0.0)))
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
LENS_MODEL = os.environ.get("LENS_MODEL", DEFAULT_MODEL)
LENS_THINKING = os.environ.get("LENS_THINKING", "medium")
# The write-up meta-agent reads more and reasons harder than a quick Q&A, so it
# defaults to a higher thinking level (override via env).
WRITEUP_THINKING = os.environ.get("LENS_WRITEUP_THINKING", "high")
# Max number of Run-Lens summary agents the dashboard's "Generate summaries"
# fan-out runs at once (also injected as the client-side cap). Each one is a full
# model call, so this is the main throughput/cost knob; override via env.
# Default kept conservative because each agent is a full Opus call and many at
# once (alongside the real runs) can OOM the box (the killed-rc=-9 symptom);
# raise it via env if the machine has headroom (e.g. =50).
LENS_SUMMARY_CONCURRENCY = max(1, int(os.environ.get("LENS_SUMMARY_CONCURRENCY", "8")))
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
    env_path = ROOT / ".env"
    overrides = parse_env_text(env_path.read_text()) if env_path.exists() else {}
    env = sandbox.default_env(overrides)
    env["HOME"] = "/lensjob/home"  # writable scratch (workspace is read-only)
    return env


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
        "Key locations (relative to /workspace):",
        "  - execution transcript: .pi_transcripts/session.jsonl",
        "  - planner transcript:   .pi_transcripts/planner.session.jsonl",
        "  - run-loop sub-agent sessions: .home/.pi/agent/sessions/*/*.jsonl",
        "  - run-loop state: planner/RUN_LOOP_STATE.json",
        "  - the agent's own write-ups: writeup/ and/or writeups/",
        "  - the task spec: proposal.md, planner/OVERALL_PLAN.md, planner/INSTRUCTIONS_*.md",
        "",
        "File index (relative path | bytes):",
        *_lens_file_index(base),
        "",
        "User question:",
        question.strip(),
    ]
    return "\n".join(lines)


def _writeup_prompt(rel: str, base: Path) -> str:
    """Prompt for the meta-agent that reads a run and writes a clean write-up.

    Mirrors the ``write_up.md`` structure used by the empirical-ml-research
    workflow: a faithful, self-contained report a task-aware reader can follow.
    """
    tdir = base / ".pi_transcripts"
    status = "running" if (tdir / RUNNING_MARKER).exists() else "completed"
    data = _transcript_disk(rel)
    sess = ", ".join(
        f"{s.get('label') or s['name']}({len(s['turns'])})"
        for s in data.get("sessions", [])
    )
    rl = data.get("run_loop")
    lines = [
        "You are a META-AGENT that writes a clean, faithful write-up of an autonomous",
        "research run produced by ANOTHER agent. Your working directory (/workspace) is",
        "that run's directory, mounted READ-ONLY: read any file (code, transcripts,",
        "results, data, existing write-ups) and run read-only shell commands, but you",
        "cannot modify the run.",
        "",
        "FIRST read enough to understand the run (do NOT start writing until you have):",
        "  - the task spec: proposal.md, planner/OVERALL_PLAN.md, planner/INSTRUCTIONS_*.md",
        "  - the execution + planner transcripts (see Key locations below)",
        "  - the agent's OWN write-ups in writeup/ or writeups/ — treat these as EVIDENCE,",
        "    NOT ground truth: the run's agent may have over- or under-claimed. Verify",
        "    claims against the actual code and result/data files before repeating them.",
        "  - the real code and the result/data files it produced.",
        "",
        "THEN write ONE clean, self-contained write-up in Markdown for a reader who knows",
        "the task/setup but did NOT watch the run. Use this structure:",
        "  - **TL;DR** — 3-5 sentences: what was attempted and the headline outcome.",
        "  - **Goal / research question**",
        "  - **What was done** — methodology in order: approach, models, datasets, key steps.",
        "  - **Key findings / results** — concrete numbers; cite the result file / plot paths.",
        "  - **Important choices & rationale** — non-obvious decisions and why.",
        "  - **Failed approaches / dead-ends** — what didn't work and why (don't overstate",
        "    how thoroughly something was ruled out).",
        "  - **Limitations & caveats** — including anything the run's own write-ups got",
        "    wrong or overclaimed.",
        "  - **Status** — done / in-progress / blocked, and what's next.",
        "",
        "Be faithful and grounded: cite specific files/results for claims, never invent",
        "numbers, and flag uncertainty. Be concise and well-organized (clear prose + short",
        "lists, not walls of text). Output ONLY the Markdown write-up, with no preamble.",
        "",
        f"Run: {rel}",
        f"Status: {status} | mode: {data.get('mode')} | est. spend: ${data.get('cost', 0) or 0:.2f}",
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
        "Key locations (relative to /workspace):",
        "  - execution transcript: .pi_transcripts/session.jsonl",
        "  - planner transcript:   .pi_transcripts/planner.session.jsonl",
        "  - run-loop sub-agent sessions: .home/.pi/agent/sessions/*/*.jsonl",
        "  - run-loop state: planner/RUN_LOOP_STATE.json",
        "  - the agent's own write-ups: writeup/ and/or writeups/",
        "",
        "File index (relative path | bytes):",
        *_lens_file_index(base),
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
    inner = [
        "pi",
        "-p",
        "--session",
        "/lensjob/session.jsonl",
        "--model",
        LENS_MODEL,
        "--thinking",
        thinking,
        "--mode",
        "json",
        prompt,
    ]
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


def start_writeup(rel: str) -> dict:
    """Spawn a read-only meta-agent that reads the run and writes a clean write-up."""
    if sandbox.available() is None:
        return {"error": "bubblewrap (bwrap) is not installed"}
    base = _safe_disk_path(rel)
    if base is None or not (base / ".pi_transcripts").exists():
        return {"error": "unknown run"}
    return _spawn_lens(rel, base, _writeup_prompt(rel, base), WRITEUP_THINKING)


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
    if not running and not turns and proc.returncode not in (0, None):
        err = b""
        try:
            err = proc.stderr.read() if proc.stderr else b""
        except (OSError, ValueError):
            pass
        rc = proc.returncode
        detail = err.decode("utf-8", "replace").strip()[-400:]
        if not detail and rc is not None and rc < 0:
            detail = (
                f"oversight agent was killed (signal {-rc}) — most likely out of memory "
                f"from too many parallel summaries; lower LENS_SUMMARY_CONCURRENCY"
            )
        out["error"] = detail or f"oversight agent exited rc={rc}"
    return out


def cancel_lens(job: str) -> dict:
    info = _LENS_JOBS.get(job)
    if info and info["proc"].poll() is None:
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
        try:
            path = urlparse(self.path).path
            if path == "/api/lens/ask":
                body = self._read_body()
                self._json(
                    start_lens((body.get("id") or ""), body.get("question") or "")
                )
            elif path == "/api/lens/cancel":
                body = self._read_body()
                self._json(cancel_lens(body.get("job") or ""))
            elif path == "/api/lens/writeup":
                body = self._read_body()
                self._json(start_writeup(body.get("id") or ""))
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
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("/", "/index.html"):
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
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 var(--sans);}
::selection{background:rgba(122,162,247,.3)}
.sidebar::-webkit-scrollbar,.main::-webkit-scrollbar,pre::-webkit-scrollbar{width:9px;height:9px}
.sidebar::-webkit-scrollbar-thumb,.main::-webkit-scrollbar-thumb,pre::-webkit-scrollbar-thumb{background:var(--panel3);border-radius:6px}
.app{display:grid;grid-template-columns:var(--sidebar-w,300px) 6px minmax(0,1fr);height:100vh}
.app.lens-open{grid-template-columns:var(--sidebar-w,300px) 6px minmax(0,1fr) 6px var(--lens-w,420px)}
.sidebar{background:var(--panel);border-right:1px solid var(--border);overflow-y:auto;padding:12px}
.resizer{cursor:col-resize;background:var(--border);transition:background .12s}
.resizer:hover,.resizer.active{background:var(--accent)}
.resizer[hidden]{display:none}
#lensResizer{grid-column:4}
.ovbtn{width:100%;display:flex;align-items:center;justify-content:center;gap:8px;background:var(--panel2);border:1px solid var(--border);color:var(--fg);border-radius:8px;padding:9px 10px;margin-bottom:11px;cursor:pointer;font-size:13px;font-weight:700;letter-spacing:.2px;transition:.12s}
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
.sesstabs{display:flex;gap:6px;flex-wrap:wrap;padding:8px 22px 10px;max-width:1000px;margin:0 auto}
.sesstab{font-size:12px;border:1px solid var(--border);background:var(--panel2);color:var(--muted);border-radius:7px;padding:4px 10px;cursor:pointer;transition:.12s;display:inline-flex;align-items:center}
.sesstab:hover{color:var(--fg);border-color:var(--faint)}
.sesstab.active{border-color:var(--accent);color:var(--fg);background:var(--panel3)}
.sesstab .tc{font-size:9px;color:var(--faint);margin-left:6px;font-family:var(--mono)}
.sesstab.active .tc{color:var(--muted)}
.lens-toggle.active{border-color:var(--accent);color:var(--fg);background:var(--panel3)}
/* Run Lens drawer */
.lens{grid-column:5;min-width:0;height:100vh;overflow:hidden;
  background:var(--panel);border-left:1px solid var(--border);display:flex;flex-direction:column}
.lens[hidden]{display:none}
.lens-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:11px 14px;border-bottom:1px solid var(--border);background:var(--panel2)}
.lens-headbtns{display:flex;gap:6px;align-items:center;flex:none}
.lens-title{font-weight:700;font-size:13px;display:flex;gap:7px;align-items:center}
.lens-mark{color:var(--accent)}
.lens-sub{font-weight:500;font-size:11px;color:var(--muted);font-family:var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:230px}
.lens-msgs{flex:1;overflow-y:auto;padding:12px 14px}
.lens-q{margin:4px 0 10px;padding:8px 11px;background:var(--panel3);border:1px solid var(--border);border-radius:8px;color:var(--fg);font-size:13px;white-space:pre-wrap;word-break:break-word}
.lens-q .who{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--user);margin-bottom:3px;font-weight:700}
.lens-ans{margin:2px 0 16px}
.lens-ans .who{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--accent);margin-bottom:5px;font-weight:700}
.lens-thinking{color:var(--muted);font-size:12px;font-style:italic}
.lens-composer{border-top:1px solid var(--border);padding:10px 12px;background:var(--panel2)}
.lens-composer textarea{width:100%;resize:vertical;min-height:42px;background:var(--bg);border:1px solid var(--border);color:var(--fg);border-radius:8px;padding:8px 10px;font:13px/1.5 var(--sans);outline:none}
.lens-composer textarea:focus{border-color:var(--accent)}
.lens-row{display:flex;align-items:center;gap:8px;margin-top:7px}
.lens-status{flex:1;font-size:11px;color:var(--muted);font-family:var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
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
.livetag{font-size:9px;font-weight:700;letter-spacing:.5px;color:var(--ok);border:1px solid rgba(158,206,106,.4);border-radius:5px;padding:0 5px}
.donetag{font-size:9px;font-weight:700;letter-spacing:.5px;color:var(--faint);text-transform:uppercase}
/* Overview dashboard (homepage) */
.dash{max-width:1040px;margin:0 auto;padding:18px 22px}
.dash-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:2px 2px 14px;flex-wrap:wrap}
.dash-title{font-size:16px;font-weight:700}
.dash-title span{color:var(--muted);font-weight:500;font-size:13px}
.dash-actions{display:flex;gap:8px;align-items:center}
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
<div class="app">
  <div class="sidebar">
    <button id="overviewBtn" class="ovbtn" title="Status dashboard of all runs">⌂ Overview — all runs</button>
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
        <button class="tbtn" id="toggleAll" title="Expand / collapse all blocks">expand</button>
        <button class="tbtn lens-toggle" id="lensBtn" disabled title="Open a run to ask the read-only oversight agent about it">🔍 Run Lens</button>
        <label><input type="checkbox" id="autorefresh" checked> live</label>
      </div>
    </div>
    <div id="sesstabs" class="sesstabs"></div>
    </div>
    <div class="content" id="content"><div class="empty">Click through the folders on the left and pick a run to view its transcript.</div></div>
  </div>
  <div class="resizer" id="lensResizer" title="Drag to resize Run Lens" hidden></div>
  <aside class="lens" id="lens" hidden>
    <div class="lens-head">
      <div class="lens-title"><span class="lens-mark">›</span> Run Lens <span class="lens-sub" id="lensCtx">no run</span></div>
      <div class="lens-headbtns"><button class="tbtn" id="lensWriteup" title="Have a meta-agent read this run's code + transcripts and produce a clean write-up">📝 Writeup</button><button class="tbtn" id="lensClose" title="Close">×</button></div>
    </div>
    <div class="lens-msgs" id="lensMsgs"><div class="empty" style="padding:30px 14px">Ask a read-only agent about this run — its state, code, or transcripts.<br><br>It can read every file in the run (mounted read-only) and cite evidence.</div></div>
    <div class="lens-composer">
      <textarea id="lensInput" rows="2" placeholder="Ask about this run… (Enter to send)"></textarea>
      <div class="lens-row"><span class="lens-status" id="lensStatus"></span><button class="tbtn" id="lensSend">Ask</button><button class="tbtn" id="lensStop" hidden>Stop</button></div>
    </div>
  </aside>
</div>
<script>
const E=s=>document.createElement(s);
const esc=s=>(s==null?"":String(s)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

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

let state={agentId:null,sess:0,data:null,es:null,path:"",items:[],filter:"",
           panes:{},paneAgent:null,lensOpen:false,lensEs:null,lensJob:null,
           view:"overview",overview:[],overviewSig:"",summaries:{},sumQueue:[],sumActive:0,sumPoll:null};
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
      const dot=it.live?'<span class="dot live"></span>':'<span class="dot done"></span>';
      const tag=it.live?'<span class="livetag">LIVE</span>':`<span class="donetag">${esc(it.status||"done")}</span>`;
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
  openStream();
  // The Run Lens is bound to a specific run: opening a run makes it available
  // and (on a fresh run) docks it open on the side; switching clears stale state.
  if(switching){ lensReset(); lensSetOpen(true,false); }
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
  if(open){updateLensCtx(); if(focus)document.getElementById("lensInput").focus();}
}
function lensReset(){   // stop any in-flight job and clear the conversation
  stopLens(true);
  const m=document.getElementById("lensMsgs");
  if(m)m.innerHTML='<div class="empty" style="padding:30px 14px">Ask a read-only agent about this run \u2014 its state, code, or transcripts.<br><br>It can read every file in the run (mounted read-only) and cite evidence.</div>';
  lensStatus("");
}
function updateLensCtx(){
  const el=document.getElementById("lensCtx"); if(!el)return;
  el.textContent=state.agentId?("· "+state.agentId.split("/").pop()):"no run selected";
}
function lensBusy(b){document.getElementById("lensSend").hidden=b;document.getElementById("lensStop").hidden=!b;}
function lensStatus(s){document.getElementById("lensStatus").textContent=s||"";}
function lensAddQuestion(q){
  const m=document.getElementById("lensMsgs");const e=m.querySelector(".empty");if(e)e.remove();
  const d=E("div");d.className="lens-q";d.innerHTML='<span class="who">You</span>'+esc(q);m.appendChild(d);
  const a=E("div");a.className="lens-ans";a.innerHTML='<span class="who">Run Lens</span><div class="ansbody"><div class="lens-thinking">working…</div></div>';
  m.appendChild(a);m.scrollTop=m.scrollHeight;
  return a.querySelector(".ansbody");
}
function lensRender(body,data){
  if(data.error){body.innerHTML='<div class="lens-thinking" style="color:var(--err)">'+esc(data.error)+'</div>';return;}
  const blocks=(data.turns||[]).flatMap(t=>t.blocks||[]);
  if(!blocks.length){body.innerHTML='<div class="lens-thinking">'+(data.running?'working…':'(no output)')+'</div>';return;}
  body.innerHTML="";body.appendChild(renderBlocks(blocks));
}
function lensStreamJob(job,body,workingMsg){
  state.lensJob=job;lensStatus("reading the run…");
  const m=document.getElementById("lensMsgs");
  const es=new EventSource("/api/lens/stream?job="+encodeURIComponent(job));state.lensEs=es;
  es.onmessage=ev=>{let d;try{d=JSON.parse(ev.data);}catch(_){return;}
    const pinned=m.scrollHeight-m.scrollTop-m.clientHeight<120;
    lensRender(body,d);
    if(pinned)m.scrollTop=m.scrollHeight;
    if(d.error||!d.running){es.close();state.lensEs=null;lensBusy(false);lensStatus(d.error?"error":"done");}
    else lensStatus(workingMsg||"investigating…");
  };
  es.onerror=()=>{};
}
async function sendLens(){
  const inp=document.getElementById("lensInput");const q=inp.value.trim();
  if(!q){return;} if(!state.agentId){lensStatus("pick a run first");return;}
  stopLens(true); inp.value="";
  const body=lensAddQuestion(q);
  lensBusy(true);lensStatus("starting Run Lens…");
  let res; try{res=await (await fetch("/api/lens/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:state.agentId,question:q})})).json();}catch(e){res={error:String(e)};}
  if(!res||res.error||!res.job){body.innerHTML='<div class="lens-thinking" style="color:var(--err)">'+esc((res&&res.error)||"failed to start")+'</div>';lensBusy(false);lensStatus("error");return;}
  lensStreamJob(res.job,body);
}
// Meta-agent: read the run's code + transcripts and produce a clean write-up.
async function requestWriteup(){
  if(!state.agentId){lensStatus("pick a run first");return;}
  stopLens(true);
  const body=lensAddQuestion("\ud83d\udcdd Generate a clean write-up of this run");
  lensBusy(true);lensStatus("starting writeup…");
  let res; try{res=await (await fetch("/api/lens/writeup",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:state.agentId})})).json();}catch(e){res={error:String(e)};}
  if(!res||res.error||!res.job){body.innerHTML='<div class="lens-thinking" style="color:var(--err)">'+esc((res&&res.error)||"failed to start")+'</div>';lensBusy(false);lensStatus("error");return;}
  lensStreamJob(res.job,body,"writing up the run…");
}
function stopLens(quiet){
  if(state.lensEs){state.lensEs.close();state.lensEs=null;}
  if(state.lensJob){fetch("/api/lens/cancel",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({job:state.lensJob})}).catch(()=>{});state.lensJob=null;}
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
    +'<div class="dash-actions"><button id="sumAllBtn" class="tbtn" title="Ask Run Lens for a brief summary of every run (runs in parallel)">\u2726 Generate summaries</button>'
    +'<button id="sumStopBtn" class="tbtn" hidden>Stop</button></div></div>'
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
  const sig=JSON.stringify(res.runs.map(r=>[r.path,r.live,r.status,r.turns,r.sessions,r.lastActivity,r.cost,
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
function runStatusLine(r){
  const b=[];
  if(r.cost!=null)b.push(`<b style="color:var(--ok)">$${Number(r.cost).toFixed(2)}</b>`);
  if(r.goal)b.push(`goal <b>${esc(r.goal.status||"active")}</b>`+(r.goal.tokensUsed!=null?` \u00b7 ${esc(r.goal.tokensUsed)} tok`:""));
  if(r.run_loop){const rl=r.run_loop;b.push(`run-loop <b>${esc(rl.status||"?")}</b> \u00b7 S${rl.segment}P${rl.phase} ${esc(rl.stage||"")} \u00b7 ${rl.completed} done`);}
  b.push(`<b>${r.sessions}</b> sess \u00b7 <b>${r.turns}</b> turns`);
  b.push(fmtAgo(r.lastActivity));
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
function renderOverview(runs){
  const grid=document.getElementById("dashGrid"); if(!grid)return;
  const c=document.getElementById("dashCount"); if(c)c.textContent="("+runs.length+")";
  grid.innerHTML="";
  if(!runs.length){grid.innerHTML='<div class="empty">No runs found under outputs/.</div>';return;}
  let curGroup=null;
  for(const r of runs){
    if((r.group||"")!==curGroup){curGroup=r.group||"";const g=E("div");g.className="dgroup";g.textContent=curGroup||"runs";grid.appendChild(g);}
    const card=E("div");card.className="card";
    const dot=r.live?'<span class="dot live"></span>':'<span class="dot done"></span>';
    const tag=r.live?'<span class="livetag">LIVE</span>':`<span class="donetag">${esc(r.status||"done")}</span>`;
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
  const runs=state.overview||[]; if(!runs.length)return;
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

function renderTabs(data){
  const tabs=document.getElementById("sesstabs");tabs.innerHTML="";
  const sessions=data.sessions||[];
  if(sessions.length<=1){tabs.style.display="none";return;}
  tabs.style.display="";
  sessions.forEach((s,i)=>{
    const m=(s.group||"").match(/Segment\s*(\d+).*Phase\s*(\d+)/);   // compact, self-describing label
    const label=(m?`S${m[1]}P${m[2]} `:"")+(s.label||s.name);
    const b=E("button");b.className="sesstab"+(i===state.sess?" active":"");
    b.innerHTML=`${esc(label)}<span class="tc">${s.turns.length}</span>`;
    b.title=s.group||label;
    b.onclick=()=>selectSession(i);
    tabs.appendChild(b);
  });
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
document.getElementById("lensBtn").onclick=()=>lensSetOpen(!state.lensOpen,true);
document.getElementById("lensClose").onclick=()=>lensSetOpen(false);
document.getElementById("overviewBtn").onclick=showOverview;
lensSetOpen(true,false);   // open the lens iff a run is deep-linked; otherwise it stays closed/disabled
document.getElementById("lensSend").onclick=sendLens;
document.getElementById("lensWriteup").onclick=requestWriteup;
document.getElementById("lensStop").onclick=()=>stopLens();
document.getElementById("lensInput").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendLens();}});
// Keyboard: 1-9 jump to a session tab, [ / ] cycle prev/next.
document.addEventListener("keydown",e=>{
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
    print(f"Agent viewer on {url}  (Ctrl-C to stop)", flush=True)
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
