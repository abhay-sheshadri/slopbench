"""Blue Team tab — mounted under ``/blueteam`` by the agent viewer.

Pick a finished run and watch a read-only sabotage auditor explore it live (the
same agent as ``experiments/08_automated_blue_teaming`` — run mounted READ-ONLY at
/source, the prompt from :mod:`src.blue_team`, launched non-blocking and streamed
through the lens job machinery). The agent ends with a ``json`` block of
concern-labelled findings, which the page renders as colour-coded, sorted cards.

Like the studio, this also persists and manages audits:
  - every audit is SAVED to ``outputs/08_automated_blue_teaming/<run>/`` the same way
    the blogpost agent saves (``blue_team_report.md`` + ``blue_team_agent_session.jsonl``),
    written by a background daemon so it persists even if you close the tab;
  - **Run all** kicks off ``run_all.sh`` over every completed run;
  - **Delete** / **Delete all** remove saved audits.

No server of its own: :func:`handle` is called by the viewer's request handler.
"""

from __future__ import annotations

import collections
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src import agent_viewer as av
from src.theme import (
    APP_JS,
    CHAT_CSS,
    CONTROLS_CSS,
    PALETTE_CSS,
    PROGRESS_CSS,
    PROGRESS_JS,
    TRANSCRIPT_JS,
)

PREFIX = "/blueteam"
BT_DIR = av.OUTPUTS_DIR / "08_automated_blue_teaming"
REPORT = "blue_team_report.md"
SESSION_OUT = "blue_team_agent_session.jsonl"
LEVELS = ["critical", "high", "medium", "low"]
# Run all = enqueue the SAME streamable per-run jobs (not a separate run_all.sh),
# so every audit in a batch streams + persists + re-attaches like a single one.
BATCH_CAP = max(1, int(os.environ.get("BLUE_TEAM_BATCH_CONCURRENCY", "10")))
_QUEUE: "collections.deque[str]" = collections.deque()  # rels waiting (batch)
_BATCH_SET: set[str] = set()  # rels belonging to the current batch

_LOCK = threading.Lock()
_JOBS: dict[str, str] = {}  # every live audit (single or batch): job -> run rel
_PERSISTED: set[str] = set()
_PERSIST_TRIES: dict[str, int] = (
    {}
)  # job -> persist attempts (session file can lag exit)


def _name(rel: str) -> str:
    return (rel or "").rstrip("/").split("/")[-1]


def _saved_dir(rel: str) -> Path:
    return BT_DIR / _name(rel)


# --------------------------------------------------------------------------- #
# Parsing saved reports / transcripts into concern-labelled findings
# --------------------------------------------------------------------------- #
def _findings_from_text(text: str):
    for b in reversed(re.findall(r"```json\s*([\s\S]*?)```", text or "")):
        try:
            o = json.loads(b)
            if isinstance(o, dict) and isinstance(o.get("findings"), list):
                return o["findings"]
        except Exception:
            pass
    return None


def _orient_from_text(text: str) -> str:
    i = (text or "").find("```json")
    head = (text[:i] if i >= 0 else text).strip()
    return head[-1500:]


def _worst(findings) -> str | None:
    for lvl in LEVELS:
        if any((f.get("concern") or "").lower() == lvl for f in findings):
            return lvl
    return None


def saved_summary(rel: str) -> dict | None:
    p = _saved_dir(rel) / REPORT
    if not p.exists():
        return None
    f = _findings_from_text(p.read_text(errors="replace")) or []
    return {"count": len(f), "worst": _worst(f), "mtime": p.stat().st_mtime}


def saved_full(rel: str) -> dict:
    p = _saved_dir(rel) / REPORT
    if not p.exists():
        return {"exists": False}
    t = p.read_text(errors="replace")
    return {
        "exists": True,
        "orient": _orient_from_text(t),
        "findings": _findings_from_text(t) or [],
        "mtime": p.stat().st_mtime,
    }


def saved_transcript(rel: str) -> dict:
    """The saved agent exploration transcript (assistant turns) for a run, if any."""
    p = _saved_dir(rel) / SESSION_OUT
    if not p.exists():
        return {"turns": []}
    turns = [
        t
        for t in av.parse_session(p.read_text(errors="replace")).get("turns", [])
        if t.get("role") == "assistant"
    ]
    return {"turns": turns}


# --------------------------------------------------------------------------- #
# Persistence — save finished live audits exactly like the blogpost agent does
# --------------------------------------------------------------------------- #
def _turn_text(turn) -> str:
    return "\n".join(
        b.get("text", "") for b in (turn.get("blocks") or []) if b.get("kind") == "text"
    )


def _report_text(turns) -> str:
    """Pick the report body from assistant turns.

    Prefer the last turn that actually carries a parseable ```json findings
    deliverable (so the saved report is the findings, not the whole log). If no
    turn has one, fall back to the full transcript text — never gate on only the
    very last turn, which silently dropped findings emitted a turn earlier.
    """
    for t in reversed(turns):
        ttext = _turn_text(t)
        if "```json" in ttext and _findings_from_text(ttext):
            return ttext
    return "\n".join(_turn_text(t) for t in turns)


def _persist(job: str, rel: str) -> None:
    if job in _PERSISTED:
        return
    info = av._LENS_JOBS.get(job)
    if info is None or info["proc"].poll() is None:
        return  # gone or still running
    if info.get("followup_pending"):
        return  # first pass done; clarity follow-up not started/finished yet
    try:
        turns = av.lens_transcript(job).get("turns", [])
        report = _report_text(turns)
        # The session jsonl can lag a beat behind process exit. If the transcript
        # is still empty, leave the job unpersisted so the daemon retries instead
        # of freezing an empty "(no findings produced)" report (and losing real
        # findings to a race). Give up after a few ticks for genuinely-empty runs.
        if not report.strip():
            n = _PERSIST_TRIES.get(job, 0) + 1
            _PERSIST_TRIES[job] = n
            if n < 6:
                return
        out = _saved_dir(rel)
        out.mkdir(parents=True, exist_ok=True)
        (out / REPORT).write_text(report or "(no findings produced)")
        sess = info["session"]
        if sess.exists():
            shutil.copyfile(sess, out / SESSION_OUT)
    except Exception:
        pass
    _PERSISTED.add(job)
    _PERSIST_TRIES.pop(job, None)
    with _LOCK:
        _JOBS.pop(job, None)


def _running_rels() -> set[str]:
    return set(_JOBS.values())


def _start_one(rel: str) -> str | None:
    """Spawn a streamable per-run audit and register it. Returns the job id."""
    if rel in _running_rels():
        return None
    r = av.start_blue_team(rel)
    job = r.get("job")
    if job:
        _PERSISTED.discard(job)
        _PERSIST_TRIES.pop(job, None)
        with _LOCK:
            _JOBS[job] = rel
    return job


def _advance_queue() -> None:
    """Start queued batch audits up to the concurrency cap (total live audits)."""
    while _QUEUE and len(_JOBS) < BATCH_CAP:
        rel = _QUEUE.popleft()
        if rel in _running_rels():
            continue
        _start_one(rel)


def _pump() -> None:
    """Background daemon: persist finished audits (even with no client polling) and
    keep the Run-all queue flowing."""
    while True:
        for job, rel in list(_JOBS.items()):
            info = av._LENS_JOBS.get(job)
            if info is None or info["proc"].poll() is not None:
                _persist(job, rel)
        _advance_queue()
        time.sleep(3)


threading.Thread(target=_pump, daemon=True).start()


# --------------------------------------------------------------------------- #
# Batch (Run all) + lifecycle — one unified, streamable audit path for all runs
# --------------------------------------------------------------------------- #
def batch_running() -> bool:
    return bool(_QUEUE) or bool(_BATCH_SET & _running_rels())


def batch_status() -> dict:
    return {
        "batch": batch_running(),
        "active": len(_BATCH_SET & _running_rels()),
        "queued": len(_QUEUE),
    }


def list_runs() -> dict:
    out = []
    job_by_rel = {r: j for j, r in _JOBS.items()}  # the active audit job per run
    queued = set(_QUEUE)
    for r in av.list_runs_overview():
        if r.get("type") and r["type"] != "run":
            continue
        rel = r.get("path")
        out.append(
            {
                "path": rel,
                "name": r.get("name"),
                "status": r.get("status"),
                "live": bool(r.get("live")),
                "audit": saved_summary(rel),
                "running": rel in job_by_rel,
                "queued": rel in queued,
                "job": job_by_rel.get(rel),  # re-attach the live stream on click
            }
        )
    out.sort(key=lambda x: (x["audit"] is None, -(x["audit"] or {}).get("mtime", 0)))
    return {"items": out, **batch_status()}


def start(rel: str) -> dict:
    """Start (or re-run) a single streamable audit. Coexists with a batch."""
    if rel in _running_rels() or rel in _QUEUE:
        return {"error": "this run is already queued or being audited"}
    job = _start_one(rel)
    return {"job": job} if job else {"error": "failed to start audit"}


def start_all() -> dict:
    """Queue a fresh audit for every completed (non-live) run. Each becomes a
    normal streamable job, started up to BATCH_CAP at a time."""
    if batch_running():
        return {"error": "a batch is already running"}
    rels = [
        r["path"]
        for r in list_runs()["items"]
        if r["status"] == "completed" and not r["live"]
    ]
    if not rels:
        return {"error": "no completed runs to audit"}
    _BATCH_SET.clear()
    _BATCH_SET.update(rels)
    _QUEUE.clear()
    _QUEUE.extend(r for r in rels if r not in _running_rels())
    _advance_queue()
    return {"ok": True, "queued": len(rels)}


def stop_all() -> dict:
    _QUEUE.clear()
    for job, rel in list(_JOBS.items()):
        if rel in _BATCH_SET:
            cancel(job)
    _BATCH_SET.clear()
    return {"ok": True}


def cancel(job: str) -> dict:
    av.cancel_lens(job)
    _PERSISTED.add(job)  # don't save a cancelled, partial audit
    with _LOCK:
        _JOBS.pop(job, None)
    return {"ok": True}


def delete(rel: str) -> dict:
    if batch_running() or rel in _running_rels():
        return {"error": "an audit for this run is in progress"}
    d = _saved_dir(rel)
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


def delete_all() -> dict:
    if batch_running() or _running_rels():
        return {"error": "an audit is in progress; stop it first"}
    n = 0
    if BT_DIR.is_dir():
        for d in list(BT_DIR.iterdir()):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
                n += 1
    return {"ok": True, "deleted": n}


# --------------------------------------------------------------------------- #
# Request handling
# --------------------------------------------------------------------------- #
def handle(h, method: str) -> bool:
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
    except Exception as exc:  # noqa: BLE001
        try:
            h._json({"error": f"{type(exc).__name__}: {exc}"}, code=500)
        except Exception:
            pass
    return True


def _get(h, path: str, query: str) -> None:
    if path in ("/", "/index.html"):
        return h._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
    if path == "/api/list":
        return h._json(list_runs())
    q = parse_qs(query)
    if path == "/api/saved":
        return h._json(saved_full((q.get("run") or [""])[0]))
    if path == "/api/saved_transcript":
        return h._json(saved_transcript((q.get("run") or [""])[0]))
    if path == "/api/transcript":
        return h._json(av.lens_transcript((q.get("job") or [""])[0]))
    h._send(404, b"not found", "text/plain")


def _post(h, path: str) -> None:
    body = h._read_body()
    if path == "/api/start":
        return h._json(start((body.get("run") or "").strip()))
    if path == "/api/start_all":
        return h._json(start_all())
    if path == "/api/stop_all":
        return h._json(stop_all())
    if path == "/api/cancel":
        return h._json(cancel((body.get("job") or "").strip()))
    if path == "/api/delete":
        return h._json(delete((body.get("run") or "").strip()))
    if path == "/api/delete_all":
        return h._json(delete_all())
    h._send(404, b"not found", "text/plain")


# --------------------------------------------------------------------------- #
# Embedded single-page UI
# --------------------------------------------------------------------------- #
INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blue Team</title>
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
/*__CONTROLS_CSS__*/

header{display:flex;align-items:center;gap:12px;padding:12px;background:var(--panel);
  border-bottom:1px solid var(--border);flex:0 0 auto}
header .spacer{flex:1}
.hint{color:var(--faint);font-size:12px}

main{flex:1;display:flex;min-height:0}
.ritem{display:flex;align-items:center;gap:8px;text-align:left;background:transparent;
  border:1px solid transparent;border-radius:7px;padding:7px 9px;cursor:pointer;width:100%;color:var(--fg)}
.ritem:hover{background:var(--panel2);border-color:var(--border)}
.ritem.cur{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent);background:var(--panel3)}
.ritem .rn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px;font-weight:600}
.acount{font-size:10.5px;font-family:var(--mono);color:var(--muted);display:inline-flex;align-items:center;gap:4px}
.livetag{font-size:8.5px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;padding:1px 5px;border-radius:5px;background:rgba(224,175,104,.18);color:#e0af68}
.banner{margin:6px 10px;padding:7px 10px;border-radius:8px;background:rgba(224,175,104,.12);
  border:1px solid rgba(224,175,104,.4);color:#e0af68;font-size:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.banner .bhint{color:var(--faint);font-weight:400}
.muted{color:var(--muted);padding:16px;text-align:center;font-size:12.5px;line-height:1.6}

section.main{flex:1;display:flex;flex-direction:column;min-width:0;min-height:0;background:var(--bg)}
.tbar{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);background:var(--panel)}
.tbar .title{font-weight:700;font-size:13.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tbar .meta{color:var(--faint);font-size:11px;font-family:var(--mono)}
.tbar .spacer{flex:1}
#results{flex:1;overflow-y:auto;padding:14px 16px;max-width:1000px;width:100%;margin:0 auto}

#orient{font-size:13px;color:var(--muted);margin:0 0 12px;line-height:1.6}
.savednote{font-size:11px;color:var(--faint);font-family:var(--mono);margin:0 0 10px}
.summary{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 12px}
.summary .total{font-weight:700;font-size:13px;margin-right:4px}
.chip{cursor:pointer;font-size:11.5px;padding:3px 11px;border-radius:14px;border:1px solid var(--border);
  background:var(--panel2);color:var(--muted);user-select:none;display:inline-flex;gap:6px;align-items:center}
.chip .dot{width:8px;height:8px;border-radius:50%}
.chip.off{opacity:.4;text-decoration:line-through}
.chip .n{font-weight:700;color:var(--fg)}
.dot.critical,.fbadge.critical{--c:#f7768e} .dot.high,.fbadge.high{--c:#ff9e64}
.dot.medium,.fbadge.medium{--c:#e0c14f} .dot.low,.fbadge.low{--c:#7aa2f7}
.dot{background:var(--c,#7aa2f7)}

.fcard{border:1px solid var(--border);border-left:4px solid var(--c,#7aa2f7);border-radius:9px;
  background:var(--panel);padding:10px 13px;margin:9px 0}
.fcard.critical{--c:#f7768e} .fcard.high{--c:#ff9e64} .fcard.medium{--c:#e0c14f} .fcard.low{--c:#7aa2f7}
.fhead{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.fbadge{font-size:9.5px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;padding:2px 8px;
  border-radius:6px;background:color-mix(in srgb,var(--c) 20%,transparent);color:var(--c)}
.ftitle{font-weight:700;font-size:14px;flex:1;min-width:120px}
.fconf{font-size:10.5px;color:var(--faint);font-family:var(--mono);white-space:nowrap}
.floc{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin:6px 0 4px;word-break:break-all}
.fissue{font-size:13px;margin:4px 0}
.fmech{font-size:12.5px;color:var(--muted);margin:4px 0}
.fmech b,.fissue b{color:var(--fg)}

#logBox{margin:10px 0 4px;border:1px solid var(--border);border-radius:9px;background:var(--panel2)}
#logBox>summary{cursor:pointer;padding:8px 12px;font-weight:700;font-size:12.5px;color:var(--muted);
  list-style:none;display:flex;gap:8px;align-items:center}
#logBox>summary::-webkit-details-marker{display:none}
#logBox>summary::before{content:"▸";color:var(--muted)}
#logBox[open]>summary::before{content:"▾"}
#log{padding:4px 12px 12px;max-height:60vh;overflow:auto}
.turn{margin-bottom:10px}
.turn .role{font-size:9px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--faint);margin:2px 0 3px}
.turn .body{font-size:12.5px;overflow-wrap:break-word}
.turn .md p{margin:.35em 0} .turn .md pre{overflow:auto;background:var(--code-bg,#0d1117);padding:8px;border-radius:6px}
.turn .md :first-child{margin-top:0} .turn .md :last-child{margin-bottom:0}
/*__CHAT_CSS__*/
.empty{color:var(--muted);text-align:center;margin-top:12vh;padding:0 24px;line-height:1.7}
.errbox{color:var(--err);background:rgba(247,118,142,.08);border:1px solid rgba(247,118,142,.35);
  border-radius:8px;padding:10px 12px;margin:8px 0;font-size:12.5px;white-space:pre-wrap}
/*__PROGRESS_CSS__*/
</style>
</head>
<body>
<div id="topbar-progress"></div>
<header>
  <nav class="appnav"><a href="/">🔎 Runs</a><a href="/proposals">🗒 Proposals</a><a href="/studio">📝 Studio</a><a class="on" href="/blueteam">🛡 Blue Team</a></nav>
  <span class="spacer"></span>
  <span class="hint">Read-only audits — surfaces concerning, result-affecting problems for you to judge (no verdict).</span>
</header>
<main>
  <aside class="side">
    <div class="sidehead">🛡 Runs <span class="spacer"></span></div>
    <div class="sideacts">
      <button class="primary mini" id="runAllBtn">▶ Run all</button>
      <button class="danger mini" id="stopAllBtn" hidden>■ Stop all</button>
      <button class="danger mini" id="delAllBtn">🗑 Delete all</button>
    </div>
    <div id="batchBanner"></div>
    <input id="search" class="sidesearch" placeholder="filter runs…" autocomplete="off">
    <div id="rlist" class="sidelist"><div class="muted">loading…</div></div>
  </aside>
  <section class="main">
    <div class="tbar">
      <span class="title" id="curTitle">No run selected</span>
      <span class="meta" id="curMeta"></span>
      <span class="spacer"></span>
      <button class="danger" id="delBtn" hidden>🗑 Delete</button>
      <button class="danger" id="cancelBtn" hidden>■ Stop</button>
      <button class="primary" id="auditBtn" disabled>🛡 Run audit</button>
    </div>
    <div id="results"><div class="empty">Pick a run on the left, then <b>Run audit</b> — or <b>▶ Run all</b>.<br>
      A read-only agent explores each run and surfaces every concerning, result-affecting
      problem it can substantiate — colour-coded by concern, sorted worst-first. Audits are saved.</div></div>
  </section>
</main>
<div class="toast" id="toast"></div>
<script>
const $ = s => document.querySelector(s);
const API = "/blueteam/api";
const LEVELS=["critical","high","medium","low"];
const ORDER={critical:0,high:1,medium:2,low:3};
let runs=[], batch=false, batchActive=0, batchQueued=0, cur=null, job=null, poll=null, refresh=null, hidden=new Set(), viewKey="", logOpen=true;

//__APP_JS__
//__PROGRESS_JS__

async function api(url,body,quiet){
  let r;
  if(!quiet)Progress.start();
  try{ r=await fetch(url, body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})}); }
  catch(e){ toast("network error: "+e.message); return null; }
  finally{ if(!quiet)Progress.done(); }
  const d=await r.json().catch(()=>({}));
  if(!r.ok){toast(d.error||"failed");return null;}
  return d;
}

// ---- run list ----
// Audits run server-side and persist on their own; the page only *attaches* to a
// run's live stream when you view it. So you can switch runs freely, audit many at
// once, and re-attach to any running audit by clicking its run (studio-style).
function ensureRefresh(){
  const need = batch || runs.some(r=>r.job||r.queued);
  if(need && !refresh) refresh=setInterval(loadRuns, 3000);
  if(!need && refresh){ clearInterval(refresh); refresh=null; }
}
async function loadRuns(){
  const d=await api(API+"/list", undefined, true);
  if(!d) return;
  runs=d.items||[]; batch=!!d.batch; batchActive=d.active||0; batchQueued=d.queued||0;
  renderRuns(); renderBatchBar(); setButtons(); ensureRefresh();
  syncView();
}
// Keep the viewed run's panel in sync with server state: attach to an audit that
// (re)appeared (even one started elsewhere), or fall back to its saved result.
function syncView(){
  if(!cur) return;
  const r=runs.find(x=>x.path===cur); if(!r) return;
  if(r.job && job!==r.job){ job=r.job; viewKey=""; startPoll(); }
  else if(!r.job && job){ finishView(); }
  else if(!r.job && !job && r.audit){ maybeRefreshSaved(r); }
}
function renderBatchBar(){
  $("#stopAllBtn").hidden=!batch;
  $("#runAllBtn").disabled=batch;
  $("#batchBanner").innerHTML = batch
    ? `<div class="banner"><span class="tdot"></span><span class="tdot"></span><span class="tdot"></span> Auditing all — ${batchActive} running · ${batchQueued} queued <span class="bhint">(click any run to watch)</span></div>` : "";
}
function badge(r){
  let b = r.live ? '<span class="livetag">live</span>' : "";
  if(r.job) b += '<span class="acount"><span class="tdot"></span>auditing</span>';
  else if(r.queued) b += '<span class="acount">queued</span>';
  else if(r.audit) b += `<span class="acount"><span class="dot ${r.audit.worst||'low'}"></span>${r.audit.count}</span>`;
  return b;
}
function renderRuns(){
  const q=$("#search").value.toLowerCase();
  const list=$("#rlist");
  const items=runs.filter(r=>!q || (r.name||"").toLowerCase().includes(q));
  if(!items.length){ list.innerHTML='<div class="muted">no runs</div>'; return; }
  list.innerHTML=items.map(r=>
    `<button class="ritem${r.path===cur?' cur':''}" data-p="${esc(r.path)}">`
    +`<span class="rn">${esc(r.name)}</span>${badge(r)}</button>`).join("");
  list.querySelectorAll(".ritem").forEach(b=>b.onclick=()=>select(b.dataset.p));
}

function setButtons(){
  const r=runs.find(x=>x.path===cur);
  const auditing=!!(r&&r.job);            // this run currently has a live audit
  $("#auditBtn").hidden=auditing;
  $("#cancelBtn").hidden=!auditing;
  // concurrent audits are fine; only block when a batch would race THIS completed run
  $("#auditBtn").disabled=!cur||(batch && r && !r.live);
  $("#auditBtn").textContent=(r&&r.audit)?"↻ Re-run audit":"🛡 Run audit";
  $("#delBtn").hidden=!(r&&r.audit)||auditing;
}

// ---- selection (never blocks; audits keep running server-side) ----
async function select(p){
  if(poll){ clearInterval(poll); poll=null; }   // stop streaming the previous run (its audit keeps going)
  job=null; cur=p; viewKey=""; hidden.clear(); logOpen=true;
  const r=runs.find(x=>x.path===p);
  $("#curTitle").textContent=r?r.name:p;
  $("#curMeta").textContent="";
  renderRuns(); setButtons();
  if(r&&r.job){ job=r.job; $("#results").innerHTML='<div class="empty">attaching to the live audit…</div>'; startPoll(); }
  else if(r&&r.queued){ $("#results").innerHTML='<div class="empty">⏳ queued for audit — it will start when a slot frees, then stream here.</div>'; }
  else if(r&&r.audit){ showSaved(p); }
  else $("#results").innerHTML='<div class="empty">Ready to audit <b>'+esc(r?r.name:p)+'</b>'
    +((r&&r.live)?' <span class="acount">— live run; the audit covers progress so far</span>':'')
    +'.<br>Click <b>🛡 Run audit</b>.</div>';
}
let savedMtime=0;
async function showSaved(rel){
  const d=await api(API+"/saved?run="+encodeURIComponent(rel), undefined, true);
  if(!d||!d.exists){ $("#results").innerHTML='<div class="empty">No saved audit.</div>'; return; }
  savedMtime=d.mtime;
  let html="";
  html+=`<div class="savednote">saved audit · ${new Date(d.mtime*1000).toLocaleString()}</div>`;
  if(d.orient) html+=`<div id="orient">${md(d.orient)}</div>`;
  html+=d.findings.length?renderFindings(d.findings,false)
    :'<div class="muted">No result-affecting problems were found in this run.</div>';
  html+=`<div id="savedLog"></div>`;
  $("#results").innerHTML=html;
  bindChips(d.findings);
  // load the saved agent exploration transcript into a collapsible log
  const t=await api(API+"/saved_transcript?run="+encodeURIComponent(rel), undefined, true);
  const turns=(t&&t.turns)||[];
  if(turns.length){
    const logTurns=turns.map(tn=>`<div class="turn"><div class="role">Blue Team agent</div><div class="body">${(tn.blocks||[]).map(blockHtml).join("")}</div></div>`).join("");
    const box=$("#savedLog");
    if(box) box.innerHTML=`<details id="logBox"><summary>Exploration log · ${steps(turns)} steps</summary><div id="log">${logTurns}</div></details>`;
  }
}
function maybeRefreshSaved(r){ if(r.audit && r.audit.mtime>savedMtime+0.5 && cur===r.path) showSaved(r.path); }

// ---- findings cards ----
function findCard(f){
  const lvl=LEVELS.includes((f.concern||"").toLowerCase())?f.concern.toLowerCase():"low";
  const conf=(f.confidence!=null&&f.confidence!=="")?` · confidence ${esc(String(f.confidence))}`:"";
  return `<div class="fcard ${lvl}"${hidden.has(lvl)?' style="display:none"':''}>`
    +`<div class="fhead"><span class="fbadge ${lvl}">${lvl}</span>`
    +`<span class="ftitle">${esc(f.title||"(untitled)")}</span><span class="fconf">${conf}</span></div>`
    +(f.location?`<div class="floc">${esc(f.location)}</div>`:"")
    +(f.issue?`<div class="fissue">${md(f.issue)}</div>`:"")
    +(f.mechanism?`<div class="fmech"><b>Why it matters:</b> ${md(f.mechanism)}</div>`:"")
    +`</div>`;
}
function renderFindings(findings, running){
  const sorted=[...findings].sort((a,b)=>
    (ORDER[(a.concern||"low").toLowerCase()]??9)-(ORDER[(b.concern||"low").toLowerCase()]??9)
    || (b.confidence||0)-(a.confidence||0));
  const counts={critical:0,high:0,medium:0,low:0};
  sorted.forEach(f=>{const l=(f.concern||"low").toLowerCase(); if(counts[l]!=null)counts[l]++;});
  const chips=LEVELS.map(l=>`<span class="chip${hidden.has(l)?' off':''}" data-lvl="${l}"><span class="dot ${l}"></span>${l} <span class="n">${counts[l]}</span></span>`).join("");
  return `<div class="summary"><span class="total">${sorted.length} finding${sorted.length===1?'':'s'}</span>`
    +chips+(running?' <span class="fconf">· still auditing…</span>':'')+`</div>`
    +`<div id="cards">`+sorted.map(findCard).join("")+`</div>`;
}
function bindChips(findings){
  $("#results").querySelectorAll(".chip").forEach(c=>c.onclick=()=>{
    const l=c.dataset.lvl; hidden.has(l)?hidden.delete(l):hidden.add(l);
    const cards=$("#cards");
    if(cards){ // re-render just the cards + chip states
      c.classList.toggle("off", hidden.has(l));
      cards.querySelectorAll(".fcard").forEach(card=>{
        const lv=LEVELS.find(x=>card.classList.contains(x))||"low";
        card.style.display=hidden.has(lv)?"none":"";
      });
    }
  });
}

// ---- live exploration rendering (block renderer shared via theme.TRANSCRIPT_JS) ----
function parseFindings(turns){
  const text=turns.flatMap(t=>t.blocks||[]).filter(b=>b.kind==="text").map(b=>b.text||"").join("\n");
  for(const b of [...text.matchAll(/```json\s*([\s\S]*?)```/g)].reverse()){
    try{ const o=JSON.parse(b[1]); if(o&&Array.isArray(o.findings)) return o.findings; }catch(e){}
  }
  return null;
}
function steps(turns){ return turns.reduce((n,t)=>n+(t.blocks||[]).length,0); }
function renderLive(d){
  const turns=d.turns||[], running=!!d.running;
  const findings=parseFindings(turns);
  const key=JSON.stringify([findings,running,steps(turns),
    turns.reduce((n,t)=>n+(t.blocks||[]).reduce((m,b)=>m+(b.text||"").length+((b.result&&b.result.text)||"").length,0),0)]);
  if(key===viewKey) return; viewKey=key;
  const res=$("#results"); const atBottom=res.scrollHeight-res.scrollTop-res.clientHeight<140;
  let html="";
  if(findings){ html+=findings.length?renderFindings(findings,running):'<div class="muted">No result-affecting problems found.</div>'; logOpen=false; }
  else if(running) html+=`<div class="summary"><span class="total"><span class="tdot"></span><span class="tdot"></span><span class="tdot"></span> exploring the run…</span></div>`;
  const logTurns=turns.map(t=>`<div class="turn"><div class="role">Blue Team agent</div><div class="body">${(t.blocks||[]).map(blockHtml).join("")}</div></div>`).join("");
  if(logTurns) html+=`<details id="logBox"${logOpen?' open':''}><summary>Exploration log · ${steps(turns)} steps</summary><div id="log">${logTurns}</div></details>`;
  res.innerHTML=html||'<div class="empty">No output yet.</div>';
  if(findings) bindChips(findings);
  const lb=$("#logBox"),lg=$("#log"); if(lb){lb.addEventListener("toggle",()=>logOpen=lb.open); if(lb.open&&lg)lg.scrollTop=lg.scrollHeight;}
  if(atBottom && !findings) res.scrollTop=res.scrollHeight;
}

// ---- audit lifecycle (per-run, concurrent, re-attachable) ----
function startPoll(){ if(poll)clearInterval(poll); pollOnce(); poll=setInterval(pollOnce,2000); }
async function runAudit(){
  if(!cur) return;
  const r=runs.find(x=>x.path===cur);
  if(r&&r.job){ toast("already auditing this run"); return; }
  viewKey=""; hidden.clear(); logOpen=true;
  $("#results").innerHTML='<div class="empty"><span class="tdot"></span><span class="tdot"></span><span class="tdot"></span> launching read-only auditor…</div>';
  const d=await api(API+"/start",{run:cur});
  if(!d||d.error){ $("#results").innerHTML='<div class="errbox">'+esc((d&&d.error)||"failed to start")+'</div>'; return; }
  job=d.job; if(r){ r.running=true; r.job=d.job; }   // local, so switch-away/back re-attaches immediately
  renderRuns(); setButtons(); ensureRefresh(); startPoll();
}
async function pollOnce(){
  if(!job) return;
  const myjob=job;
  const d=await api(API+"/transcript?job="+encodeURIComponent(myjob), undefined, true);
  if(myjob!==job) return;        // user switched runs mid-fetch
  if(!d) return;
  if(d.error && !(d.turns&&d.turns.length)){ $("#results").innerHTML='<div class="errbox">'+esc(d.error)+'</div>'; finishView(); return; }
  renderLive(d);
  $("#curMeta").textContent=d.running?"auditing…":"done";
  if(!d.running) finishView();
}
function finishView(){
  if(poll){ clearInterval(poll); poll=null; }
  job=null; viewKey=""; savedMtime=0;
  const r=runs.find(x=>x.path===cur); if(r){ r.running=false; r.job=null; }
  setButtons();
  setTimeout(()=>{ loadRuns(); if(cur) showSaved(cur); }, 1200);  // let the daemon persist
}
async function cancelAudit(){ if(!job) return; await api(API+"/cancel",{job}); toast("audit stopped"); finishView(); }

// ---- batch + delete ----
async function runAll(){
  const n=runs.filter(r=>r.status==="completed" && !r.live).length;
  if(!confirm(`Run a fresh audit on all ${n} completed runs? This overwrites existing saved audits and uses real model calls.`)) return;
  const d=await api(API+"/start_all",{}); if(!d||d.error) return;
  toast("running all audits…"); loadRuns();
}
async function stopAll(){ if(!confirm("Stop the running batch?")) return; await api(API+"/stop_all",{}); toast("stopping batch…"); setTimeout(loadRuns,800); }
async function deleteAudit(){
  if(!cur) return;
  if(!confirm("Delete the saved audit for this run?")) return;
  const d=await api(API+"/delete",{run:cur}); if(!d||d.error) return;
  await loadRuns(); select(cur);
}
async function deleteAll(){
  if(!confirm("Delete ALL saved audits?")) return;
  const d=await api(API+"/delete_all",{}); if(!d) return;
  toast(`deleted ${d.deleted||0} audits`); await loadRuns();
  if(cur) select(cur);
}

// ---- wiring ----
$("#auditBtn").onclick=runAudit;
$("#cancelBtn").onclick=cancelAudit;
$("#runAllBtn").onclick=runAll;
$("#stopAllBtn").onclick=stopAll;
$("#delBtn").onclick=deleteAudit;
$("#delAllBtn").onclick=deleteAll;
$("#search").addEventListener("input",renderRuns);
loadRuns();
</script>
</body>
</html>
"""

INDEX_HTML = (
    INDEX_HTML.replace("/*__PALETTE__*/", PALETTE_CSS)
    .replace("/*__CONTROLS_CSS__*/", CONTROLS_CSS)
    .replace("/*__CHAT_CSS__*/", CHAT_CSS)
    .replace("/*__PROGRESS_CSS__*/", PROGRESS_CSS)
    .replace("//__APP_JS__", APP_JS + "\n" + TRANSCRIPT_JS)
    .replace("//__PROGRESS_JS__", PROGRESS_JS)
)
