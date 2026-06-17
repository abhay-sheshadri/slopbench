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
}

/* Shared segmented nav between the two apps (Runs | Studio): same-tab links,
   identical look on both pages so switching feels like one site. */
.appnav{display:flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;flex:0 0 auto}
.appnav a{padding:6px 14px;font-size:12.5px;font-weight:700;color:var(--muted);
  text-decoration:none;background:var(--panel2);transition:.12s;white-space:nowrap}
.appnav a:hover{color:var(--fg)}
.appnav a.on{color:var(--fg);background:rgba(122,162,247,.16)}
.appnav a+a{border-left:1px solid var(--border)}"""

# Shared markdown editor (used by the blogpost studio and the proposals page):
# a transparent <textarea id=editor> stacked on a highlighted <pre id=editorHL>,
# plus the rendered <div id=preview>. Pages insert these by replacing the
# /*__EDITOR_CSS__*/, /*__PREVIEW_CSS__*/ and //__HIGHLIGHT_JS__ tokens.
EDITOR_CSS = """/* The edit pane is a transparent <textarea> stacked exactly on top of a
   syntax-highlighted <pre>. They MUST share every metric that affects glyph
   position (font, size, line-height, padding, wrapping) so the real caret lines
   up with the colored text behind it. */
.editwrap{position:relative;flex:1;min-width:0;overflow:hidden}
#editor,#editorHL{margin:0;border:0;position:absolute;inset:0;
  font-family:var(--mono);font-size:13.5px;line-height:1.75;tab-size:2;
  white-space:pre-wrap;word-break:break-word;overflow-wrap:break-word;
  padding:32px max(26px,calc((100% - 720px)/2))}
/* Both reserve a scrollbar gutter so they wrap at the same width (the textarea's
   visible scrollbar would otherwise narrow only its text and misalign the layers). */
#editorHL{overflow-y:scroll;overflow-x:hidden;color:var(--fg);pointer-events:none;z-index:1}
#editorHL::-webkit-scrollbar{width:0;height:0}
#editor{overflow-y:scroll;overflow-x:hidden;resize:none;outline:none;z-index:2;background:transparent;
  color:transparent;-webkit-text-fill-color:transparent;caret-color:var(--accent)}
#editor::placeholder{color:var(--faint);-webkit-text-fill-color:var(--faint)}
#editor::selection{background:rgba(122,162,247,.32)}
/* markdown token colors in the editor */
.hl-h{color:var(--accent);font-weight:700}
.hl-h1{color:var(--accent)} .hl-h2{color:var(--accent)} .hl-h3{color:var(--accent2)}
.hl-h4,.hl-h5,.hl-h6{color:var(--accent2)}
.hl-b{color:var(--fg);font-weight:700} .hl-i{color:var(--fg);font-style:italic}
.hl-code{color:var(--user)} .hl-fence{color:var(--user);font-weight:600}
.hl-link{color:var(--accent2)} .hl-url{color:var(--muted)}
.hl-quote{color:var(--muted);font-style:italic} .hl-mark{color:var(--tool);font-weight:700}
.hl-hr{color:var(--faint)}"""

PREVIEW_CSS = """#preview{font-size:15px;line-height:1.75;padding:32px max(26px,calc((100% - 720px)/2))}
#preview>:first-child{margin-top:0}
#preview h1,#preview h2,#preview h3,#preview h4{line-height:1.3;margin:1.5em 0 .5em;font-weight:700}
#preview h1{font-size:1.7em;color:var(--accent)}
#preview h2{font-size:1.36em;color:var(--accent);border-bottom:1px solid var(--border);padding-bottom:.2em}
#preview h3{font-size:1.12em;color:var(--accent2)}
#preview h4{color:var(--accent2)}
#preview pre{background:var(--code-bg);border:1px solid var(--border);border-radius:8px;padding:12px;overflow:auto}
#preview code{font-family:var(--mono);font-size:.88em}
#preview p code,#preview li code{background:var(--panel2);padding:.1em .35em;border-radius:4px}
#preview table{border-collapse:collapse;font-size:.95em}
#preview td,#preview th{border:1px solid var(--border);padding:6px 10px}
#preview blockquote{border-left:3px solid var(--border);margin:.6em 0;padding-left:14px;color:var(--muted)}
#preview hr{border:0;border-top:1px solid var(--border);margin:1.8em 0}
.md-img,#preview img{max-width:100%;height:auto;border:1px solid var(--border);border-radius:8px;
  margin:12px 0;display:block;background:#fff;cursor:zoom-in}"""

HIGHLIGHT_JS = """// ---- in-editor markdown syntax highlighting (shared) ----
// We render an escaped, span-wrapped copy of the text behind a transparent
// textarea. Spans only ADD markup — they never change the text content — so the
// highlight layer stays glyph-for-glyph aligned with the real caret. Because of
// that, even an imperfect tokenization can't misalign the cursor.
function escHL(s){return s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}
function inlineHL(line){
  let s=escHL(line);
  s=s.replace(/(`+)([^`]+?)\\1/g,(m,t,inner)=>'<span class="hl-code">'+t+inner+t+'</span>');
  s=s.replace(/(\\*\\*|__)(?=\\S)([\\s\\S]+?\\S)\\1/g,(m,d,inner)=>'<span class="hl-b">'+d+inner+d+'</span>');
  s=s.replace(/(?<![\\*_\\w])([\\*_])(?=\\S)([^\\*_]+?\\S)\\1(?![\\*_\\w])/g,(m,d,inner)=>'<span class="hl-i">'+d+inner+d+'</span>');
  s=s.replace(/(\\[)([^\\]]*)(\\]\\()([^)]*)(\\))/g,(m,a,txt,b,url,c)=>'<span class="hl-link">'+a+txt+b+'</span><span class="hl-url">'+url+c+'</span>');
  return s;
}
function highlightMarkdown(src){
  let inFence=false;
  return (src||"").split("\\n").map(line=>{
    if(/^(\\s*)(```|~~~)/.test(line)){ inFence=!inFence; return '<span class="hl-fence">'+escHL(line)+'</span>'; }
    if(inFence) return '<span class="hl-code">'+escHL(line)+'</span>';
    const h=/^(\\s{0,3})(#{1,6})(\\s.*)?$/.exec(line);
    if(h) return '<span class="hl-h hl-h'+h[2].length+'">'+escHL(line)+'</span>';
    if(/^\\s{0,3}([-*_])(\\s*\\1){2,}\\s*$/.test(line)) return '<span class="hl-hr">'+escHL(line)+'</span>';
    if(/^\\s{0,3}>/.test(line)) return '<span class="hl-quote">'+inlineHL(line)+'</span>';
    const li=/^(\\s*)([-*+]|\\d+[.)])(\\s+)(.*)$/.exec(line);
    if(li) return escHL(li[1])+'<span class="hl-mark">'+escHL(li[2])+'</span>'+li[3]+inlineHL(li[4]);
    return inlineHL(line);
  }).join("\\n");
}"""

# Shared control primitives (buttons + toast) — single source of truth so the
# same action looks and behaves identically on every page. Insert via the
# /*__CONTROLS_CSS__*/ token. Button classes: base <button>, .primary (main
# action), .danger (destructive), .mini (compact). Don't redefine these per page.
CONTROLS_CSS = """button{font:inherit;color:var(--fg);background:var(--panel2);border:1px solid var(--border);
  border-radius:6px;padding:6px 12px;cursor:pointer;transition:.12s}
button:hover:not(:disabled){border-color:var(--accent)}
button:disabled{opacity:.4;cursor:not-allowed}
button.primary{background:rgba(122,162,247,.14);border-color:rgba(122,162,247,.5)}
button.primary:hover:not(:disabled){background:rgba(122,162,247,.24)}
button.danger{background:rgba(247,118,142,.12);border-color:rgba(247,118,142,.45);color:var(--err)}
button.danger:hover:not(:disabled){background:rgba(247,118,142,.2)}
button.mini{font-size:11px;padding:4px 9px}
/* Standard list-page sidebar: <aside class="side"> with, in this order, a
   .sidehead (title), a .sideacts row of full-width bulk actions (the page's
   bulk "generate" action then a .danger "Delete all"), a .sidesearch filter,
   and a .sidelist of items. Used identically by every list page so the same
   action sits in the same place everywhere. */
aside.side{width:300px;flex:0 0 auto;background:var(--panel);border-right:1px solid var(--border);
  display:flex;flex-direction:column;min-height:0}
.sidehead{padding:9px 12px;border-bottom:1px solid var(--border);font-weight:700;font-size:13px;
  display:flex;align-items:center;gap:8px}
.sidehead .spacer{flex:1}
.sideacts{display:flex;gap:6px;padding:8px 10px}
.sideacts button{flex:1}
.sidesearch{margin:0 10px 6px;width:calc(100% - 20px);background:var(--panel2);color:var(--fg);
  border:1px solid var(--border);border-radius:7px;padding:6px 9px;font:12.5px var(--sans);outline:none}
.sidesearch:focus{border-color:var(--accent)}
.sidelist{flex:1;overflow:auto;display:flex;flex-direction:column;gap:1px;padding:4px 8px}
.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--panel3);
  color:var(--fg);border:1px solid var(--border);padding:8px 14px;border-radius:8px;opacity:0;
  transition:opacity .2s;pointer-events:none;z-index:9999;font-size:13px}
.toast.show{opacity:1}"""

# Shared base JS helpers (single source): HTML-escape, markdown render, and the
# toast popup. Insert via the //__APP_JS__ token. toast() lazily creates the
# #toast node, so a page needn't include the markup. Requires marked.js loaded.
APP_JS = """// ---- shared base helpers (theme.APP_JS) ----
function esc(s){return (s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
if(window.marked) marked.setOptions({breaks:true, gfm:true});
function md(t){return window.marked?marked.parse(t||""):esc(t||"");}
function toast(m){let t=document.getElementById("toast");
  if(!t){t=document.createElement("div");t.id="toast";t.className="toast";document.body.appendChild(t);}
  t.textContent=m;t.classList.add("show");clearTimeout(toast._t);toast._t=setTimeout(()=>t.classList.remove("show"),3200);}"""

# Shared agent-transcript rendering — the collapsible thinking/tool/subagent
# blocks an agent emits, rendered identically wherever a chat/oversight stream is
# shown. Insert CHAT_CSS via /*__CHAT_CSS__*/ and TRANSCRIPT_JS via
# //__TRANSCRIPT_JS__. TRANSCRIPT_JS provides argSummary(name,args) and
# blockHtml(b) -> html for one block ({kind:text|thinking|tool|subagent}).
CHAT_CSS = """details.aux{margin:6px 0;border:1px solid var(--border);border-radius:8px;background:var(--panel2);font-size:12.5px}
details.aux>summary{cursor:pointer;padding:5px 11px;font-weight:600;list-style:none;display:flex;gap:8px;align-items:center;color:var(--muted)}
details.aux>summary::-webkit-details-marker{display:none}
details.aux>summary::before{content:"▸";color:var(--muted)}
details.aux[open]>summary::before{content:"▾"}
details.think>summary{color:var(--think)} details.tool>summary{color:var(--tool)} details.sub>summary{color:var(--accent)}
details.aux.err>summary{color:var(--err)}
details.aux .arg{color:var(--faint);font-family:var(--mono);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
details.aux .body2{padding:0 11px 9px;white-space:pre-wrap;font-family:var(--mono);font-size:11.5px;color:var(--muted);max-height:320px;overflow:auto}
details.think .body2{color:#c8bfe7;font-style:italic}
.tdot{display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--muted);margin-right:3px;animation:tb 1.2s infinite}
.tdot:nth-child(2){animation-delay:.15s}.tdot:nth-child(3){animation-delay:.3s}
@keyframes tb{0%,60%,100%{opacity:.25}30%{opacity:1}}"""

TRANSCRIPT_JS = """// ---- shared agent-transcript block rendering (theme.TRANSCRIPT_JS) ----
// Requires esc() and md() (theme.APP_JS). One assistant block -> html.
function argSummary(name,args){
  if(args==null) return "";
  if(typeof args!=="object") return String(args).slice(0,160);
  const a=args, pick=a.path||a.file_path||a.file||a.filename;
  if(name==="bash"||name==="shell") return (a.command||a.cmd||"").slice(0,160);
  if(pick) return String(pick);
  try{return JSON.stringify(a).slice(0,160);}catch(e){return "";}
}
function blockHtml(b){
  if(b.kind==="text") return `<div class="md">${md(b.text)}</div>`;
  if(b.kind==="thinking")
    return `<details class="aux think"><summary>thinking</summary><div class="body2">${esc(b.text)}</div></details>`;
  if(b.kind==="subagent")
    return `<details class="aux sub"><summary>subagent: ${esc(b.agent)}<span class="arg">${esc((b.task||"").slice(0,80))}</span></summary>`
      +`<div class="body2">${esc((b.result&&b.result.text)||"")}</div></details>`;
  if(b.kind==="tool"){
    const err=b.result&&b.result.isError?" err":"";
    const res=b.result?esc(b.result.text||""):"(running…)";
    return `<details class="aux tool${err}"><summary>${esc(b.name||"tool")}<span class="arg">${esc(argSummary(b.name,b.args))}</span></summary>`
      +`<div class="body2">${res}</div></details>`;
  }
  return "";
}"""

# Thin top progress bar (the run viewer's), shared so every page pulses the
# same way during user-initiated fetches. Pages add <div id="topbar-progress">,
# the CSS/JS tokens, and call Progress.start()/done() around fetches.
PROGRESS_CSS = """#topbar-progress{position:fixed;top:0;left:0;height:3px;width:0;z-index:9999;
  background:linear-gradient(90deg,var(--accent),var(--accent2));
  box-shadow:0 0 10px var(--accent),0 0 4px var(--accent);border-radius:0 2px 2px 0;
  opacity:0;transition:width .2s ease,opacity .35s ease;pointer-events:none}
#topbar-progress.active{opacity:1}"""

PROGRESS_JS = """// ---- thin top progress bar (shared with the run viewer) ----
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
})();"""

# Draggable column resizers (same look/feel as the run viewer's): a 6px flex
# handle between columns. Pages insert via the /*__RESIZER_CSS__*/ and
# //__RESIZER_JS__ tokens, then call makeResizer per handle.
RESIZER_CSS = """.vresizer{flex:0 0 6px;cursor:col-resize;background:var(--border);transition:background .12s}
.vresizer:hover,.vresizer.active{background:var(--accent)}"""

RESIZER_JS = """// ---- draggable column resizer (shared) ----
// makeResizer(handle, target, storageKey, {min, max, fromRight}): drag the
// handle to resize target's width, persisted in localStorage per page.
// fromRight = the target is docked on the right of the handle.
function makeResizer(handle, target, key, opts){
  const o=Object.assign({min:220,max:720,fromRight:false},opts||{});
  const saved=parseInt(localStorage.getItem(key)||"",10);
  if(saved>=o.min&&saved<=o.max) target.style.width=saved+"px";
  let drag=false;
  handle.addEventListener("mousedown",e=>{drag=true;handle.classList.add("active");
    document.body.style.userSelect="none";e.preventDefault();});
  window.addEventListener("mousemove",e=>{
    if(!drag)return;
    const r=target.getBoundingClientRect();
    const w=Math.min(o.max,Math.max(o.min,o.fromRight?r.right-e.clientX:e.clientX-r.left));
    target.style.width=w+"px";
  });
  window.addEventListener("mouseup",()=>{ if(!drag)return; drag=false; handle.classList.remove("active");
    document.body.style.userSelect="";
    localStorage.setItem(key,parseInt(target.style.width,10)||""); });
}"""

__all__ = [
    "PALETTE_CSS",
    "CONTROLS_CSS",
    "APP_JS",
    "CHAT_CSS",
    "TRANSCRIPT_JS",
    "EDITOR_CSS",
    "PREVIEW_CSS",
    "HIGHLIGHT_JS",
    "PROGRESS_CSS",
    "PROGRESS_JS",
    "RESIZER_CSS",
    "RESIZER_JS",
]
