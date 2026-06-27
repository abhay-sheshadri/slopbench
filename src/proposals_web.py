"""Proposals manager — mounted under ``/proposals`` by the agent viewer.

Browse, read, edit, and create the research proposals in ``proposals/`` with
the same markdown editor/preview as the blogpost studio (shared via
:mod:`src.theme`), plus a per-proposal editing agent (:mod:`src.proposal_studio`)
that edits the proposal file directly — the proposals counterpart of the
writeup agent. Sessions are per-proposal and named on every request, so any
number of windows can each drive a different proposal at the same time.

Like the studio, this has no server of its own: :func:`handle` is called by the
viewer's request handler and claims paths under ``/proposals``.
"""

from __future__ import annotations

import re
import shutil
import threading
from urllib.parse import parse_qs

from src import web_common
from src.agent_viewer import ROOT
from src.blogpost_studio_web import _sse  # generic over DocAgentSession
from src.proposal_studio import ProposalSession
from src.theme import (
    API_JS,
    APP_JS,
    CHAT_CSS,
    CONTROLS_CSS,
    EDITOR_CSS,
    FAVICON_LINK,
    HIGHLIGHT_JS,
    PALETTE_CSS,
    PREVIEW_CSS,
    PROGRESS_CSS,
    PROGRESS_JS,
    RESIZER_CSS,
    RESIZER_JS,
)

PREFIX = "/proposals"
PROPOSALS_DIR = ROOT / "proposals"

# Plain flat filenames only — no separators, nothing hidden.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# One agent session per proposal, created lazily; per-window by construction
# (every request names its proposal).
SESSIONS: dict[str, ProposalSession] = {}
_LOCK = threading.Lock()


def _path_for(name: str):
    """proposals/<name>.md for a validated bare name (``.md`` optional)."""
    name = (name or "").strip()
    if name.endswith(".md"):
        name = name[:-3]
    if not _NAME_RE.match(name):
        raise ValueError("proposal names use letters, digits, '.', '-', '_'")
    return PROPOSALS_DIR / f"{name}.md"


def _stem_for(name: str) -> str:
    """Validated proposal stem for API responses / session keys."""
    return _path_for(name).stem


def _session(name: str, *, create: bool) -> ProposalSession | None:
    """The agent session for a proposal (validated), created on demand."""
    p = _path_for(name)
    with _LOCK:
        s = SESSIONS.get(p.stem)
        if s is None and create:
            s = SESSIONS[p.stem] = ProposalSession(p.stem)
        return s


def list_proposals() -> list[dict]:
    from src.blogpost_studio import live_sandbox_workspaces
    from src.proposal_studio import WORK_ROOT

    live_ws = live_sandbox_workspaces()  # catches turns we hold no session for
    items = []
    for p in sorted(PROPOSALS_DIR.glob("*.md")):
        st = p.stat()
        s = SESSIONS.get(p.stem)
        items.append(
            {
                "name": p.stem,
                "mtime": st.st_mtime,
                "size": st.st_size,
                "busy": bool(s and s.is_running())
                or str(WORK_ROOT / p.stem) in live_ws,
            }
        )
    return items


def _is_busy(name: str) -> bool:
    """Whether a proposal has a live editing agent, including orphaned sandboxes."""
    from src.blogpost_studio import live_sandbox_workspaces
    from src.proposal_studio import WORK_ROOT

    stem = _stem_for(name)
    s = SESSIONS.get(stem)
    return (
        bool(s and s.is_running()) or str(WORK_ROOT / stem) in live_sandbox_workspaces()
    )


def create_doc(name: str, content: str) -> dict:
    """Create a new proposal. Refuses to replace an existing file."""
    p = _path_for(name)
    if p.exists():
        raise FileExistsError(f"{p.stem}.md already exists")
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"name": p.stem, "mtime": p.stat().st_mtime}


def read_doc(name: str) -> dict:
    p = _path_for(name)
    if not p.exists():
        raise ValueError(f"no proposal named {p.stem}")
    return {
        "name": p.stem,
        "content": p.read_text(encoding="utf-8", errors="replace"),
        "mtime": p.stat().st_mtime,
    }


def save_doc(name: str, content: str) -> dict:
    """Write (or create) a proposal. Refuses while its agent is editing it."""
    p = _path_for(name)
    s = SESSIONS.get(p.stem)
    if s is not None and s.is_running():
        raise RuntimeError("the agent is editing this proposal; wait for it to finish")
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"name": p.stem, "mtime": p.stat().st_mtime}


def rename_doc(name: str, new_name: str) -> dict:
    """Rename a proposal and its idle agent workspace, if present."""
    from src.proposal_studio import WORK_ROOT

    old = _path_for(name)
    new = _path_for(new_name)
    if not old.exists():
        raise ValueError(f"no proposal named {old.stem}")
    if old == new:
        return {"name": old.stem, "mtime": old.stat().st_mtime}
    if new.exists():
        raise FileExistsError(f"{new.stem}.md already exists")
    if _is_busy(old.stem):
        raise RuntimeError("the agent is editing this proposal; wait for it to finish")

    with _LOCK:
        SESSIONS.pop(old.stem, None)
    old.rename(new)

    old_work = WORK_ROOT / old.stem
    new_work = WORK_ROOT / new.stem
    if old_work.exists() and not new_work.exists():
        try:
            shutil.move(str(old_work), str(new_work))
        except OSError:
            pass
    return {"name": new.stem, "oldName": old.stem, "mtime": new.stat().st_mtime}


def duplicate_doc(name: str, new_name: str) -> dict:
    src = _path_for(name)
    dst = _path_for(new_name)
    if not src.exists():
        raise ValueError(f"no proposal named {src.stem}")
    if dst.exists():
        raise FileExistsError(f"{dst.stem}.md already exists")
    if _is_busy(src.stem):
        raise RuntimeError("the agent is editing this proposal; wait for it to finish")
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return {"name": dst.stem, "mtime": dst.stat().st_mtime}


def delete_doc(name: str) -> dict:
    p = _path_for(name)
    if not p.exists():
        raise ValueError(f"no proposal named {p.stem}")
    if _is_busy(p.stem):
        raise RuntimeError("the agent is editing this proposal; wait for it to finish")
    with _LOCK:
        SESSIONS.pop(p.stem, None)
    p.unlink()
    return {"name": p.stem}


# --------------------------------------------------------------------------- #
# Request handling (called from the agent viewer's Handler)
# --------------------------------------------------------------------------- #
def handle(h, method: str) -> bool:
    """Serve one request if its path is under /proposals (shared dispatch)."""
    return web_common.serve(h, method, PREFIX, _get, _post)


def _get(h, path: str, query: str) -> None:
    if path in ("/", "/index.html"):
        return h._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
    if path == "/api/list":
        return h._json({"items": list_proposals()})
    q = parse_qs(query)
    name = (q.get("name") or [""])[0]
    if path == "/api/doc":
        try:
            h._json(read_doc(name))
        except ValueError as exc:
            h._json({"error": str(exc)}, code=404)
    elif path == "/api/agent/stream":
        # The SSE machinery is the studio's, generic over DocAgentSession.
        try:
            s = _session(name, create=True) if name else None
        except ValueError:
            s = None
        _sse(h, s)
    else:
        h._send(404, b"not found", "text/plain")


def _post(h, path: str) -> None:
    body = h._read_body()
    name = body.get("name") or ""
    if path == "/api/create":
        content = body.get("content")
        if not isinstance(content, str):
            return h._json({"error": "missing content"}, code=400)
        try:
            return h._json({"ok": True, **create_doc(name, content)})
        except ValueError as exc:
            return h._json({"error": str(exc)}, code=400)
        except FileExistsError as exc:
            return h._json({"error": str(exc)}, code=409)
    if path == "/api/doc":
        content = body.get("content")
        if not isinstance(content, str):
            return h._json({"error": "missing content"}, code=400)
        try:
            return h._json({"ok": True, **save_doc(name, content)})
        except ValueError as exc:
            return h._json({"error": str(exc)}, code=400)
        except RuntimeError as exc:
            return h._json({"error": str(exc)}, code=409)
    if path == "/api/rename":
        try:
            return h._json({"ok": True, **rename_doc(name, body.get("newName") or "")})
        except ValueError as exc:
            return h._json({"error": str(exc)}, code=400)
        except FileExistsError as exc:
            return h._json({"error": str(exc)}, code=409)
        except RuntimeError as exc:
            return h._json({"error": str(exc)}, code=409)
    if path == "/api/duplicate":
        try:
            return h._json(
                {"ok": True, **duplicate_doc(name, body.get("newName") or "")}
            )
        except ValueError as exc:
            return h._json({"error": str(exc)}, code=400)
        except FileExistsError as exc:
            return h._json({"error": str(exc)}, code=409)
        except RuntimeError as exc:
            return h._json({"error": str(exc)}, code=409)
    if path == "/api/delete":
        try:
            return h._json({"ok": True, **delete_doc(name)})
        except ValueError as exc:
            return h._json({"error": str(exc)}, code=404)
        except RuntimeError as exc:
            return h._json({"error": str(exc)}, code=409)
    try:
        s = _session(name, create=path == "/api/agent/chat")
    except ValueError as exc:
        return h._json({"error": str(exc)}, code=400)
    if path == "/api/agent/chat":
        try:
            s.start_turn((body.get("message") or "").strip())
        except (ValueError, RuntimeError) as exc:
            return h._json({"error": str(exc)}, code=409)
        h._json({"ok": True})
    elif path == "/api/agent/stop":
        h._json({"ok": True, "killed": bool(s and s.stop())})
    elif path == "/api/agent/reset":
        try:
            if s:
                s.reset()
        except RuntimeError as exc:
            return h._json({"error": str(exc)}, code=409)
        h._json({"ok": True})
    else:
        h._send(404, b"not found", "text/plain")


# --------------------------------------------------------------------------- #
# Embedded single-page UI
# --------------------------------------------------------------------------- #
INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Proposals</title>
<!--__FAVICON__-->
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

main{flex:1;display:flex;min-height:0}
.pitem{display:flex;align-items:baseline;gap:8px;text-align:left;background:transparent;
  border:1px solid transparent;border-radius:6px;padding:7px 9px;cursor:pointer;width:100%;color:var(--fg)}
.pitem:hover{background:var(--panel2);border-color:var(--border)}
.pitem.cur{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.pitem .pn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:600}
.pitem .pt{color:var(--faint);font-size:10px;white-space:nowrap;font-family:var(--mono)}
.pitem .busy{color:var(--warn);font-size:10px}
.sidecount{color:var(--faint);font:11px var(--mono)}
.muted{color:var(--muted);padding:14px;text-align:center;font-size:12.5px}

/* chat with the proposal-editing agent (same workflow as the writeup studio);
   docked on the right, doc in the middle */
#chatcol{width:420px;flex:0 0 auto;min-width:0;display:flex;flex-direction:column;min-height:0;
  background:var(--panel);border-left:1px solid var(--border)}
.chathead{display:flex;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid var(--border);
  font-weight:700;font-size:13px}
.chathead .meta{font-weight:400}
.chathead .spacer{flex:1}
#plog{flex:1;overflow-y:auto;padding:10px;display:flex;flex-direction:column;gap:8px}
.turn{max-width:100%}
.turn .role{font-size:9.5px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;
  color:var(--faint);margin:2px 2px 3px}
.turn .body{background:var(--panel2);border:1px solid var(--border);border-radius:10px;
  padding:7px 10px;font-size:13px;overflow-wrap:break-word}
.turn.user .body{background:rgba(122,162,247,.10);border-color:rgba(122,162,247,.35)}
.turn.cont{margin-top:-7px}            /* same speaker: bubbles join into one group */
.turn.cont .body{padding-top:10px}
.turn .md p{margin:.3em 0} .turn .md pre{overflow:auto;background:var(--code-bg);padding:8px;border-radius:6px}
.turn .md :first-child{margin-top:0} .turn .md :last-child{margin-bottom:0}
.turn .md img{max-width:100%;cursor:zoom-in}
/*__CHAT_CSS__*/
/* image lightbox (as in the studio / agent viewer) */
.lightbox{position:fixed;inset:0;z-index:9999;background:rgba(3,5,10,.88);display:flex;
  align-items:center;justify-content:center;padding:40px}
.lightbox[hidden]{display:none}
.lightbox img{max-width:95vw;max-height:90vh;object-fit:contain;background:#fff;border-radius:6px;
  box-shadow:0 14px 45px rgba(0,0,0,.55)}
.modal{position:fixed;inset:0;z-index:9000;background:rgba(3,5,10,.72);display:flex;
  align-items:center;justify-content:center;padding:24px}
.modal[hidden]{display:none}
.dialog{width:min(440px,calc(100vw - 32px));background:var(--panel);border:1px solid var(--border);
  border-radius:10px;box-shadow:0 18px 55px rgba(0,0,0,.45);padding:16px}
.dialog h2{font-size:15px;line-height:1.3;margin:0 0 10px}
.dialog p{color:var(--muted);font-size:13px;line-height:1.55;margin:0 0 12px}
.dialog input{width:100%;background:var(--panel2);color:var(--fg);border:1px solid var(--border);
  border-radius:7px;padding:8px 10px;font:13px var(--mono);outline:none}
.dialog input:focus{border-color:var(--accent)}
.dialog .actions{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}
.composer{display:flex;gap:8px;padding:10px;border-top:1px solid var(--border);align-items:flex-end}
.composer .btncol{display:flex;flex-direction:column;gap:6px;justify-content:flex-end}
.composer .btncol button{width:100%;white-space:nowrap}
.composer textarea{flex:1;resize:none;background:var(--panel2);color:var(--fg);
  border:1px solid var(--border);border-radius:8px;padding:8px 10px;font:13px/1.45 var(--sans);outline:none}
.composer textarea:focus{border-color:var(--accent)}

#doc{flex:1;display:flex;flex-direction:column;min-width:0;background:var(--bg)}
.docbar{display:flex;align-items:center;gap:10px;padding:7px 14px;border-bottom:1px solid var(--border);background:var(--panel)}
#viewtoggle{font-size:12px;padding:4px 13px;color:var(--muted)}
#viewtoggle:hover:not(:disabled){color:var(--fg)}
#docname{color:var(--muted);font-family:var(--mono);font-size:12px}
.docbar .spacer{flex:1}
.docactions{display:flex;gap:6px;align-items:center}
.docactions button{font-size:12px;padding:4px 10px}
.docactions .danger{padding-left:9px;padding-right:9px}
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
.empty{color:var(--muted);text-align:center;margin-top:14vh;padding:0 24px;line-height:1.6}
.empty button{margin-top:14px}

@media (max-width: 1000px){
  main{display:grid;grid-template-columns:minmax(220px,280px) minmax(0,1fr);
    grid-template-rows:minmax(0,1fr) minmax(250px,36vh)}
  aside.side{grid-column:1;grid-row:1 / 3;width:auto}
  #rsSide,#rsChat{display:none}
  #doc{grid-column:2;grid-row:1;min-height:0}
  #chatcol{grid-column:2;grid-row:2;width:auto;border-left:0;border-top:1px solid var(--border)}
  .docbar{flex-wrap:wrap;gap:7px}
  #docname{flex:1 1 260px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .docactions{order:3}
  #meta{margin-left:auto}
  #plog{padding:8px 10px}
  .composer{padding:8px 10px}
}
@media (max-width: 680px){
  main{display:flex;flex-direction:column}
  aside.side{width:auto;max-height:34vh;border-right:0;border-bottom:1px solid var(--border)}
  #doc{min-height:44vh}
  #chatcol{width:auto;min-height:260px}
  .docactions{order:3;width:100%;justify-content:flex-end}
}

/*__RESIZER_CSS__*/
/*__PROGRESS_CSS__*/
</style>
</head>
<body>
<div id="topbar-progress"></div>
<header>
  <nav class="appnav"><a href="/">🔎 Runs</a><a class="on" href="/proposals">🗒 Proposals</a><a href="/studio">📝 Studio</a><a href="/blueteam">🛡 Blue Team</a></nav>
  <span class="spacer"></span>
</header>
<main>
  <aside class="side">
    <div class="sidehead">🗒 Proposals <span class="spacer"></span><span class="sidecount" id="pcount"></span></div>
    <div class="sideacts"><button class="primary mini" id="newbtn">＋ New proposal</button></div>
    <input id="psearch" class="sidesearch" placeholder="filter proposals…" autocomplete="off">
    <div id="plist" class="sidelist"><div class="muted">loading…</div></div>
  </aside>
  <div class="vresizer" id="rsSide" title="Drag to resize"></div>
  <section id="doc">
    <div class="docbar">
      <button id="viewtoggle">✎ Edit</button>
      <span id="docname"></span>
      <span class="spacer"></span>
      <span class="docactions">
        <button class="mini" id="renamebtn" title="Rename this proposal">Rename</button>
        <button class="mini" id="dupbtn" title="Duplicate this proposal">Duplicate</button>
        <button class="danger mini" id="deletebtn" title="Delete this proposal">Delete</button>
      </span>
      <span class="meta" id="meta"></span>
    </div>
    <div id="docview" class="view">
      <div class="pane editpane"><div class="editwrap"><pre id="editorHL" aria-hidden="true"></pre><textarea id="editor" spellcheck="false"
        placeholder="Write the proposal in markdown. Changes autosave."></textarea></div></div>
      <div class="pane previewpane"><div id="preview"><div class="empty">Pick a proposal on the left, or create a new one.</div></div></div>
    </div>
  </section>
  <div class="vresizer" id="rsChat" title="Drag to resize"></div>
  <section id="chatcol">
    <div class="chathead">Agent <span class="meta" id="cost"></span><span class="spacer"></span>
      <button class="mini" id="resetchatbtn" title="Clear this proposal's agent conversation">New chat</button>
      <button class="mini" id="polishbtn" title="Ask the agent to clean up this proposal">✨ Clean up</button>
    </div>
    <div id="plog"><div class="muted">Chat with an agent that edits this proposal directly — same workflow as the writeup studio.</div></div>
    <div class="composer">
      <textarea id="pmsg" rows="2" placeholder="Ask for edits… (Enter to send)"></textarea>
      <div class="btncol">
        <button class="danger" id="stopbtn" hidden title="Stop the agent's current turn">■ Stop</button>
        <button class="primary" id="psend">Send</button>
      </div>
    </div>
  </section>
</main>
<div class="toast" id="toast"></div>
<div class="lightbox" id="lightbox" hidden><img alt=""></div>
<div class="modal" id="modal" hidden>
  <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
    <h2 id="modalTitle"></h2>
    <p id="modalText"></p>
    <input id="modalInput" autocomplete="off" spellcheck="false">
    <div class="actions">
      <button id="modalCancel">Cancel</button>
      <button class="primary" id="modalOk">OK</button>
    </div>
  </div>
</div>
<script>
const $ = s => document.querySelector(s);
const API = "/proposals/api";
const editor=$("#editor"), preview=$("#preview"), hl=$("#editorHL");
let cur=null, dirty=false, mode="view", saveTimer, docMtime=0, running=false, es=null, turnsKey="";
let lastTurns=[], queue=[], sending=false, sentBase=0;
let proposals=[];

//__APP_JS__

//__HIGHLIGHT_JS__
//__RESIZER_JS__
//__PROGRESS_JS__
function syncHL(){
  hl.innerHTML=highlightMarkdown(editor.value)+"\n";   // trailing \n keeps last line height in sync
  hl.scrollTop=editor.scrollTop; hl.scrollLeft=editor.scrollLeft;
}
function renderPreview(){ preview.innerHTML=md(editor.value); }
function updateMeta(status){
  const n=(editor.value.match(/\S+/g)||[]).length;
  status = status || (dirty && running ? "unsaved · agent editing…" : (dirty ? "unsaved" : (running ? "agent editing…" : (cur ? "saved" : ""))));
  $("#meta").innerHTML=(n?n.toLocaleString()+" words":"")+(status?` <span class="dot">·</span> ${esc(status)}`:"");
}
function setMode(m){
  mode=m;
  $("#docview").className=m;
  $("#viewtoggle").textContent = m==="view" ? "✎ Edit" : "👁 Preview";
  if(m==="view") renderPreview(); else syncHL();
}

// every POST names the current proposal (shared api() injects it via apiBody)
window.apiBody=(b)=>({name:cur||undefined,...(b||{})});
//__API_JS__

let modalResolve=null;
function closeModal(value){
  const done=modalResolve; modalResolve=null;
  $("#modal").hidden=true;
  if(done) done(value);
}
function modalBase({title,text="",value="",input=true,danger=false,ok="OK"}){
  $("#modalTitle").textContent=title;
  $("#modalText").textContent=text;
  $("#modalText").hidden=!text;
  $("#modalInput").hidden=!input;
  $("#modalInput").value=value;
  $("#modalOk").textContent=ok;
  $("#modalOk").className=danger?"danger":"primary";
  $("#modal").hidden=false;
  if(input){ setTimeout(()=>{ $("#modalInput").focus(); $("#modalInput").select(); },0); }
  else setTimeout(()=>$("#modalOk").focus(),0);
  return new Promise(resolve=>{ modalResolve=resolve; });
}
async function askName(opts){
  const v=await modalBase({...opts,input:true});
  return v==null?null:cleanName(v);
}
function askConfirm(opts){ return modalBase({...opts,input:false}); }

// ---- document ----
async function save(){
  clearTimeout(saveTimer);
  if(!cur || !dirty) return true;
  if(running) return true;       // keep edits local; save when the turn ends
  updateMeta("saving…");
  const d=await api(API+"/doc",{content:editor.value},true);
  if(!d){updateMeta();return false;}
  dirty=false; docMtime=d.mtime; updateMeta();
  return true;
}
function onEdit(){
  if(!cur) return;
  dirty=true;
  syncHL();
  renderPreview();
  updateMeta();
  clearTimeout(saveTimer);
  if(!running) saveTimer=setTimeout(save,800);
}
async function reloadDoc(){
  const d=await api(API+"/doc?name="+encodeURIComponent(cur),undefined,true);
  if(!d) return;
  docMtime=d.mtime;
  if(dirty) return;            // never clobber the human's unsaved edits
  editor.value=d.content;
  if(mode==="edit") syncHL(); else renderPreview();
  updateMeta();
}

// ---- agent chat (same rendering as the studio chat) ----
function argSummary(name,args){
  if(args==null) return "";
  if(typeof args!=="object") return String(args).slice(0,160);
  const a=args;
  const pick=a.path||a.file_path||a.file||a.filename;
  if(name==="bash"||name==="shell") return (a.command||a.cmd||"").slice(0,160);
  if(pick) return String(pick);
  try{return JSON.stringify(a).slice(0,160);}catch(e){return "";}
}
function blockHtml(b,k,live){
  const at=` data-k="${k}"${live?' data-live="1"':''}`;
  if(b.kind==="text") return `<div class="md">${md(b.text)}</div>`;
  if(b.kind==="thinking")
    return `<details class="aux think"${at}><summary>thinking</summary>`
      +`<div class="body2">${esc(b.text)}</div></details>`;
  if(b.kind==="subagent")
    return `<details class="aux sub"${at}><summary>subagent: ${esc(b.agent)}<span class="arg">${esc((b.task||"").slice(0,80))}</span></summary>`
      +`<div class="body2">${esc((b.result&&b.result.text)||"")}</div></details>`;
  if(b.kind==="tool"){
    const err=b.result&&b.result.isError?" err":"";
    const res=b.result?esc(b.result.text||""):"(running…)";
    return `<details class="aux tool${err}"${at}><summary>${esc(b.name||"tool")}<span class="arg">${esc(argSummary(b.name,b.args))}</span></summary>`
      +`<div class="body2">${res}</div></details>`;
  }
  return "";
}
// The transcript only updates at message boundaries, so this bubble is the
// signal that a (possibly long) turn is in flight. cont = joins an agent group.
const typingHtml=cont=>`<div class="turn assistant typing${cont?' cont':''}">${cont?'':'<div class="role">Agent</div>'}`
  +`<div class="body"><span class="tdot"></span><span class="tdot"></span><span class="tdot"></span></div></div>`;
const autoOpened=new Set();       // details we opened for the live stream (vs. user-opened)
function renderTurns(turns){
  if(sending && turns.length>sentBase){ queue.shift(); sending=false; }
  lastTurns=turns;
  const display = queue.length
    ? turns.concat(queue.map(m=>({role:"user",blocks:[{kind:"text",text:m}]})))
    : turns;
  const log=$("#plog");
  // Key on content size too: a live thinking/text block grows without the
  // turn or block count changing, and the re-render must still happen.
  const key=JSON.stringify(display.map(t=>[t.role,t.blocks.length,!!t.live,
    t.blocks.reduce((n,b)=>n+(b.text||"").length+((b.result&&b.result.text)||"").length,0)]))+"|"+queue.join("\x01")+"|"+(running?1:0);
  if(key===turnsKey) return;     // avoid clobbering scroll/details when nothing changed
  turnsKey=key;
  const atBottom=log.scrollHeight-log.scrollTop-log.clientHeight<80;
  if(!display.length && !running){
    log.innerHTML='<div class="empty">No conversation yet.<br>'
      +'<button class="primary" id="cleanempty">Clean up proposal</button></div>';
    $("#cleanempty").onclick=()=>sendCommand("/polish");
    return;
  }
  const parts=display.map((t,ti)=>{
    const who=t.role==="user"?"You":"Agent";
    const cont=ti>0&&display[ti-1].role===t.role;  // same speaker: group the bubbles
    const last=t.live?t.blocks.length-1:-1;      // the block still streaming in
    const body=t.role==="user"
      ? `<div class="md">${md(t.blocks.map(b=>b.text||"").join("\n"))}</div>`
      : t.blocks.map((b,bi)=>blockHtml(b,ti+"."+bi,bi===last)).join("");
    return `<div class="turn ${t.role}${cont?' cont':''}">${cont?'':`<div class="role">${who}</div>`}<div class="body">${body}</div></div>`;
  });
  if(running)
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
function refreshControls(){
  $("#psend").disabled=!cur;
  $("#pmsg").disabled=!cur;
  $("#polishbtn").disabled=!cur;
  $("#resetchatbtn").disabled=!cur||running;
  $("#stopbtn").hidden=!running;
  $("#renamebtn").disabled=!cur||running;
  $("#dupbtn").disabled=!cur||running;
  $("#deletebtn").disabled=!cur||running;
  $("#viewtoggle").disabled=!cur;
  editor.readOnly=!cur;
}
function bindStream(){
  if(es) es.close(); es=null; turnsKey="";
  if(!cur) return;
  es=new EventSource(API+"/agent/stream?name="+encodeURIComponent(cur));
  es.onmessage=async ev=>{
    const d=JSON.parse(ev.data);
    if(d.error){toast(d.error);return;}
    if(!d.selected) return;
    const was=running; running=!!d.running;
    renderTurns(d.turns||[]);
    $("#cost").textContent = d.cost>0.005 ? "$"+d.cost.toFixed(2) : "";
    if(d.doc && d.doc.mtime && d.doc.mtime!==docMtime) reloadDoc();
    refreshControls(); updateMeta();
    if(was && !running){
      if(sending){ if(lastTurns.length<=sentBase) queue.shift(); sending=false; }
      if(dirty) await save();
      else await reloadDoc();   // turn ended: show the agent's final edits
      pump();
    }
  };
  es.onerror=()=>{};
}
function autosizeMsg(){const t=$("#pmsg");t.style.height="auto";t.style.height=Math.min(t.scrollHeight,180)+"px";}
function sendMsg(){
  if(!cur) return;
  const text=$("#pmsg").value.trim();
  if(!text) return;
  $("#pmsg").value=""; autosizeMsg();
  sendCommand(text);
}
function sendCommand(text){
  if(!cur || !text) return;
  queue.push(text);
  renderTurns(lastTurns);
  pump();
}
async function pump(){
  if(sending || running || !cur || !queue.length) return;
  sending=true; sentBase=lastTurns.length;
  if(dirty) await save();
  const ok=await api(API+"/agent/chat",{message:queue[0]});
  if(ok){ running=true; renderTurns(lastTurns); refreshControls(); updateMeta(); }
  else { sending=false; queue.shift(); renderTurns(lastTurns); }
}
async function stopAgent(){ await api(API+"/agent/stop",{}); }
async function resetChat(){
  if(!cur || running) return;
  if(!await askConfirm({
    title:"Clear agent conversation?",
    text:"The proposal file stays unchanged.",
    danger:true,
    ok:"New chat",
  })) return;
  const d=await api(API+"/agent/reset",{});
  if(!d) return;
  lastTurns=[]; queue=[]; sending=false; turnsKey=""; autoOpened.clear();
  renderTurns([]);
  refreshControls();
}

// ---- proposal list / selection ----
function visibleProposals(){
  const q=$("#psearch").value.trim().toLowerCase();
  return proposals.filter(p=>!q || p.name.toLowerCase().includes(q));
}
function renderList(){
  const list=$("#plist");
  $("#pcount").textContent=proposals.length ? String(proposals.length) : "";
  if(!proposals.length){
    list.innerHTML='<div class="muted">no proposals yet</div>';
    return;
  }
  const items=visibleProposals();
  if(!items.length){
    list.innerHTML='<div class="muted">no matches</div>';
    return;
  }
  list.innerHTML=items.map(p=>
    `<button class="pitem${p.name===cur?' cur':''}" data-n="${esc(p.name)}">`
    +`<span class="pn">${esc(p.name)}</span>`
    +(p.busy?'<span class="busy">editing…</span>':"")
    +`<span class="pt">${new Date(p.mtime*1000).toISOString().slice(0,10)}</span></button>`).join("");
  list.querySelectorAll(".pitem").forEach(b=>b.onclick=()=>open(b.dataset.n));
}
async function loadList(){
  const d=await api(API+"/list");
  if(!d) return;
  proposals=d.items;
  renderList();
  return proposals;
}

async function open(name){
  if(dirty && !await save()) return;     // don't lose edits when switching
  const d=await api(API+"/doc?name="+encodeURIComponent(name));
  if(!d) return;
  cur=d.name; dirty=false; docMtime=d.mtime; running=false;
  lastTurns=[]; queue=[]; sending=false; turnsKey=""; autoOpened.clear();
  editor.value=d.content;
  $("#docname").textContent=cur+".md";
  document.title="Proposals · "+cur;
  history.replaceState(null,"","/proposals?p="+encodeURIComponent(cur));
  renderList();
  setMode(d.content.trim()?"view":"edit");
  updateMeta();
  bindStream();
  refreshControls();
}

function cleanName(raw){
  return (raw||"").trim().replace(/\.md$/,"");
}
function titleFromName(name){
  return cleanName(name).replace(/[_-]+/g," ").replace(/\s+/g," ").trim();
}
function clearSelection(){
  if(es) es.close(); es=null;
  cur=null; dirty=false; running=false; docMtime=0; turnsKey="";
  lastTurns=[]; queue=[]; sending=false; autoOpened.clear();
  editor.value=""; hl.textContent="";
  $("#docname").textContent="";
  $("#cost").textContent="";
  document.title="Proposals";
  history.replaceState(null,"","/proposals");
  mode="view";
  $("#docview").className="view";
  $("#viewtoggle").textContent="✎ Edit";
  preview.innerHTML='<div class="empty">Pick a proposal on the left, or create a new one.</div>';
  $("#plog").innerHTML='<div class="muted">Chat with an agent that edits this proposal directly — same workflow as the writeup studio.</div>';
  renderList();
  updateMeta();
  refreshControls();
}

async function newProposal(){
  const name=await askName({
    title:"New proposal",
    text:"Use letters, digits, '.', '-', or '_'.",
    value:"empirical_",
    ok:"Create",
  });
  if(!name) return;
  const d=await api(API+"/create",{name,content:"# "+titleFromName(name)+"\n\n"});
  if(!d) return;
  await loadList();
  await open(d.name);
  setMode("edit"); editor.focus();
}

async function renameProposal(){
  if(!cur || running) return;
  if(dirty && !await save()) return;
  const name=await askName({
    title:"Rename proposal",
    text:"The .md extension is optional.",
    value:cur,
    ok:"Rename",
  });
  if(!name || name===cur) return;
  const d=await api(API+"/rename",{newName:name});
  if(!d) return;
  cur=d.name; dirty=false; docMtime=d.mtime||docMtime;
  $("#docname").textContent=cur+".md";
  document.title="Proposals · "+cur;
  history.replaceState(null,"","/proposals?p="+encodeURIComponent(cur));
  bindStream();
  await loadList();
  updateMeta("renamed");
}

async function duplicateProposal(){
  if(!cur || running) return;
  if(dirty && !await save()) return;
  let base=cur+"_copy", i=2;
  const names=new Set(proposals.map(p=>p.name));
  while(names.has(base)) base=cur+"_copy_"+(i++);
  const name=await askName({
    title:"Duplicate proposal",
    text:"The new proposal will start with the same markdown.",
    value:base,
    ok:"Duplicate",
  });
  if(!name) return;
  const d=await api(API+"/duplicate",{newName:name});
  if(!d) return;
  await loadList();
  await open(d.name);
  setMode("edit");
}

async function deleteProposal(){
  if(!cur || running) return;
  if(!await askConfirm({
    title:"Delete "+cur+".md?",
    text:dirty ? "Unsaved editor changes will be discarded." : "This cannot be undone.",
    danger:true,
    ok:"Delete",
  })) return;
  const old=cur;
  const d=await api(API+"/delete",{});
  if(!d) return;
  toast("deleted "+old+".md");
  clearSelection();
  const items=await loadList();
  if(items && items.length) open(items.reduce((a,b)=>a.mtime>b.mtime?a:b).name);
}

// ---- wiring ----
$("#viewtoggle").onclick=()=>setMode(mode==="view"?"edit":"view");
$("#newbtn").onclick=newProposal;
$("#renamebtn").onclick=renameProposal;
$("#dupbtn").onclick=duplicateProposal;
$("#deletebtn").onclick=deleteProposal;
$("#psearch").addEventListener("input",renderList);
$("#modalCancel").onclick=()=>closeModal(null);
$("#modalOk").onclick=()=>closeModal($("#modalInput").hidden?true:$("#modalInput").value);
$("#modal").addEventListener("mousedown",e=>{ if(e.target===$("#modal")) closeModal(null); });
$("#modalInput").addEventListener("keydown",e=>{
  if(e.key==="Enter"){e.preventDefault();closeModal($("#modalInput").value);}
  else if(e.key==="Escape"){e.preventDefault();closeModal(null);}
});
makeResizer($("#rsSide"),document.querySelector("aside"),"pp.sideW",{min:220,max:520});
makeResizer($("#rsChat"),$("#chatcol"),"pp.chatW",{min:300,max:800,fromRight:true});
$("#psend").onclick=()=>sendMsg();
$("#polishbtn").onclick=()=>sendCommand("/polish");
$("#resetchatbtn").onclick=resetChat;
$("#stopbtn").onclick=stopAgent;
$("#pmsg").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendMsg();}});
$("#pmsg").addEventListener("input",autosizeMsg);
document.addEventListener("click",e=>{
  if(e.target.tagName==="IMG" && e.target.closest("#preview,#plog")){
    $("#lightbox img").src=e.target.src; $("#lightbox").hidden=false;
  }
});
$("#lightbox").onclick=()=>$("#lightbox").hidden=true;
document.addEventListener("keydown",e=>{
  if(e.key==="Escape" && !$("#modal").hidden) closeModal(null);
  if(e.key==="Escape") $("#lightbox").hidden=true;
});
editor.addEventListener("input",onEdit);
editor.addEventListener("scroll",()=>{hl.scrollTop=editor.scrollTop;hl.scrollLeft=editor.scrollLeft;});
editor.addEventListener("keydown",e=>{
  if(e.key==="Tab"){e.preventDefault();const c=editor.selectionStart;
    editor.setRangeText("  ",c,editor.selectionEnd,"end");onEdit();}
  else if((e.metaKey||e.ctrlKey)&&e.key==="s"){e.preventDefault();save();}
});
addEventListener("beforeunload",()=>{
  if(cur && dirty && !running && navigator.sendBeacon)
    navigator.sendBeacon(API+"/doc",new Blob([JSON.stringify({name:cur,content:editor.value})],{type:"application/json"}));
});

async function init(){
  editor.readOnly=true;
  refreshControls();
  const items=await loadList();
  const pre=new URLSearchParams(location.search).get("p");
  if(pre) open(pre);
  else if(items && items.length){
    // open whatever was edited last
    open(items.reduce((a,b)=>a.mtime>b.mtime?a:b).name);
  }
}
init();
</script>
</body>
</html>
"""

# Shared palette + markdown-editor pieces come from src.theme (single source).
INDEX_HTML = (
    INDEX_HTML.replace("/*__PALETTE__*/", PALETTE_CSS)
    .replace("<!--__FAVICON__-->", FAVICON_LINK)
    .replace("/*__CONTROLS_CSS__*/", CONTROLS_CSS)
    .replace("/*__CHAT_CSS__*/", CHAT_CSS)
    .replace("//__APP_JS__", APP_JS)
    .replace("//__API_JS__", API_JS)
    .replace("/*__EDITOR_CSS__*/", EDITOR_CSS)
    .replace("/*__PREVIEW_CSS__*/", PREVIEW_CSS)
    .replace("//__RESIZER_JS__", RESIZER_JS)
    .replace("//__PROGRESS_JS__", PROGRESS_JS)
    .replace("/*__PROGRESS_CSS__*/", PROGRESS_CSS)
    .replace("/*__RESIZER_CSS__*/", RESIZER_CSS)
    .replace("//__HIGHLIGHT_JS__", HIGHLIGHT_JS)
)
