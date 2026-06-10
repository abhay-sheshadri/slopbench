"""Proposals manager — mounted under ``/proposals`` by the agent viewer.

Browse, read, edit, and create the research proposals in ``proposals/`` with
the same markdown editor/preview as the blogpost studio (shared via
:mod:`src.theme`). Like the studio, this has no server of its own:
:func:`handle` is called by the viewer's request handler and claims paths
under ``/proposals``.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from src.agent_viewer import ROOT
from src.theme import EDITOR_CSS, HIGHLIGHT_JS, PALETTE_CSS, PREVIEW_CSS

PREFIX = "/proposals"
PROPOSALS_DIR = ROOT / "proposals"

# Plain flat filenames only — no separators, nothing hidden.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _path_for(name: str):
    """proposals/<name>.md for a validated bare name (``.md`` optional)."""
    name = (name or "").strip()
    if name.endswith(".md"):
        name = name[:-3]
    if not _NAME_RE.match(name):
        raise ValueError("proposal names use letters, digits, '.', '-', '_'")
    return PROPOSALS_DIR / f"{name}.md"


def list_proposals() -> list[dict]:
    items = []
    for p in sorted(PROPOSALS_DIR.glob("*.md")):
        st = p.stat()
        items.append({"name": p.stem, "mtime": st.st_mtime, "size": st.st_size})
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
    """Write (or create) a proposal. Returns its normalized name + mtime."""
    p = _path_for(name)
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
            if path in ("/", "/index.html"):
                h._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/list":
                h._json({"items": list_proposals()})
            elif path == "/api/doc":
                name = (parse_qs(parsed.query).get("name") or [""])[0]
                try:
                    h._json(read_doc(name))
                except ValueError as exc:
                    h._json({"error": str(exc)}, code=404)
            else:
                h._send(404, b"not found", "text/plain")
        else:
            if path == "/api/doc":
                body = h._read_body()
                content = body.get("content")
                if not isinstance(content, str):
                    return h._json({"error": "missing content"}, code=400)
                try:
                    h._json({"ok": True, **save_doc(body.get("name") or "", content)})
                except (ValueError, OSError) as exc:
                    h._json({"error": str(exc)}, code=400)
            else:
                h._send(404, b"not found", "text/plain")
    except (BrokenPipeError, ConnectionError, OSError):
        pass
    except Exception as exc:  # noqa: BLE001 - never let a handler kill the server
        try:
            h._json({"error": f"{type(exc).__name__}: {exc}"}, code=500)
        except Exception:
            pass
    return True


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

header{display:flex;align-items:center;gap:12px;padding:12px;background:var(--panel);
  border-bottom:1px solid var(--border);flex:0 0 auto}
header .spacer{flex:1}

main{flex:1;display:flex;min-height:0}
aside{width:300px;flex:0 0 auto;background:var(--panel);border-right:1px solid var(--border);
  display:flex;flex-direction:column;padding:10px}
#newbtn{margin-bottom:10px}
#plist{flex:1;overflow:auto;display:flex;flex-direction:column;gap:1px}
.pitem{display:flex;align-items:baseline;gap:8px;text-align:left;background:transparent;
  border:1px solid transparent;border-radius:6px;padding:7px 9px;cursor:pointer;width:100%;color:var(--fg)}
.pitem:hover{background:var(--panel2);border-color:var(--border)}
.pitem.cur{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.pitem .pn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:600}
.pitem .pt{color:var(--faint);font-size:10px;white-space:nowrap;font-family:var(--mono)}
.muted{color:var(--muted);padding:14px;text-align:center;font-size:12.5px}

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
.empty{color:var(--muted);text-align:center;margin-top:16vh;padding:0 24px;line-height:1.6}

.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--panel3);
  color:var(--err);border:1px solid var(--border);padding:8px 14px;border-radius:8px;opacity:0;
  transition:opacity .2s;pointer-events:none;z-index:9999;font-size:13px}
.toast.show{opacity:1}
</style>
</head>
<body>
<header>
  <nav class="appnav"><a href="/">🔎 Runs</a><a href="/studio">📝 Studio</a><a class="on" href="/proposals">🗒 Proposals</a></nav>
  <span class="spacer"></span>
</header>
<main>
  <aside>
    <button class="primary" id="newbtn">＋ New proposal</button>
    <div id="plist"><div class="muted">loading…</div></div>
  </aside>
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
<script>
const $ = s => document.querySelector(s);
const API = "/proposals/api";
const editor=$("#editor"), preview=$("#preview"), hl=$("#editorHL");
let cur=null, dirty=false, mode="view", saveTimer;

marked.setOptions({breaks:true, gfm:true});

function toast(m){const t=$("#toast");t.textContent=m;t.classList.add("show");
  clearTimeout(toast._t);toast._t=setTimeout(()=>t.classList.remove("show"),3200);}
function esc(s){return (s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}

//__HIGHLIGHT_JS__
function syncHL(){
  hl.innerHTML=highlightMarkdown(editor.value)+"\n";   // trailing \n keeps last line height in sync
  hl.scrollTop=editor.scrollTop; hl.scrollLeft=editor.scrollLeft;
}
function renderPreview(){ preview.innerHTML=marked.parse(editor.value||""); }
function updateMeta(status){
  const n=(editor.value.match(/\S+/g)||[]).length;
  status = status || (dirty?"unsaved":(cur?"saved":""));
  $("#meta").innerHTML=(n?n.toLocaleString()+" words":"")+(status?` <span class="dot">·</span> ${status}`:"");
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
      headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  }catch(e){ toast("network error: "+e.message); return null; }
  const d=await r.json().catch(()=>({}));
  if(!r.ok){toast(d.error||"failed");return null;}
  return d;
}

async function save(){
  clearTimeout(saveTimer);
  if(!cur || !dirty) return true;
  updateMeta("saving…");
  const d=await api(API+"/doc",{name:cur,content:editor.value});
  if(!d){updateMeta();return false;}
  dirty=false; updateMeta();
  return true;
}
function onEdit(){
  if(!cur) return;
  dirty=true;
  syncHL();
  renderPreview();
  updateMeta();
  clearTimeout(saveTimer);
  saveTimer=setTimeout(save,800);
}

async function loadList(){
  const d=await api(API+"/list");
  if(!d) return;
  const list=$("#plist");
  if(!d.items.length){ list.innerHTML='<div class="muted">no proposals yet</div>'; return; }
  list.innerHTML=d.items.map(p=>
    `<button class="pitem${p.name===cur?' cur':''}" data-n="${esc(p.name)}">`
    +`<span class="pn">${esc(p.name)}</span>`
    +`<span class="pt">${new Date(p.mtime*1000).toISOString().slice(0,10)}</span></button>`).join("");
  list.querySelectorAll(".pitem").forEach(b=>b.onclick=()=>open(b.dataset.n));
  return d.items;
}

async function open(name){
  if(dirty && !await save()) return;     // don't lose edits when switching
  const d=await api(API+"/doc?name="+encodeURIComponent(name));
  if(!d) return;
  cur=d.name; dirty=false;
  editor.value=d.content; editor.readOnly=false;
  $("#docname").textContent=cur+".md";
  document.title="Proposals · "+cur;
  history.replaceState(null,"","/proposals?p="+encodeURIComponent(cur));
  $("#plist").querySelectorAll(".pitem").forEach(b=>b.classList.toggle("cur",b.dataset.n===cur));
  setMode(d.content.trim()?"view":"edit");
  updateMeta();
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
editor.addEventListener("input",onEdit);
editor.addEventListener("scroll",()=>{hl.scrollTop=editor.scrollTop;hl.scrollLeft=editor.scrollLeft;});
editor.addEventListener("keydown",e=>{
  if(e.key==="Tab"){e.preventDefault();const c=editor.selectionStart;
    editor.setRangeText("  ",c,editor.selectionEnd,"end");onEdit();}
  else if((e.metaKey||e.ctrlKey)&&e.key==="s"){e.preventDefault();save();}
});
addEventListener("beforeunload",()=>{
  if(cur && dirty && navigator.sendBeacon)
    navigator.sendBeacon(API+"/doc",new Blob([JSON.stringify({name:cur,content:editor.value})],{type:"application/json"}));
});

async function init(){
  editor.readOnly=true;
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
