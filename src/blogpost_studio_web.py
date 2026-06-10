"""Blogpost Studio web app — mounted under ``/studio`` by the agent viewer.

A two-pane page (chat + live markdown editor/preview) for co-writing a blogpost
about one completed run with an oversight ``pi`` agent: the run is mounted
read-only at /source, the agent edits ``final_writeup.md`` in a persistent
workspace, and the human steers in chat (or sends ``/draft`` to get the whole
post in one turn) and edits the prose directly. The engine lives in
:mod:`src.blogpost_studio`; this module is the HTTP routes + embedded UI.

There is no standalone server: :func:`handle` is called by the agent viewer's
request handler for every request and claims the ones under ``/studio``, so the
studio shares the viewer's port (and, in production, its Cloudflare tunnel and
Access policy). Workspaces persist under ``outputs/06_blogpost_studio/<run>/``.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src import audit_agent
from src.agent_viewer import OUTPUTS_DIR, _discover_run_dirs, _run_item
from src.blogpost_studio import (
    DOC_NAME,
    SESSION_NAME,
    STUDIO_ROOT,
    StudioSession,
    default_work_dir,
)
from src.theme import EDITOR_CSS, HIGHLIGHT_JS, PALETTE_CSS, PREVIEW_CSS

PREFIX = "/studio"

# Each selected run gets its own StudioSession, cached by run-dir path so
# switching away and back keeps its conversation, document, and any in-flight
# turn. The HTTP server is threaded; the lock serializes session
# creation/selection so two concurrent selects can't build two StudioSessions
# for one run (they would share a workspace + session.jsonl but not a turn lock).
SESSIONS: dict[str, StudioSession] = {}
CURRENT: StudioSession | None = None
_SELECT_LOCK = threading.Lock()

_IMG_TYPES = {
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def _run_phase(d: Path) -> str:
    """Canonical Active/Completed/Failed phase, reusing the agent viewer's logic
    (heartbeat/marker health + run-loop state + manifest status) so "finished"
    means the same thing here as it does in the run viewer."""
    try:
        return _run_item(d, str(d)).get("phase") or "Completed"
    except Exception:  # noqa: BLE001 - never let a bad run dir break the picker
        return "Failed"


def list_runs() -> list[dict]:
    """Every run available to write about, tagged with its phase and folder.

    Only ``Completed`` runs are selectable — you can't write a blogpost about a
    run that is still going (Active) or that errored out (Failed). Order mirrors
    the viewer's overview: folders by their most recent activity, and within a
    folder runs you've already drafted come first (a draft edit counts as
    activity), then the rest newest-first."""
    runs = []
    for d in _discover_run_dirs(OUTPUTS_DIR):
        name = d.name
        mode = (
            "multi_phase"
            if name.endswith("_multi_phase")
            else ("goal" if name.endswith("_goal") else "")
        )
        try:
            group = str(d.parent.relative_to(OUTPUTS_DIR))
        except ValueError:
            group = ""
        try:
            mtime = (d / ".pi_transcripts" / "session.jsonl").stat().st_mtime
        except OSError:
            mtime = d.stat().st_mtime if d.exists() else 0.0
        try:
            draft_mtime = (default_work_dir(d) / DOC_NAME).stat().st_mtime
        except OSError:
            draft_mtime = None
        phase = _run_phase(d)
        session = SESSIONS.get(str(d))
        runs.append(
            {
                "name": name,
                "path": str(d),
                "mode": mode,
                "group": group,
                "phase": phase,  # Active | Completed | Failed
                "selectable": phase == "Completed",
                "started": draft_mtime is not None,  # a studio draft exists
                "drafting": bool(session and session.is_running()),
                "current": CURRENT is not None and CURRENT.run_dir == d,
                "mtime": max(mtime, draft_mtime or 0.0),
            }
        )
    latest = {}
    for r in runs:
        latest[r["group"]] = max(latest.get(r["group"], 0.0), r["mtime"])
    runs.sort(
        key=lambda r: (
            -latest[r["group"]],  # most recently active folder first
            r["group"],  # keep folders contiguous (the picker shows section labels)
            not r["started"],  # drafts in progress on top within a folder
            -r["mtime"],
            r["name"],
        )
    )
    return runs


def _validated_run_dir(spec: str) -> Path:
    """A Completed run dir under outputs/, or raise ValueError."""
    try:
        rd = Path(spec).resolve()
    except (OSError, ValueError) as exc:
        raise ValueError(f"bad run path: {exc}")
    if OUTPUTS_DIR.resolve() not in rd.parents:
        raise ValueError("run must live under outputs/")
    if not audit_agent.is_run_dir(rd):
        raise ValueError(f"{rd.name} is not a run dir (no .pi_transcripts/)")
    phase = _run_phase(rd)
    if phase != "Completed":
        raise ValueError(
            f"{rd.name} is {phase} — only finished (Completed) runs can be opened in the studio"
        )
    return rd


def _session_for(rd: Path) -> StudioSession:
    """The cached StudioSession for a validated run dir, created if needed."""
    with _SELECT_LOCK:
        session = SESSIONS.get(str(rd))
        if session is None:
            session = StudioSession(rd)
            SESSIONS[str(rd)] = session
        return session


def select_run(spec: str) -> dict:
    """Make ``spec`` (a run-dir path) the active session, creating it if needed."""
    global CURRENT
    CURRENT = _session_for(_validated_run_dir(spec))
    return state_payload()


def reset_all() -> dict:
    """Delete every studio draft workspace (drafts, figures, conversations).

    Refuses while any session has a turn in flight. Live sessions are reset in
    place (workspace re-staged); workspaces with no session this process are
    removed outright."""
    with _SELECT_LOCK:
        sessions = list(SESSIONS.values())
    if any(s.is_running() for s in sessions):
        raise RuntimeError("an agent is working in some session; stop it first")
    known = {str(s.work) for s in sessions}
    deleted = 0
    if STUDIO_ROOT.is_dir():
        for d in sorted(STUDIO_ROOT.iterdir()):
            if not d.is_dir():
                continue
            if (d / DOC_NAME).exists() or (d / SESSION_NAME).exists():
                deleted += 1
            if str(d) not in known:
                shutil.rmtree(d, ignore_errors=True)
    for s in sessions:
        s.reset()
    return {"deleted": deleted}


def draft_all(dry: bool) -> dict:
    """Start a parallel ``/draft`` turn for every Completed, non-goal run that
    has no draft yet. ``dry`` only reports the targets — the UI shows them in
    the confirmation dialog first, since each /draft is a long, real agent turn.
    """
    targets = [
        r
        for r in list_runs()
        if r["selectable"]
        and r["mode"] != "goal"
        and not r["started"]
        and not r["drafting"]
    ]
    started = []
    if not dry:
        for r in targets:
            session = _session_for(Path(r["path"]))
            try:
                session.start_turn("/draft")
                started.append(r["name"])
            except (ValueError, RuntimeError):
                pass  # raced with another turn; it shows as drafting either way
    return {"targets": [r["name"] for r in targets], "started": started}


def state_payload() -> dict:
    s = CURRENT
    return {"selected": False} if s is None else {"selected": True, **s.state()}


def _workspace_image(rel: str) -> tuple[bytes, str] | None:
    """Read an image referenced by a RELATIVE path from inside the workspace.

    Lets the markdown preview render any figure the document points at — e.g.
    ``final_plots/fig1.png`` or ``./final_plots/fig1.png`` — not just basenames
    under ``final_plots/``. The resolved path must stay inside the workspace and
    be an image type, so this can't be used to read arbitrary files (transcripts,
    .env, /source, …).
    """
    s = CURRENT
    rel = (rel or "").lstrip("/")
    if s is None or not rel:
        return None
    work = s.work.resolve()
    try:
        p = (work / rel).resolve()
    except (OSError, ValueError):
        return None
    if p != work and work not in p.parents:
        return None  # escaped the workspace
    if not p.is_file():
        return None
    ctype = _IMG_TYPES.get(p.suffix.lower())
    if ctype is None:
        return None  # only serve image types from this endpoint
    return p.read_bytes(), ctype


def _stream_payload() -> dict:
    """The full state pushed to the client: chat + run/doc status."""
    s = CURRENT
    if s is None:
        return {
            "selected": False,
            "turns": [],
            "running": False,
            "doc": {"mtime": 0.0, "size": 0},
        }
    parsed = s.transcript()
    running = s.is_running()
    turns = list(parsed["turns"])
    if running:
        # Mid-turn, session.jsonl lags the agent (it flushes at message
        # boundaries); splice in the live turns — including the streaming
        # partial message — from the json stdout log, marked for the UI.
        last_ts = (turns[-1].get("ts") or 0) if turns else 0
        turns += [dict(t, live=True) for t in s.live_turns(after_ts=last_ts)]
    dst = s.doc_path.stat() if s.doc_path.exists() else None
    return {
        "selected": True,
        "turns": turns,
        "cost": parsed.get("cost", 0.0),
        "running": running,
        "doc": {
            "mtime": dst.st_mtime if dst else 0.0,
            "size": dst.st_size if dst else 0,
        },
    }


def _cheap_sig() -> tuple:
    """A cheap (no-parse) change key for the SSE loop: a couple of stat() calls.

    The transcript can grow to many MB, so re-reading and re-parsing it on every
    poll is the main cost. Instead we poll this — session/doc mtime+size, the
    active run, and the running flag — and only build the full payload (which
    parses the transcript) when one of these actually moved.
    """
    s = CURRENT
    if s is None:
        return ("",)

    def stat(p: Path) -> tuple:
        try:
            x = p.stat()
            return (x.st_mtime, x.st_size)
        except OSError:
            return (0.0, 0)

    # The agent log only matters mid-turn (it drives the live thinking stream);
    # keying on it while idle would re-push the payload for stale log churn.
    running = s.is_running()
    log_sig = stat(s.log_path) if running else ()
    return (str(s.run_dir), *stat(s.session_path), *stat(s.doc_path), *log_sig, running)


# --------------------------------------------------------------------------- #
# Request handling (called from the agent viewer's Handler)
# --------------------------------------------------------------------------- #
def handle(h, method: str) -> bool:
    """Serve one request if its path is under /studio. Returns whether it was ours.

    ``h`` is the viewer's ``BaseHTTPRequestHandler`` instance; its ``_send`` /
    ``_json`` / ``_read_body`` helpers are reused here.
    """
    parsed = urlparse(h.path)
    if parsed.path != PREFIX and not parsed.path.startswith(PREFIX + "/"):
        return False
    path = parsed.path[len(PREFIX) :] or "/"
    try:
        if method == "GET":
            _get(h, path, parsed.query)
        else:
            _post(h, path)
    except (BrokenPipeError, ConnectionError, OSError):
        pass
    except Exception as exc:  # noqa: BLE001 - never let a handler kill the server
        try:
            h._json({"error": f"{type(exc).__name__}: {exc}"}, code=500)
        except Exception:
            pass
    return True


def _get(h, path: str, query: str) -> None:
    if path in ("/", "/index.html"):
        h._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
    elif path == "/api/runs":
        h._json({"runs": list_runs()})
    elif path == "/api/state":
        h._json(state_payload())
    elif path == "/api/doc":
        s = CURRENT
        h._json(s.read_doc() if s else {"content": "", "mtime": 0.0, "size": 0})
    elif path == "/api/stream":
        _sse(h)
    elif path == "/api/file":
        data = _workspace_image((parse_qs(query).get("path") or [""])[0])
        if data is None:
            h._send(404, b"not found", "text/plain")
        else:
            _send_image(h, *data)
    else:
        h._send(404, b"not found", "text/plain")


def _post(h, path: str) -> None:
    if path == "/api/select":
        try:
            h._json(select_run(h._read_body().get("run") or ""))
        except (ValueError, RuntimeError) as exc:
            h._json({"error": str(exc)}, code=400)
        return
    if path == "/api/draft_all":
        return h._json(draft_all(dry=bool(h._read_body().get("dry"))))
    if path == "/api/reset_all":
        try:
            return h._json(reset_all())
        except RuntimeError as exc:
            return h._json({"error": str(exc)}, code=409)
    s = CURRENT
    if s is None:
        return h._json({"error": "no run selected"}, code=409)
    if path == "/api/chat":
        try:
            s.start_turn((h._read_body().get("message") or "").strip())
        except (ValueError, RuntimeError) as exc:
            return h._json({"error": str(exc)}, code=409)
        h._json({"ok": True})
    elif path == "/api/doc":
        content = h._read_body().get("content")
        if not isinstance(content, str):
            return h._json({"error": "missing content"}, code=400)
        try:
            meta = s.write_doc(content)
        except RuntimeError as exc:
            return h._json({"error": str(exc)}, code=409)
        h._json({"ok": True, **meta})
    elif path == "/api/reset":
        try:
            s.reset()
        except RuntimeError as exc:
            return h._json({"error": str(exc)}, code=409)
        h._json({"ok": True})
    elif path == "/api/stop":
        h._json({"ok": True, "killed": s.stop()})
    else:
        h._send(404, b"not found", "text/plain")


def _send_image(h, body: bytes, ctype: str) -> None:
    """Like the viewer's _send, but cacheable: figure URLs are versioned by
    ?v=<mtime>, so caching keeps the live preview from refetching images on
    every keystroke."""
    try:
        h.send_response(200)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", "max-age=86400")
        h.end_headers()
        h.wfile.write(body)
    except (BrokenPipeError, ConnectionError, OSError):
        pass


def _sse(h) -> None:
    """SSE: push the full studio payload whenever the cheap signature moves."""
    try:
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-store")
        h.send_header("Connection", "close")
        h.end_headers()
        h.wfile.flush()
    except (BrokenPipeError, ConnectionError, OSError):
        return
    # 0.9s between payloads while things change: mid-turn the agent log moves
    # every few hundred ms, and rebuilding + shipping the full payload at 0.4s
    # doubled the work for no visible smoothness gain.
    last_sig = None
    interval = 0.9
    deadline = time.monotonic() + 12 * 3600
    while time.monotonic() < deadline:
        try:
            sig = _cheap_sig()
        except Exception:  # noqa: BLE001 - keep the stream alive
            sig = ("err",)
        try:
            if sig != last_sig:
                last_sig = sig
                interval = 0.9
                try:
                    payload = (
                        _stream_payload()
                    )  # parses the transcript (only on change)
                except Exception as exc:  # noqa: BLE001
                    payload = {"error": f"{type(exc).__name__}: {exc}"}
                h.wfile.write(b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n")
            else:
                interval = min(interval * 1.4, 2.5)
                h.wfile.write(b": hb\n\n")
            h.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            return
        time.sleep(interval)


# --------------------------------------------------------------------------- #
# Embedded single-page UI
# --------------------------------------------------------------------------- #
INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blogpost Studio</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
/*__PALETTE__*/
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--fg);font:14px/1.55 var(--sans);display:flex;flex-direction:column}
::selection{background:rgba(122,162,247,.3)}
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{background:var(--panel3);border-radius:6px}
a{color:var(--accent)}
button{font:inherit;color:var(--fg);background:var(--panel2);border:1px solid var(--border);
  border-radius:6px;padding:6px 12px;cursor:pointer;transition:.12s}
button:hover:not(:disabled){border-color:var(--accent)}
button:disabled{opacity:.4;cursor:not-allowed}
button.primary{background:rgba(122,162,247,.14);border-color:rgba(122,162,247,.5)}
button.primary:hover:not(:disabled){background:rgba(122,162,247,.24)}
button.danger{background:rgba(247,118,142,.12);border-color:rgba(247,118,142,.4);color:var(--err)}

/* header */
/* 12px offsets put the nav pill at the exact spot it occupies in the viewer's
   sidebar, so it doesn't jump when switching pages. */
header{display:flex;align-items:center;gap:12px;padding:12px;background:var(--panel);
  border-bottom:1px solid var(--border);flex:0 0 auto;position:relative;z-index:20}
header .spacer{flex:1}

/* typing indicator: shows in the chat log while the agent works */
.turn.typing .body{padding:11px 13px}
.tdot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--assist);
  margin-right:5px;opacity:.3;animation:tblink 1.2s infinite}
.tdot:nth-child(2){animation-delay:.2s}
.tdot:nth-child(3){animation-delay:.4s}
@keyframes tblink{0%,100%{opacity:.25}50%{opacity:1}}

/* run picker */
.runpick{background:var(--panel2);border:1px solid var(--border);color:var(--muted);
  font-family:var(--mono);font-size:12px;padding:4px 10px;border-radius:6px;cursor:pointer;
  max-width:46vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;transition:.12s}
.runpick:hover{border-color:var(--accent);color:var(--fg)}
.picker{position:absolute;top:48px;left:100px;z-index:30;width:min(460px,82vw);background:var(--panel);
  border:1px solid var(--border);border-radius:10px;box-shadow:0 16px 48px rgba(0,0,0,.6);padding:8px;display:none}
.picker.show{display:block}
#pickerSearch{width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--border);
  border-radius:7px;padding:7px 10px;font:13px/1.4 var(--sans);margin-bottom:6px;outline:none}
#pickerSearch:focus{border-color:var(--accent)}
.pickerList{max-height:52vh;overflow:auto;display:flex;flex-direction:column;gap:1px}
.runitem{display:flex;align-items:baseline;gap:10px;text-align:left;background:transparent;
  border:1px solid transparent;border-radius:6px;padding:7px 9px;cursor:pointer;width:100%;color:var(--fg)}
.runitem:hover{background:var(--panel2);border-color:var(--border)}
.runitem.cur{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.runitem .rn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:600}
.runitem .rt{color:var(--faint);font-size:10px;white-space:nowrap;font-family:var(--mono)}
.runitem .rt b{color:var(--ok);font-weight:600}
.runitem.disabled{opacity:.45;cursor:not-allowed}
.runitem.disabled:hover{background:transparent;border-color:transparent}
/* phase tabs + folder labels: same visual language as the viewer's overview */
.phase-tabs{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:2px 2px 8px}
.phase-tab{border:1px solid var(--border);background:var(--panel2);color:var(--muted);
  border-radius:7px;padding:5px 10px;font-size:12px;font-weight:700;cursor:pointer;transition:.12s}
.phase-tab:hover{border-color:var(--accent);color:var(--fg)}
.phase-tab.active{border-color:var(--accent);background:var(--panel3);color:var(--fg)}
.phase-tab .num{color:var(--faint);font-weight:600;margin-left:4px}
.dgroup{font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:var(--faint);
  font-weight:700;margin:10px 4px 3px}
.dgroup:first-child{margin-top:2px}
.muted{color:var(--muted);padding:14px;text-align:center;font-size:12.5px}
.pickerFoot{display:flex;align-items:center;gap:8px;padding:7px 6px 3px;border-top:1px solid var(--border);margin-top:6px}
.pickerFoot .spacer{flex:1}
.pickerOpt{display:flex;align-items:center;gap:6px;color:var(--faint);font-size:11px;
  font-family:var(--mono);cursor:pointer;user-select:none}
.pickerOpt input{accent-color:var(--accent)}
.mini2{font-size:11px;padding:3px 9px}

main{flex:1;display:flex;min-height:0}
body.noselect #chat{display:none}            /* no chat until a run is picked */
body.noselect .docbar{opacity:.4;pointer-events:none}

/* chat (right side) — same turn/role/collapsible language as the agent viewer */
#chat{width:40%;min-width:360px;display:flex;flex-direction:column;border-left:1px solid var(--border);background:var(--bg)}
#log{flex:1;overflow:auto;padding:14px 16px 4px}
.turn{margin:0 0 12px;border:1px solid var(--border);border-radius:10px;overflow:hidden;background:var(--panel)}
.turn .role{font-size:10px;text-transform:uppercase;letter-spacing:.6px;padding:6px 13px;font-weight:700;border-bottom:1px solid var(--border)}
.turn.user .role{color:var(--user)} .turn.assistant .role{color:var(--assist)}
.turn.user{border-left:3px solid var(--user)} .turn.assistant{border-left:3px solid var(--assist)}
.turn .body{padding:4px 13px 10px}
/* consecutive messages from the same speaker read as one group */
.turn.cont{margin-top:-7px}
.turn.cont .body{padding-top:10px}
.md{line-height:1.6;word-wrap:break-word}
.md>:first-child{margin-top:0}.md>:last-child{margin-bottom:0}
.md p{margin:8px 0}.md ul,.md ol{margin:8px 0;padding-left:22px}.md li{margin:3px 0}
.md h1,.md h2,.md h3,.md h4{margin:14px 0 6px;line-height:1.3;font-weight:700;font-size:1.05em}
.md pre{background:var(--code-bg);border:1px solid var(--border);border-radius:7px;padding:9px;overflow:auto;font-family:var(--mono);font-size:12.5px}
.md code{font-family:var(--mono);font-size:.9em}
.md p code,.md li code{background:var(--panel2);padding:.1em .35em;border-radius:4px}
details.aux{margin:8px 0;border:1px solid var(--border);border-radius:8px;background:var(--panel2);font-size:12.5px}
details.aux>summary{cursor:pointer;padding:6px 11px;font-weight:600;list-style:none;display:flex;gap:8px;align-items:center;color:var(--muted)}
details.aux>summary::-webkit-details-marker{display:none}
details.aux>summary::before{content:"▸";color:var(--muted)}
details.aux[open]>summary::before{content:"▾"}
details.think>summary{color:var(--think)} details.tool>summary{color:var(--tool)} details.sub>summary{color:var(--accent)}
details.aux.err>summary{color:var(--err)}
details.aux .arg{color:var(--faint);font-family:var(--mono);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
details.aux .body2{padding:0 11px 10px;white-space:pre-wrap;font-family:var(--mono);font-size:11.5px;color:var(--muted);max-height:300px;overflow:auto}
details.think .body2{color:#c8bfe7;font-style:italic}
.empty{color:var(--muted);text-align:center;margin-top:16vh;padding:0 24px;line-height:1.6}
.empty button{margin-top:14px}

/* composer */
#composer{flex:0 0 auto;border-top:1px solid var(--border);padding:10px 12px;background:var(--panel)}
#composer .row{display:flex;gap:8px;align-items:flex-end}
#msg{flex:1;resize:none;background:var(--bg);color:var(--fg);border:1px solid var(--border);
  border-radius:8px;padding:9px 11px;font:14px/1.5 var(--sans);max-height:180px;min-height:42px;outline:none}
#msg:focus{border-color:var(--accent)}

/* document (left side) — a calm, writerly editor with an Edit/Preview toggle */
#doc{flex:1;display:flex;flex-direction:column;min-width:0;background:var(--bg)}
.docbar{display:flex;align-items:center;gap:10px;padding:7px 14px;border-bottom:1px solid var(--border);background:var(--panel)}
#viewtoggle{font-size:12px;padding:4px 13px;color:var(--muted)}
#viewtoggle:hover:not(:disabled){color:var(--fg)}
/* destructive + rare: quiet until you aim at it */
#delbtn{font-size:12px;padding:4px 13px;background:transparent;border-color:transparent;color:var(--faint)}
#delbtn:hover:not(:disabled){background:rgba(247,118,142,.12);border-color:rgba(247,118,142,.4);color:var(--err)}
.docbar .spacer{flex:1}
.meta{color:var(--faint);font-size:11px;font-family:var(--mono);font-variant-numeric:tabular-nums}
.meta .dot{opacity:.5;margin:0 2px}
#docview{flex:1;display:flex;min-height:0;overflow:hidden}
.pane{flex:1;min-width:0}
.editpane{display:flex;overflow:hidden}
.previewpane{overflow:auto}
#docview.edit .previewpane{display:none}
#docview.view .editpane{display:none}
/*__EDITOR_CSS__*/
/*__PREVIEW_CSS__*/

/* image lightbox (as in the agent viewer) */
.lightbox{position:fixed;inset:0;z-index:9999;background:rgba(3,5,10,.88);display:flex;
  align-items:center;justify-content:center;padding:40px}
.lightbox[hidden]{display:none}
.lightbox img{max-width:95vw;max-height:90vh;object-fit:contain;background:#fff;border-radius:6px;
  box-shadow:0 14px 45px rgba(0,0,0,.55)}

.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--panel3);
  color:var(--err);border:1px solid var(--border);padding:8px 14px;border-radius:8px;opacity:0;
  transition:opacity .2s;pointer-events:none;z-index:9999;font-size:13px}
.toast.show{opacity:1}
</style>
</head>
<body>
<header>
  <nav class="appnav"><a href="/">🔎 Runs</a><a class="on" href="/studio">📝 Studio</a><a href="/proposals">🗒 Proposals</a></nav>
  <button class="runpick" id="runpick">Select a run ▾</button>
  <span class="spacer"></span>
  <span class="meta" id="cost" title="model spend in this studio conversation"></span>
</header>
<div class="picker" id="picker">
  <input id="pickerSearch" placeholder="Filter runs…" autocomplete="off">
  <div class="phase-tabs" id="pickerTabs"></div>
  <div class="pickerList" id="pickerList"></div>
  <div class="pickerFoot">
    <label class="pickerOpt"><input type="checkbox" id="showGoal"> show goal runs</label>
    <span class="spacer"></span>
    <button class="mini2" id="draftAllBtn" title="Start /draft for every completed run that has no draft yet, in parallel">✍ Draft missing</button>
    <button class="mini2 danger" id="delAllBtn" title="Delete every draft, its figures, and its conversation">Delete all drafts</button>
  </div>
</div>
<main>
  <section id="doc">
    <div class="docbar">
      <button id="viewtoggle">✎ Edit</button>
      <span class="spacer"></span>
      <span class="meta" id="meta"></span>
      <button class="danger" id="delbtn" title="Delete this run's draft, figures, and conversation">Delete draft</button>
    </div>
    <div id="docview" class="view">
      <div class="pane editpane"><div class="editwrap"><pre id="editorHL" aria-hidden="true"></pre><textarea id="editor" spellcheck="false"
        placeholder="The document appears here as you and the agent write it. Edit freely — changes autosave."></textarea></div></div>
      <div class="pane previewpane"><div id="preview"></div></div>
    </div>
  </section>
  <section id="chat">
    <div id="log"></div>
    <div id="composer">
      <div class="row">
        <textarea id="msg" placeholder="Ask for a passage, a fix, a figure… (/draft = write the whole post)"></textarea>
        <button class="danger" id="stopbtn" style="display:none" title="Stop the agent's current turn">■ Stop</button>
        <button class="primary" id="send">Send</button>
      </div>
    </div>
  </section>
</main>
<div class="toast" id="toast"></div>
<div class="lightbox" id="lightbox" hidden><img></div>
<script>
const $ = s => document.querySelector(s);
const API = "/studio/api";
let selected=false, running=false, docMtime=-1, editorDirty=false, mode="view", lastTurnsKey="";
let lastTurns=[];                 // last server-rendered turns (without optimistic ones)
let queue=[], sending=false, sentBase=0;  // outgoing message queue (send while the agent works)
const autoOpened=new Set();       // details we opened for the live stream (vs. user-opened)

marked.setOptions({breaks:true, gfm:true});

function toast(m){const t=$("#toast");t.textContent=m;t.classList.add("show");
  clearTimeout(toast._t);toast._t=setTimeout(()=>t.classList.remove("show"),3200);}

function rewriteImgs(root){
  // Render any image the document points at by a relative path (e.g.
  // final_plots/fig1.png or ./final_plots/fig1.png) straight from the workspace.
  root.querySelectorAll("img").forEach(img=>{
    const s=img.getAttribute("src")||"";
    if(!s || /^(https?:|data:|\/)/i.test(s)) return;
    const rel=s.replace(/^\.\//,"");
    img.src=API+"/file?path="+encodeURIComponent(rel)+"&v="+Math.floor(docMtime||0);
    img.loading="lazy";
    img.onerror=()=>{img.replaceWith(Object.assign(document.createElement("em"),
      {textContent:"⚠ missing image: "+rel,style:"color:var(--faint)"}));};
  });
}
function mdToHtml(text){
  const div=document.createElement("div");
  div.innerHTML=marked.parse(text||"");
  rewriteImgs(div);
  return div.innerHTML;
}

//__HIGHLIGHT_JS__
function syncHL(){
  if(!hl) return;
  hl.innerHTML=highlightMarkdown(editor.value)+"\n";   // trailing \n keeps last line height in sync
  hl.scrollTop=editor.scrollTop; hl.scrollLeft=editor.scrollLeft;
}

// ---- chat rendering ----
function argSummary(name,args){
  if(args==null) return "";
  if(typeof args!=="object") return String(args).slice(0,160);
  const a=args;
  const pick=a.path||a.file_path||a.file||a.filename;
  if(name==="bash"||name==="shell") return (a.command||a.cmd||"").slice(0,160);
  if(pick) return String(pick);
  try{return JSON.stringify(a).slice(0,160);}catch(e){return "";}
}
// k is a stable "turn.block" key so open/closed state survives re-renders;
// live marks the block currently streaming in from the agent's json stdout.
function blockHtml(b,k,live){
  const at=` data-k="${k}"${live?' data-live="1"':''}`;
  if(b.kind==="text") return `<div class="md">${mdToHtml(b.text)}</div>`;
  if(b.kind==="thinking")
    return `<details class="aux think"${at}><summary>thinking</summary>`
      +`<div class="body2">${esc(b.text)}</div></details>`;
  if(b.kind==="subagent")
    return `<details class="aux sub"${at}><summary>subagent: ${esc(b.agent)}<span class="arg">${esc(b.task).slice(0,80)}</span></summary>`
      +`<div class="body2">${esc((b.result&&b.result.text)||"")}</div></details>`;
  if(b.kind==="tool"){
    const err=b.result&&b.result.isError?" err":"";
    const res=b.result?esc(b.result.text||""):"(running…)";
    return `<details class="aux tool${err}"${at}><summary>${esc(b.name)}<span class="arg">${esc(argSummary(b.name,b.args))}</span></summary>`
      +`<div class="body2">${res}</div></details>`;
  }
  return "";
}
function esc(s){return (s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}

// The transcript only updates at message boundaries, so this bubble is the
// signal that a (possibly long) turn is in flight. cont = joins an agent group.
const typingHtml=cont=>`<div class="turn assistant typing${cont?' cont':''}">${cont?'':'<div class="role">Agent</div>'}`
  +`<div class="body"><span class="tdot"></span><span class="tdot"></span><span class="tdot"></span></div></div>`;

function renderChat(turns){
  // Once the server records the message we sent, drop it from the optimistic queue.
  if(sending && turns.length>sentBase){ queue.shift(); sending=false; }
  lastTurns=turns;
  const display = queue.length
    ? turns.concat(queue.map(m=>({role:"user",blocks:[{kind:"text",text:m}]})))
    : turns;
  // Key on content size too: a live thinking/text block grows without the
  // turn or block count changing, and the re-render must still happen.
  const key=JSON.stringify(display.map(t=>[t.role,t.blocks.length,!!t.live,
    t.blocks.reduce((n,b)=>n+(b.text||"").length+((b.result&&b.result.text)||"").length,0)]))+"|"+queue.join("\x01")+"|"+(running?1:0);
  if(key===lastTurnsKey) return; // avoid clobbering scroll/details when nothing changed
  lastTurnsKey=key;
  const log=$("#log");
  const atBottom=log.scrollHeight-log.scrollTop-log.clientHeight<80;
  if(!display.length && !running){
    log.innerHTML=`<div class="empty">No conversation yet.<br>Investigate first and write together, `
      +`or have the agent draft the whole post on its own and take over from there.`
      +`<br><button class="primary" id="kick">Investigate this run</button> `
      +`<button class="primary" id="draftnow">Draft the full post</button></div>`;
    $("#kick").onclick=()=>sendCommand("/kickoff");
    $("#draftnow").onclick=()=>sendCommand("/draft");
    return;
  }
  const parts=display.map((t,ti)=>{
    const who=t.role==="user"?"You":"Agent";
    const cont=ti>0&&display[ti-1].role===t.role;  // same speaker: group the bubbles
    const last=t.live?t.blocks.length-1:-1;   // the block still streaming in
    const body=t.role==="user"
      ? `<div class="md">${mdToHtml(t.blocks.map(b=>b.text||"").join("\n"))}</div>`
      : t.blocks.map((b,bi)=>blockHtml(b,ti+"."+bi,bi===last)).join("");
    return `<div class="turn ${t.role}${cont?' cont':''}">${cont?'':`<div class="role">${who}</div>`}<div class="body">${body}</div></div>`;
  });
  if(running)  // after the turn in flight, before queued msgs
    parts.splice(turns.length,0,typingHtml(turns.length>0&&turns[turns.length-1].role==="assistant"));
  // innerHTML replacement resets every <details>; restore what the user had,
  // and auto-open a NEWLY appeared live block so its stream is visible.
  const known=new Set(), openSet=new Set();
  log.querySelectorAll("details[data-k]").forEach(d=>{known.add(d.dataset.k); if(d.open) openSet.add(d.dataset.k);});
  log.innerHTML=parts.join("");
  log.querySelectorAll("details[data-k]").forEach(d=>{
    const k=d.dataset.k;
    if(known.has(k)){
      // a block we auto-opened collapses again once the stream moves past it
      if(autoOpened.has(k)&&!d.dataset.live){autoOpened.delete(k); d.open=false;}
      else d.open=openSet.has(k);
    }else if(d.dataset.live){d.open=true; autoOpened.add(k);}
    if(d.open&&d.dataset.live){const b=d.querySelector(".body2"); if(b) b.scrollTop=b.scrollHeight;}
  });
  if(atBottom) log.scrollTop=log.scrollHeight;
}

// ---- document: live preview, autosave, scroll-synced split ----
const editor=$("#editor"), preview=$("#preview"), hl=$("#editorHL");

async function loadDoc(force){
  if(!selected) return;   // keep the "select a run" placeholder; nothing to load
  let d;
  try{ d=await (await fetch(API+"/doc")).json(); }
  catch(e){ return; }   // transient network error: the stream will retrigger us
  if(d.mtime===docMtime && !force) return;
  docMtime=d.mtime;
  preview.innerHTML=mdToHtml(d.content);
  // Don't stomp the caret while the human is typing; otherwise mirror the file
  // (this is how the agent's live edits stream into the editor mid-turn).
  if(!editorDirty && document.activeElement!==editor){ editor.value=d.content; syncHL(); }
  updateMeta();
}
function updateMeta(status){
  const n=(editor.value.match(/\S+/g)||[]).length;
  status = status || (editorDirty?"unsaved":(docMtime>0?"saved":""));
  $("#meta").innerHTML=(n?n.toLocaleString()+" words":"")+(status?` <span class="dot">·</span> ${status}`:"");
}
let saveTimer;
async function saveDoc(){
  clearTimeout(saveTimer);
  if(!editorDirty || running) return true;
  updateMeta("saving…");
  const d=await api(API+"/doc",{content:editor.value});
  if(!d){updateMeta();return false;}
  docMtime=d.mtime; editorDirty=false; updateMeta();
  return true;
}
function onEdit(){
  if(editor.readOnly) return;
  editorDirty=true;
  syncHL();                                     // re-highlight the edit layer
  preview.innerHTML=mdToHtml(editor.value);     // live preview as you type
  updateMeta();
  clearTimeout(saveTimer);
  if(!running) saveTimer=setTimeout(saveDoc,800);
}
function setMode(m){
  mode=m;
  $("#docview").className=m;
  // The button shows the action it performs, not the current state.
  $("#viewtoggle").textContent = m==="view" ? "✎ Edit" : "👁 Preview";
  if(m==="view") preview.innerHTML=mdToHtml(editor.value);
  else syncHL();   // entering edit: paint the highlight layer (it was display:none)
}
const toggleMode=()=>setMode(mode==="view"?"edit":"view");

// ---- controls / state ----
function refreshControls(){
  // You can always type — messages queue while the agent is working — and Stop
  // appears next to Send only when there is a turn to stop.
  $("#send").disabled = $("#msg").disabled = !selected;
  $("#stopbtn").style.display = running ? "" : "none";
  $("#delbtn").disabled = !selected || running;
  // You can edit the document whenever a run is selected — even while the agent works.
  editor.readOnly = !selected;
}
function autosize(){const t=$("#msg");t.style.height="auto";t.style.height=Math.min(t.scrollHeight,180)+"px";}

// ---- server calls ----
async function api(url,body){
  let r;
  try{
    r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},
      body:body?JSON.stringify(body):undefined});
  }catch(e){ toast("network error — retry: "+e.message); return null; }
  const d=await r.json().catch(()=>({}));
  if(!r.ok){toast(d.error||"failed");return null;}
  return d;
}
function send(){
  if(!selected) return;
  const text=$("#msg").value.trim();
  if(!text) return;
  $("#msg").value=""; autosize();
  sendCommand(text);
}
// Queue a message (or a /command like /draft — the server expands those into
// their full prompts, so the transcript records what the agent actually got).
function sendCommand(text){
  queue.push(text);
  renderChat(lastTurns);   // show the queued message instantly
  pump();                  // sent now if idle, otherwise when the current turn ends
}
// Dispatch the next queued message when the agent is free. Only one turn runs at
// a time, so messages sent mid-turn wait here and go out as soon as it finishes.
async function pump(){
  if(sending || running || !selected || !queue.length) return;
  sending=true; sentBase=lastTurns.length;  // claim the slot synchronously (no double-send)
  if(editorDirty) await saveDoc();          // flush the human's edits before the agent's turn
  const ok=await api(API+"/chat",{message:queue[0]});
  if(ok){ running=true; renderChat(lastTurns); refreshControls(); }  // show typing bubble now
  else { sending=false; queue.shift(); renderChat(lastTurns); }  // send failed → drop it
}
const stop=()=>fetch(API+"/stop",{method:"POST"}).catch(()=>{});

function freshUi(){
  docMtime=-1; lastTurnsKey=""; lastTurns=[]; queue=[]; sending=false; autoOpened.clear();
  editorDirty=false;
}
async function deleteDraft(){
  if(!selected || running) return;
  if(!confirm("Delete this run's draft, figures, and conversation? This cannot be undone.")) return;
  if(!await api(API+"/reset")) return;
  freshUi();
  await loadDoc(true);
  renderChat([]);          // back to the investigate / draft choice
  refreshControls();
}
async function deleteAllDrafts(){
  if(!confirm("Delete ALL studio drafts, figures, and conversations — for every run? This cannot be undone.")) return;
  const r=await api(API+"/reset_all");
  if(!r) return;
  toast(`deleted ${r.deleted} draft workspace(s)`);
  freshUi();
  await loadDoc(true);
  renderChat([]);
  refreshControls();
  allRuns=[]; openPicker();   // refresh badges
}
async function draftAllMissing(){
  const d=await api(API+"/draft_all",{dry:true});
  if(!d) return;
  if(!d.targets.length){ toast("every completed run already has a draft"); return; }
  if(!confirm(`Start /draft for ${d.targets.length} run(s), in parallel?\n\n${d.targets.join("\n")}\n\nEach one is a full agent turn (investigate the run, write the post).`)) return;
  const r=await api(API+"/draft_all",{});
  if(!r) return;
  toast(`started ${r.started.length} draft(s) — they run in the background`);
  allRuns=[]; openPicker();   // refresh: rows now show “drafting…”
}

// ---- run picker ----
let allRuns=[], showGoal=false;   // goal runs are hidden unless toggled on
async function openPicker(){
  $("#picker").classList.add("show");
  $("#pickerSearch").value=""; $("#pickerSearch").focus();
  if(!allRuns.length){ $("#pickerTabs").innerHTML=""; $("#pickerList").innerHTML='<div class="muted">loading runs…</div>'; }
  try{ allRuns=(await (await fetch(API+"/runs")).json()).runs||[]; }
  catch(e){ allRuns=[]; toast("network error: "+e.message); }
  drawRuns();
}
const closePicker=()=>$("#picker").classList.remove("show");
let pickerPhase="Completed";   // like the viewer's overview tabs; Completed = openable
function drawRuns(){
  const q=$("#pickerSearch").value.toLowerCase();
  const pool=allRuns.filter(r=>(showGoal||r.mode!=="goal") && r.name.toLowerCase().includes(q));
  const counts={Completed:0,Active:0,Failed:0};
  pool.forEach(r=>{ if(counts[r.phase]!=null) counts[r.phase]++; });
  if(!counts[pickerPhase]) pickerPhase = counts.Completed?"Completed":(counts.Active?"Active":"Failed");
  $("#pickerTabs").innerHTML=["Completed","Active","Failed"].map(ph=>
    `<button class="phase-tab${ph===pickerPhase?' active':''}" data-ph="${ph}">${ph} <span class="num">${counts[ph]}</span></button>`).join("");
  $("#pickerTabs").querySelectorAll(".phase-tab").forEach(b=>b.onclick=()=>{pickerPhase=b.dataset.ph;drawRuns();});

  const rows=pool.filter(r=>r.phase===pickerPhase);
  const list=$("#pickerList");
  if(!rows.length){ list.innerHTML=`<div class="muted">no ${pickerPhase.toLowerCase()} runs</div>`; return; }
  let g=null, html="";
  for(const r of rows){
    if((r.group||"")!==g){ g=r.group||""; html+=`<div class="dgroup">${esc(g||"runs")}</div>`; }
    const sel=r.selectable!==false;
    html+=`<button class="runitem${r.current?' cur':''}${sel?'':' disabled'}" data-path="${esc(r.path)}"`
      +`${sel?'':' disabled title="only finished runs can be opened"'}>`
      +`<span class="rn">${esc(r.name)}</span>`
      +`<span class="rt">${esc(r.mode||"")}${r.drafting?" · <i>drafting…</i>":r.started?" · <b>draft</b>":""}</span></button>`;
  }
  list.innerHTML=html;
  list.querySelectorAll(".runitem:not(.disabled)").forEach(b=>b.onclick=()=>chooseRun(b.dataset.path));
}
async function chooseRun(path){
  const rp=$("#runpick"), prev=rp.textContent;
  rp.textContent="opening…";   // selecting stages the workspace; can take a moment
  const s=await api(API+"/select",{run:path});
  if(!s){ rp.textContent=prev; return; }
  closePicker();
  freshUi();
  applyState(s);
  await loadDoc(true);
  bindStream();
  // A fresh run shows the empty-state choice: investigate first, or /draft it all.
}

// ---- state + live stream ----
function applyState(s){
  selected=!!s.selected;
  document.body.classList.toggle("noselect",!selected);
  $("#runpick").textContent=selected?(s.run_name+" ▾"):"Select a run ▾";
  document.title=selected?("Studio · "+s.run_name):"Blogpost Studio";
  running=!!s.running;
  refreshControls();
  if(!selected){ queue=[]; sending=false; renderChat([]); $("#cost").textContent="";
    preview.innerHTML='<div class="empty">Select a run to begin co-writing.</div>'; editor.value=""; syncHL(); updateMeta(); }
}
let es=null;
function bindStream(){
  if(es) es.close();
  es=new EventSource(API+"/stream");
  es.onmessage=ev=>{
    const d=JSON.parse(ev.data);
    if(d.error){toast(d.error);return;}
    if(!d.selected){ if(selected) applyState({selected:false}); return; }
    const was=running; running=d.running;
    renderChat(d.turns);   // may shift the queue / clear `sending` if our msg was recorded
    if(d.doc && d.doc.mtime!==docMtime) loadDoc(false);
    $("#cost").textContent = d.cost>0.005 ? "$"+d.cost.toFixed(2) : "";
    refreshControls();
    if(was && !running){
      // if a turn ended but never recorded our sent message, drop it so we don't wedge
      if(sending){ if(lastTurns.length<=sentBase) queue.shift(); sending=false; }
      if(editorDirty) saveDoc();
      pump();              // start the next queued message, if any
    }
  };
  es.onerror=()=>{};
}

// ---- wiring ----
$("#send").onclick=send;
$("#stopbtn").onclick=stop;
$("#delbtn").onclick=deleteDraft;
$("#runpick").onclick=()=>$("#picker").classList.contains("show")?closePicker():openPicker();
$("#pickerSearch").addEventListener("input",drawRuns);
$("#showGoal").onchange=e=>{showGoal=e.target.checked;drawRuns();};
$("#draftAllBtn").onclick=draftAllMissing;
$("#delAllBtn").onclick=deleteAllDrafts;
document.addEventListener("click",e=>{
  // isConnected guard: a click on a re-rendered element (e.g. a phase tab)
  // bubbles here detached, and closest() would wrongly read it as "outside".
  if(e.target.isConnected && !e.target.closest("#picker") && !e.target.closest("#runpick")) closePicker();
  if(e.target.tagName==="IMG" && e.target.closest("#preview,#log")){
    $("#lightbox img").src=e.target.src; $("#lightbox").hidden=false;
  }
});
$("#lightbox").onclick=()=>$("#lightbox").hidden=true;
document.addEventListener("keydown",e=>{ if(e.key==="Escape") closePicker(); });
$("#viewtoggle").onclick=toggleMode;
$("#msg").addEventListener("input",autosize);
$("#msg").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send();}});
editor.addEventListener("input",onEdit);
editor.addEventListener("scroll",()=>{ if(hl){hl.scrollTop=editor.scrollTop;hl.scrollLeft=editor.scrollLeft;} });
editor.addEventListener("keydown",e=>{
  if(e.key==="Tab"){e.preventDefault();const c=editor.selectionStart;
    editor.setRangeText("  ",c,editor.selectionEnd,"end");onEdit();}
  else if((e.metaKey||e.ctrlKey)&&e.key==="s"){e.preventDefault();saveDoc();}
});
addEventListener("beforeunload",()=>{
  if(editorDirty && !running && navigator.sendBeacon)
    navigator.sendBeacon(API+"/doc",new Blob([JSON.stringify({content:editor.value})],{type:"application/json"}));
});

async function init(){
  setMode("view");
  let st={selected:false};
  try{ st=await (await fetch(API+"/state")).json(); }
  catch(e){ toast("network error: "+e.message); }
  applyState(st);
  await loadDoc(true);
  bindStream();
  // Deep link: /studio?run=<path> (e.g. from the agent viewer) selects that run.
  const pre=new URLSearchParams(location.search).get("run");
  if(pre && !selected) await chooseRun(pre);
  else if(!selected) openPicker();
}
init();
</script>
</body>
</html>
"""

# Shared palette + markdown-editor pieces come from src.theme (single source).
INDEX_HTML = (
    INDEX_HTML.replace("/*__PALETTE__*/", PALETTE_CSS)
    .replace("/*__EDITOR_CSS__*/", EDITOR_CSS)
    .replace("/*__PREVIEW_CSS__*/", PREVIEW_CSS)
    .replace("//__HIGHLIGHT_JS__", HIGHLIGHT_JS)
)
