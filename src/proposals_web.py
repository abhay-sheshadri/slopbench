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
import threading
from urllib.parse import parse_qs, urlparse

from src.agent_viewer import ROOT
from src.blogpost_studio_web import _sse  # generic over DocAgentSession
from src.proposal_studio import ProposalSession
from src.theme import EDITOR_CSS, HIGHLIGHT_JS, PALETTE_CSS, PREVIEW_CSS

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


def _session(name: str, *, create: bool) -> ProposalSession | None:
    """The agent session for a proposal (validated), created on demand."""
    p = _path_for(name)
    with _LOCK:
        s = SESSIONS.get(p.stem)
        if s is None and create:
            s = SESSIONS[p.stem] = ProposalSession(p.stem)
        return s


def list_proposals() -> list[dict]:
    items = []
    for p in sorted(PROPOSALS_DIR.glob("*.md")):
        st = p.stat()
        s = SESSIONS.get(p.stem)
        items.append(
            {
                "name": p.stem,
                "mtime": st.st_mtime,
                "size": st.st_size,
                "busy": bool(s and s.is_running()),
            }
        )
    return items


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


# --------------------------------------------------------------------------- #
# Request handling (called from the agent viewer's Handler)
# --------------------------------------------------------------------------- #
def handle(h, method: str) -> bool:
    """Serve one request if its path is under /proposals. Returns whether it was ours."""
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
.mini2{font-size:11px;padding:3px 9px}

header{display:flex;align-items:center;gap:12px;padding:12px;background:var(--panel);
  border-bottom:1px solid var(--border);flex:0 0 auto}
header .spacer{flex:1}

main{flex:1;display:flex;min-height:0}
aside{width:280px;flex:0 0 auto;background:var(--panel);border-right:1px solid var(--border);
  display:flex;flex-direction:column;padding:10px}
#newbtn{margin-bottom:10px}
#plist{flex:1;overflow:auto;display:flex;flex-direction:column;gap:1px}
.pitem{display:flex;align-items:baseline;gap:8px;text-align:left;background:transparent;
  border:1px solid transparent;border-radius:6px;padding:7px 9px;cursor:pointer;width:100%;color:var(--fg)}
.pitem:hover{background:var(--panel2);border-color:var(--border)}
.pitem.cur{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.pitem .pn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:600}
.pitem .pt{color:var(--faint);font-size:10px;white-space:nowrap;font-family:var(--mono)}
.pitem .busy{color:var(--warn);font-size:10px}
.muted{color:var(--muted);padding:14px;text-align:center;font-size:12.5px}

/* chat with the proposal-editing agent (same workflow as the writeup studio) */
#chatcol{width:360px;flex:0 0 auto;display:flex;flex-direction:column;min-height:0;
  background:var(--panel);border-right:1px solid var(--border)}
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
/* image lightbox (as in the studio / agent viewer) */
.lightbox{position:fixed;inset:0;z-index:9999;background:rgba(3,5,10,.88);display:flex;
  align-items:center;justify-content:center;padding:40px}
.lightbox[hidden]{display:none}
.lightbox img{max-width:95vw;max-height:90vh;object-fit:contain;background:#fff;border-radius:6px;
  box-shadow:0 14px 45px rgba(0,0,0,.55)}
.tdot{display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--muted);
  margin-right:3px;animation:tb 1.2s infinite}
.tdot:nth-child(2){animation-delay:.15s}.tdot:nth-child(3){animation-delay:.3s}
@keyframes tb{0%,60%,100%{opacity:.25}30%{opacity:1}}
.composer{display:flex;gap:8px;padding:10px;border-top:1px solid var(--border)}
.composer textarea{flex:1;resize:none;background:var(--panel2);color:var(--fg);
  border:1px solid var(--border);border-radius:8px;padding:8px 10px;font:13px/1.45 var(--sans);outline:none}
.composer textarea:focus{border-color:var(--accent)}

#doc{flex:1;display:flex;flex-direction:column;min-width:0;background:var(--bg)}
.docbar{display:flex;align-items:center;gap:10px;padding:7px 14px;border-bottom:1px solid var(--border);background:var(--panel)}
#viewtoggle{font-size:12px;padding:4px 13px;color:var(--muted)}
#viewtoggle:hover:not(:disabled){color:var(--fg)}
#docname{color:var(--muted);font-family:var(--mono);font-size:12px}
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
.empty{color:var(--muted);text-align:center;margin-top:14vh;padding:0 24px;line-height:1.6}

.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--panel3);
  color:var(--err);border:1px solid var(--border);padding:8px 14px;border-radius:8px;opacity:0;
  transition:opacity .2s;pointer-events:none;z-index:9999;font-size:13px}
.toast.show{opacity:1}
@media (max-width:1100px){ #chatcol{width:300px} aside{width:220px} }
</style>
</head>
<body>
<header>
  <nav class="appnav"><a href="/">🔎 Runs</a><a class="on" href="/proposals">🗒 Proposals</a><a href="/studio">📝 Studio</a></nav>
  <span class="spacer"></span>
</header>
<main>
  <aside>
    <button class="primary" id="newbtn">＋ New proposal</button>
    <div id="plist"><div class="muted">loading…</div></div>
  </aside>
  <section id="chatcol">
    <div class="chathead">Agent <span class="meta" id="cost"></span><span class="spacer"></span>
      <button class="mini2" id="polishbtn" title="Ask the agent to clean up this proposal">✨ Clean up</button>
      <button class="mini2" id="stopbtn" hidden>■ Stop</button>
    </div>
    <div id="plog"><div class="muted">Chat with an agent that edits this proposal directly — same workflow as the writeup studio.</div></div>
    <div class="composer">
      <textarea id="pmsg" rows="2" placeholder="Ask for edits… (Enter to send)"></textarea>
      <button class="primary" id="psend">Send</button>
    </div>
  </section>
  <section id="doc">
    <div class="docbar">
      <button id="viewtoggle">✎ Edit</button>
      <span id="docname"></span>
      <span class="spacer"></span>
      <span class="meta" id="meta"></span>
    </div>
    <div id="docview" class="view">
      <div class="pane editpane"><div class="editwrap"><pre id="editorHL" aria-hidden="true"></pre><textarea id="editor" spellcheck="false"
        placeholder="Write the proposal in markdown. Changes autosave."></textarea></div></div>
      <div class="pane previewpane"><div id="preview"><div class="empty">Pick a proposal on the left, or create a new one.</div></div></div>
    </div>
  </section>
</main>
<div class="toast" id="toast"></div>
<div class="lightbox" id="lightbox" hidden><img alt=""></div>
<script>
const $ = s => document.querySelector(s);
const API = "/proposals/api";
const editor=$("#editor"), preview=$("#preview"), hl=$("#editorHL");
let cur=null, dirty=false, mode="view", saveTimer, docMtime=0, running=false, es=null, turnsKey="";

marked.setOptions({breaks:true, gfm:true});

function toast(m){const t=$("#toast");t.textContent=m;t.classList.add("show");
  clearTimeout(toast._t);toast._t=setTimeout(()=>t.classList.remove("show"),3200);}
function esc(s){return (s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
const md=t=>marked.parse(t||"");

//__HIGHLIGHT_JS__
function syncHL(){
  hl.innerHTML=highlightMarkdown(editor.value)+"\n";   // trailing \n keeps last line height in sync
  hl.scrollTop=editor.scrollTop; hl.scrollLeft=editor.scrollLeft;
}
function renderPreview(){ preview.innerHTML=md(editor.value); }
function updateMeta(status){
  const n=(editor.value.match(/\S+/g)||[]).length;
  status = status || (running?"agent editing…":(dirty?"unsaved":(cur?"saved":"")));
  $("#meta").innerHTML=(n?n.toLocaleString()+" words":"")+(status?` <span class="dot">·</span> ${esc(status)}`:"");
}
function setMode(m){
  mode=m;
  $("#docview").className=m;
  $("#viewtoggle").textContent = m==="view" ? "✎ Edit" : "👁 Preview";
  if(m==="view") renderPreview(); else syncHL();
}

async function api(url,body){
  let r;
  try{
    r=await fetch(url, body===undefined?{}:{method:"POST",
      headers:{"Content-Type":"application/json"},body:JSON.stringify({name:cur||undefined,...body})});
  }catch(e){ toast("network error: "+e.message); return null; }
  const d=await r.json().catch(()=>({}));
  if(!r.ok){toast(d.error||"failed");return null;}
  return d;
}

// ---- document ----
async function save(){
  clearTimeout(saveTimer);
  if(!cur || !dirty || running) return !running;
  updateMeta("saving…");
  const d=await api(API+"/doc",{content:editor.value});
  if(!d){updateMeta();return false;}
  dirty=false; docMtime=d.mtime; updateMeta();
  return true;
}
function onEdit(){
  if(!cur || running) return;
  dirty=true;
  syncHL();
  renderPreview();
  updateMeta();
  clearTimeout(saveTimer);
  saveTimer=setTimeout(save,800);
}
async function reloadDoc(){
  const d=await api(API+"/doc?name="+encodeURIComponent(cur));
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
  const log=$("#plog");
  // Key on content size too: a live thinking/text block grows without the
  // turn or block count changing, and the re-render must still happen.
  const key=JSON.stringify(turns.map(t=>[t.role,t.blocks.length,!!t.live,
    t.blocks.reduce((n,b)=>n+(b.text||"").length+((b.result&&b.result.text)||"").length,0)]))+"|"+(running?1:0);
  if(key===turnsKey) return;     // avoid clobbering scroll/details when nothing changed
  turnsKey=key;
  const atBottom=log.scrollHeight-log.scrollTop-log.clientHeight<80;
  if(!turns.length && !running){
    log.innerHTML='<div class="muted">Chat with an agent that edits this proposal directly — '
      +'try <b>✨ Clean up</b>, or ask for specific changes.</div>';
    return;
  }
  const parts=turns.map((t,ti)=>{
    const who=t.role==="user"?"You":"Agent";
    const cont=ti>0&&turns[ti-1].role===t.role;  // same speaker: group the bubbles
    const last=t.live?t.blocks.length-1:-1;      // the block still streaming in
    const body=t.role==="user"
      ? `<div class="md">${md(t.blocks.map(b=>b.text||"").join("\n"))}</div>`
      : t.blocks.map((b,bi)=>blockHtml(b,ti+"."+bi,bi===last)).join("");
    return `<div class="turn ${t.role}${cont?' cont':''}">${cont?'':`<div class="role">${who}</div>`}<div class="body">${body}</div></div>`;
  });
  if(running && !(turns.length && turns[turns.length-1].live))
    parts.push(typingHtml(turns.length>0&&turns[turns.length-1].role==="assistant"));
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
  $("#psend").disabled=!cur||running;
  $("#pmsg").disabled=!cur||running;
  $("#polishbtn").disabled=!cur||running;
  $("#stopbtn").hidden=!running;
  editor.readOnly=!cur||running;     // the agent owns the file mid-turn
}
function bindStream(){
  if(es) es.close(); es=null; turnsKey="";
  if(!cur) return;
  es=new EventSource(API+"/agent/stream?name="+encodeURIComponent(cur));
  es.onmessage=ev=>{
    const d=JSON.parse(ev.data);
    if(d.error){toast(d.error);return;}
    if(!d.selected) return;
    const was=running; running=!!d.running;
    renderTurns(d.turns||[]);
    $("#cost").textContent = d.cost>0.005 ? "$"+d.cost.toFixed(2) : "";
    if(d.doc && d.doc.mtime && d.doc.mtime!==docMtime) reloadDoc();
    refreshControls(); updateMeta();
    if(was && !running) reloadDoc();   // turn ended: show the agent's final edits
  };
  es.onerror=()=>{};
}
async function sendMsg(text){
  text=(text||$("#pmsg").value).trim();
  if(!text||!cur||running) return;
  const d=await api(API+"/agent/chat",{message:text});
  if(!d) return;
  $("#pmsg").value="";
  running=true; refreshControls(); updateMeta();
}
async function stopAgent(){ await api(API+"/agent/stop",{}); }

// ---- proposal list / selection ----
async function loadList(){
  const d=await api(API+"/list");
  if(!d) return;
  const list=$("#plist");
  if(!d.items.length){ list.innerHTML='<div class="muted">no proposals yet</div>'; return; }
  list.innerHTML=d.items.map(p=>
    `<button class="pitem${p.name===cur?' cur':''}" data-n="${esc(p.name)}">`
    +`<span class="pn">${esc(p.name)}</span>`
    +(p.busy?'<span class="busy">editing…</span>':"")
    +`<span class="pt">${new Date(p.mtime*1000).toISOString().slice(0,10)}</span></button>`).join("");
  list.querySelectorAll(".pitem").forEach(b=>b.onclick=()=>open(b.dataset.n));
  return d.items;
}

async function open(name){
  if(dirty && !await save()) return;     // don't lose edits when switching
  const d=await api(API+"/doc?name="+encodeURIComponent(name));
  if(!d) return;
  cur=d.name; dirty=false; docMtime=d.mtime; running=false;
  editor.value=d.content;
  $("#docname").textContent=cur+".md";
  document.title="Proposals · "+cur;
  history.replaceState(null,"","/proposals?p="+encodeURIComponent(cur));
  $("#plist").querySelectorAll(".pitem").forEach(b=>b.classList.toggle("cur",b.dataset.n===cur));
  setMode(d.content.trim()?"view":"edit");
  updateMeta();
  bindStream();
  refreshControls();
}

async function newProposal(){
  const raw=prompt("New proposal name (letters, digits, '.', '-', '_'):","empirical_");
  if(!raw) return;
  const d=await api(API+"/doc",{name:raw.trim(),content:"# "+raw.trim().replace(/_/g," ")+"\n\n"});
  if(!d) return;
  await loadList();
  await open(d.name);
  setMode("edit"); editor.focus();
}

// ---- wiring ----
$("#viewtoggle").onclick=()=>setMode(mode==="view"?"edit":"view");
$("#newbtn").onclick=newProposal;
$("#psend").onclick=()=>sendMsg();
$("#polishbtn").onclick=()=>sendMsg("/polish");
$("#stopbtn").onclick=stopAgent;
$("#pmsg").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendMsg();}});
document.addEventListener("click",e=>{
  if(e.target.tagName==="IMG" && e.target.closest("#preview,#plog")){
    $("#lightbox img").src=e.target.src; $("#lightbox").hidden=false;
  }
});
$("#lightbox").onclick=()=>$("#lightbox").hidden=true;
document.addEventListener("keydown",e=>{ if(e.key==="Escape") $("#lightbox").hidden=true; });
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
    .replace("/*__EDITOR_CSS__*/", EDITOR_CSS)
    .replace("/*__PREVIEW_CSS__*/", PREVIEW_CSS)
    .replace("//__HIGHLIGHT_JS__", HIGHLIGHT_JS)
)
