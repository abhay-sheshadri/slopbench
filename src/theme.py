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

__all__ = ["PALETTE_CSS", "EDITOR_CSS", "PREVIEW_CSS", "HIGHLIGHT_JS"]
