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
import re
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src import sandbox
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
    return {"turns": turns, "goal": goal, "header": header}


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
    t = d / ".pi_transcripts"
    return (t / "session.jsonl").exists() or (t / RUNNING_MARKER).exists()


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
    raw = [("main", main["turns"])]
    if planner is not None:
        raw.append(("planner", planner["turns"]))
    for nm, text in sub_sessions:
        raw.append((nm, parse_session(text)["turns"]))
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
    return {
        "mode": mode,
        # The goal-mode objective lives in the execution session; fall back to the
        # planner session just in case.
        "goal": main["goal"] or (planner["goal"] if planner else None),
        "run_loop": _run_loop_summary(run_loop_state_text),
        "sessions": sessions,
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


def _transcript_disk(rel: str) -> dict:
    base = _safe_disk_path(rel)
    if base is None or not base.exists():
        return {"error": "not found"}
    tdir = base / ".pi_transcripts"
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
    return data


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
        stages = sorted({s.rsplit("_", 1)[0] if s[-1].isdigit() else s for s in subs})
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
            elif path == "/api/agent":
                qs = parse_qs(parsed.query)
                self._json(get_transcript((qs.get("id") or [""])[0]))
            elif path == "/api/stream":
                qs = parse_qs(parsed.query)
                self._stream((qs.get("id") or [""])[0])
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
.sidebar{background:var(--panel);border-right:1px solid var(--border);overflow-y:auto;padding:12px}
.resizer{cursor:col-resize;background:var(--border);transition:background .12s}
.resizer:hover,.resizer.active{background:var(--accent)}
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
.topbar{position:sticky;top:0;z-index:5;background:rgba(15,17,23,.92);backdrop-filter:blur(6px);
  border-bottom:1px solid var(--border);padding:12px 22px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.topbar .title{font-weight:700;font-size:16px}
.flt{width:100%;background:var(--panel2);border:1px solid var(--border);color:var(--fg);border-radius:7px;padding:6px 9px;font-size:12px;outline:none;margin-bottom:10px}
.flt:focus{border-color:var(--accent)}
.statepill{font-size:12px;border:1px solid var(--border);border-radius:20px;padding:3px 11px;color:var(--muted)}
.statepill b{color:var(--fg)}
.content{max-width:1000px;margin:0 auto;padding:18px 22px}
.turn{margin:14px 0;border:1px solid var(--border);border-radius:10px;overflow:hidden;background:var(--panel)}
.turn .role{font-size:11px;text-transform:uppercase;letter-spacing:.6px;padding:7px 14px;font-weight:700;border-bottom:1px solid var(--border)}
.turn.user .role{color:var(--user)} .turn.assistant .role{color:var(--assist)}
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
.phases{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 0}
.phase{font-size:11px;border:1px solid var(--border);border-radius:6px;padding:3px 8px;background:var(--panel2)}
.phase.cur{border-color:var(--accent);color:var(--accent)}
.sesstabs{display:flex;gap:6px;flex-wrap:wrap;padding:10px 22px 0;max-width:1000px;margin:0 auto}
.sesstab{font-size:12px;border:1px solid var(--border);background:var(--panel2);color:var(--muted);border-radius:7px;padding:4px 10px;cursor:pointer;transition:.12s}
.sesstab:hover{color:var(--fg);border-color:var(--faint)}
.sesstab.active{border-color:var(--accent);color:var(--fg);background:var(--panel3)}
.sessgroup{flex-basis:100%;font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:var(--faint);font-weight:700;margin:8px 2px 0}
.sessgroup:first-child{margin-top:0}
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
</style></head>
<body>
<div class="app">
  <div class="sidebar">
    <div class="browse-head"><h1>Browse</h1><button id="refresh" title="Refresh">⟳</button></div>
    <div id="breadcrumb" class="breadcrumb"></div>
    <input id="filter" class="flt" placeholder="filter…" autocomplete="off">
    <div id="tree"></div>
  </div>
  <div class="resizer" id="resizer" title="Drag to resize"></div>
  <div class="main">
    <div class="topbar">
      <span class="title" id="title">Select a run</span>
      <span class="statepill" id="modepill" style="display:none"></span>
      <span class="statepill" id="goalpill" style="display:none"></span>
      <span class="statepill" id="rlpill" style="display:none"></span>
      <div class="controls">
        <label><input type="checkbox" id="autorefresh" checked> live</label>
        <span id="updated"></span>
      </div>
    </div>
    <div id="phases"></div>
    <div id="sesstabs" class="sesstabs"></div>
    <div class="content" id="content"><div class="empty">Click through the folders on the left and pick a run to view its transcript.</div></div>
  </div>
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
           panes:{},paneAgent:null};
let busyTree=false;

async function jget(u){
  const ctrl=new AbortController();const t=setTimeout(()=>ctrl.abort(),12000);
  try{const r=await fetch(u,{signal:ctrl.signal});return await r.json();}
  catch(e){return null;}
  finally{clearTimeout(t);}
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
  const res=await jget("/api/tree?path="+encodeURIComponent(state.path));
  if(res){state.items=res.items||[];renderTree(state.items);}
}
function selectRun(id){
  state.agentId=id;state.sess=0;state._pickDefault=true;location.hash=encodeURIComponent(id);
  renderTree(state.items);   // refresh active highlight
  openStream();
}

// Pick the most useful session tab when a run is first opened: the execution
// (main) session once it has content, else whichever session does (e.g. the
// planner while planning is still in progress).
function defaultSess(data){
  const ss=data.sessions||[];
  const mi=ss.findIndex(s=>s.name==="main" && (s.turns||[]).length);
  if(mi>=0)return mi;
  const any=ss.findIndex(s=>(s.turns||[]).length);
  return any>=0?any:0;
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
  const mp=document.getElementById("modepill");
  if(data.mode){mp.style.display="";mp.innerHTML=`mode <b>${esc(data.mode)}</b>`;}else mp.style.display="none";
  const gp=document.getElementById("goalpill");
  if(data.goal){gp.style.display="";gp.innerHTML=`goal <b>${esc(data.goal.status||"active")}</b> · ${esc(data.goal.tokensUsed??"?")} tok`;}else gp.style.display="none";
  const rp=document.getElementById("rlpill");const ph=document.getElementById("phases");ph.innerHTML="";
  if(data.run_loop){
    const rl=data.run_loop;
    rp.style.display="";rp.innerHTML=`run-loop <b>${esc(rl.status)}</b> · seg ${rl.segment} ph ${rl.phase} · ${esc(rl.stage)} · $${(rl.cost||0).toFixed?(rl.cost||0).toFixed(2):rl.cost}`;
    for(const c of (rl.completed||[])){const s=E("span");s.className="phase";s.textContent=`S${c.segment}P${c.phase}:${c.decision}`;ph.appendChild(s);}
    const cur=E("span");cur.className="phase cur";cur.textContent=`▶ S${rl.segment}P${rl.phase} ${rl.stage}`;ph.appendChild(cur);
    if(rl.lastError){const s=E("span");s.className="phase";s.style.borderColor="var(--err)";s.style.color="var(--err)";s.textContent="error: "+rl.lastError.slice(0,80);ph.appendChild(s);}
  }else rp.style.display="none";
}

function renderTabs(data){
  const tabs=document.getElementById("sesstabs");tabs.innerHTML="";
  const sessions=data.sessions||[];
  if(sessions.length<=1){return;}
  let curGroup=null;
  sessions.forEach((s,i)=>{
    if(s.group && s.group!==curGroup){   // start each phase group on its own row
      curGroup=s.group;
      const g=E("span");g.className="sessgroup";g.textContent=s.group;tabs.appendChild(g);
    }
    const b=E("button");b.className="sesstab"+(i===state.sess?" active":"");
    b.textContent=`${s.label||s.name} (${s.turns.length})`;
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
  document.getElementById("updated").textContent="updated "+new Date().toLocaleTimeString();
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
  jget("/api/agent?id="+encodeURIComponent(state.agentId)).then(applyTranscript);
  if(!document.getElementById("autorefresh").checked)return;   // streaming paused
  const es=new EventSource("/api/stream?id="+encodeURIComponent(state.agentId));
  es.onmessage=e=>{try{applyTranscript(JSON.parse(e.data));}catch(_){}};
  es.onerror=()=>{};                   // browser auto-reconnects; ignore blips
  state.es=es;
}

if(location.hash.length>1){state.agentId=decodeURIComponent(location.hash.slice(1));}
_initFilter();initResizer();
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
loadDir(startDir).then(()=>{ if(state.agentId)openStream(); });
setInterval(refreshDir,3000);   // refresh current dir listing; transcript arrives via SSE
</script>
</body></html>
"""

INDEX_HTML = INDEX_HTML.replace("/*__PALETTE__*/", PALETTE_CSS)


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
