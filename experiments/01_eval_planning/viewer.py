from __future__ import annotations

import argparse
import datetime
import json
import re
import socketserver
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
import sys as _sys

if str(ROOT) not in _sys.path:
    _sys.path.insert(0, str(ROOT))
from src.theme import PALETTE_CSS  # noqa: E402  (shared color theme)

DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "01_eval_planning"
DEFAULT_NOTES_DIR = ROOT / "outputs" / "01_eval_planning_notes"

PLANNER_FILES = (
    "OVERALL_PLAN.md",
    "INSTRUCTIONS_SEGMENT_0_PHASE_0.md",
    "RUBRIC_SEGMENT_0_PHASE_0.md",
    "INITIAL_INSTRUCTIONS.md",
)

TRANSCRIPT_FILES = (
    "init_planner.session.jsonl",
    "pi_events.jsonl",
    "pi.stderr.log",
    "manifest.json",
    "init_planner.html",
)

RUN_FILES = (
    "run_status.json",
    "run_metadata.json",
)

SAFE_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


def safe_part(value: str, label: str) -> str:
    if not value or not SAFE_PART.fullmatch(value):
        raise ValueError(f"bad {label}")
    return value


def read_json(path: Path) -> object | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def scores_file(notes_dir: Path) -> Path:
    return notes_dir / "scores.json"


def load_scores(notes_dir: Path) -> dict[str, object]:
    data = read_json(scores_file(notes_dir))
    return data if isinstance(data, dict) else {}


def save_scores(notes_dir: Path, scores: dict[str, object]) -> None:
    notes_dir.mkdir(parents=True, exist_ok=True)
    scores_file(notes_dir).write_text(json.dumps(scores, indent=2, sort_keys=True))


def key_from_query(query: dict[str, list[str]]) -> str:
    project = safe_part(query.get("project", [""])[0], "project")
    model = safe_part(query.get("model", [""])[0], "model")
    attempt = safe_part(query.get("attempt", [""])[0], "attempt")
    if not attempt.startswith("attempt_"):
        attempt = f"attempt_{int(attempt):02d}"
    return f"{project}/{model}/{attempt}"


def word_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(errors="replace").split())


def file_info(path: Path, name: str, count_words: bool = False) -> dict[str, object]:
    exists = path.exists()
    return {
        "name": name,
        "exists": exists,
        "bytes": path.stat().st_size if exists else 0,
        # Only count words for small planner markdown; transcripts can be tens of
        # MB each (gigabytes total), and reading them all here makes the index
        # build painfully slow.
        "words": word_count(path) if count_words and exists else 0,
    }


def build_index(output_dir: Path, notes_dir: Path) -> dict[str, object]:
    projects: list[dict[str, object]] = []
    scores = load_scores(notes_dir)
    if not output_dir.exists():
        return {
            "output_dir": str(output_dir),
            "notes_dir": str(notes_dir),
            "projects": [],
        }

    for project_dir in sorted(path for path in output_dir.iterdir() if path.is_dir()):
        models: list[dict[str, object]] = []
        for model_dir in sorted(
            path for path in project_dir.iterdir() if path.is_dir()
        ):
            attempts: list[dict[str, object]] = []
            for attempt_dir in sorted(
                path for path in model_dir.iterdir() if path.is_dir()
            ):
                planner_dir = attempt_dir / "planner"
                status = read_json(attempt_dir / "run_status.json") or {}
                files = [
                    file_info(planner_dir / name, name, count_words=True)
                    for name in PLANNER_FILES
                ]
                transcript_dir = attempt_dir / "pi_transcripts"
                transcripts = [
                    file_info(transcript_dir / name, name)
                    for name in TRANSCRIPT_FILES
                    if (transcript_dir / name).exists()
                ]
                run_files = [
                    file_info(attempt_dir / name, name)
                    for name in RUN_FILES
                    if (attempt_dir / name).exists()
                ]
                note_path = (
                    notes_dir
                    / project_dir.name
                    / model_dir.name
                    / f"{attempt_dir.name}.md"
                )
                key = f"{project_dir.name}/{model_dir.name}/{attempt_dir.name}"
                score_entry = scores.get(key)
                if not isinstance(score_entry, dict):
                    score_entry = {}
                attempts.append(
                    {
                        "name": attempt_dir.name,
                        "attempt": attempt_dir.name.removeprefix("attempt_"),
                        "status": status.get("status", "unknown"),
                        "complete": bool(status.get("planner_files_complete")),
                        "files": files,
                        "transcripts": transcripts,
                        "run_files": run_files,
                        "score": score_entry.get("score"),
                        "comment": score_entry.get("comment", ""),
                        "has_note": note_path.exists()
                        and bool(note_path.read_text().strip()),
                    }
                )
            models.append({"name": model_dir.name, "attempts": attempts})
        projects.append({"name": project_dir.name, "models": models})
    return {
        "output_dir": str(output_dir),
        "notes_dir": str(notes_dir),
        "projects": projects,
    }


def attempt_dir_from_query(output_dir: Path, query: dict[str, list[str]]) -> Path:
    project = safe_part(query.get("project", [""])[0], "project")
    model = safe_part(query.get("model", [""])[0], "model")
    attempt = safe_part(query.get("attempt", [""])[0], "attempt")
    if not attempt.startswith("attempt_"):
        attempt = f"attempt_{int(attempt):02d}"
    path = output_dir / project / model / attempt
    resolved = path.resolve()
    if output_dir.resolve() not in resolved.parents:
        raise ValueError("bad path")
    return resolved


def note_path_from_query(notes_dir: Path, query: dict[str, list[str]]) -> Path:
    project = safe_part(query.get("project", [""])[0], "project")
    model = safe_part(query.get("model", [""])[0], "model")
    attempt = safe_part(query.get("attempt", [""])[0], "attempt")
    if not attempt.startswith("attempt_"):
        attempt = f"attempt_{int(attempt):02d}"
    path = notes_dir / project / model / f"{attempt}.md"
    resolved = path.resolve()
    if notes_dir.resolve() != resolved and notes_dir.resolve() not in resolved.parents:
        raise ValueError("bad note path")
    return resolved


def artifact_path_from_query(output_dir: Path, query: dict[str, list[str]]) -> Path:
    attempt_dir = attempt_dir_from_query(output_dir, query)
    kind = safe_part(query.get("kind", [""])[0], "kind")
    file_name = safe_part(query.get("file", [""])[0], "file")
    if kind == "planner":
        if file_name not in PLANNER_FILES:
            raise ValueError("unknown planner file")
        path = attempt_dir / "planner" / file_name
    elif kind == "transcript":
        if file_name not in TRANSCRIPT_FILES:
            raise ValueError("unknown transcript file")
        path = attempt_dir / "pi_transcripts" / file_name
    elif kind == "run":
        if file_name not in RUN_FILES:
            raise ValueError("unknown run file")
        path = attempt_dir / file_name
    else:
        raise ValueError("unknown artifact kind")

    resolved = path.resolve()
    if output_dir.resolve() not in resolved.parents:
        raise ValueError("bad path")
    return resolved


def read_artifact_text(path: Path) -> str:
    text = path.read_text(errors="replace")
    if path.suffix == ".json":
        parsed = read_json(path)
        if parsed is not None:
            return json.dumps(parsed, indent=2, sort_keys=True)
    return text


def artifact_content_type(path: Path) -> str:
    if path.suffix == ".html":
        return "text/html; charset=utf-8"
    if path.suffix == ".json" or path.suffix == ".jsonl":
        return "application/json; charset=utf-8"
    return "text/plain; charset=utf-8"


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Experiment 01 Proposal Viewer</title>
  <style>
    /*__PALETTE__*/
    :root { --sidebar-w: 280px; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      height: 100vh;
      overflow: hidden;
    }
    header {
      height: 48px;
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 0 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    header h1 {
      font-size: 16px;
      margin: 0;
      font-weight: 650;
    }
    header .meta {
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }
    main {
      display: grid;
      grid-template-columns: var(--sidebar-w, 280px) 6px minmax(0, 1fr);
      height: calc(100vh - 48px);
      min-height: 0;
    }
    .resizer {
      cursor: col-resize;
      background: transparent;
      transition: background .12s ease;
    }
    .resizer:hover, .resizer.active { background: var(--accent); }
    aside, section {
      min-height: 0;
      overflow: auto;
      border-right: 1px solid var(--line);
      background: var(--panel);
    }
    .viewer {
      background: var(--bg);
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 0;
    }
    .toolbar {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      min-height: 48px;
    }
    .toolbar select, .toolbar input {
      height: 30px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel2);
      padding: 0 8px;
      color: var(--text);
    }
    .toolbar select { max-width: 100%; }
    .toolbar input { flex: 1; min-width: 140px; }
    .toolbar button {
      height: 30px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel2);
      cursor: pointer;
      padding: 0 9px;
    }
    .toolbar button.primary {
      border-color: var(--accent);
      color: white;
      background: var(--accent);
    }
    .toolbar button:disabled {
      color: var(--muted);
      background: var(--panel3);
      cursor: not-allowed;
    }
    #selectedLabel {
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 360px;
    }
    .content {
      padding: 18px 22px;
      overflow: auto;
      min-height: 0;
      flex: 1;
    }
    .doc {
      max-width: 920px;
      font-size: 14px;
      line-height: 1.55;
    }
    .doc h1, .doc h2, .doc h3, .doc h4 {
      margin: 18px 0 8px;
      line-height: 1.2;
    }
    .doc h1 { font-size: 24px; }
    .doc h2 { font-size: 19px; border-bottom: 1px solid var(--line); padding-bottom: 4px; }
    .doc h3 { font-size: 16px; }
    .doc h4 { font-size: 14px; }
    .doc p {
      margin: 6px 0;
    }
    .doc ul, .doc ol {
      margin: 6px 0 6px 22px;
      padding: 0;
    }
    .doc li {
      margin: 3px 0;
    }
    .doc code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 1px 4px;
    }
    .doc pre {
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.45;
      background: var(--code-bg);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      overflow: auto;
    }
    .doc .table-scroll {
      overflow-x: auto;
      margin: 12px 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
    }
    .doc table {
      width: 100%;
      min-width: 560px;
      border-collapse: collapse;
      font-size: 13px;
      line-height: 1.4;
    }
    .doc th, .doc td {
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      padding: 7px 9px;
      vertical-align: top;
      text-align: left;
    }
    .doc th:last-child, .doc td:last-child { border-right: 0; }
    .doc tbody tr:last-child td { border-bottom: 0; }
    .doc th {
      background: var(--panel3);
      font-weight: 650;
      color: var(--fg);
    }
    .doc tr:nth-child(even) td { background: var(--panel2); }
    .doc blockquote {
      margin: 10px 0;
      padding: 4px 0 4px 12px;
      border-left: 3px solid var(--border);
      color: var(--muted);
      background: var(--panel2);
    }
    .doc blockquote p:first-child { margin-top: 0; }
    .doc blockquote p:last-child { margin-bottom: 0; }
    .doc hr {
      border: 0;
      border-top: 1px solid var(--line);
      margin: 16px 0;
    }
    .doc a {
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px solid var(--accent);
    }
    .doc a:hover { border-bottom-color: var(--accent); }
    .doc.plain pre {
      margin: 0;
      background: var(--panel);
    }
    .project {
      padding: 10px 10px 6px;
      border-bottom: 1px solid var(--line);
    }
    .sidebar-filter {
      padding: 10px;
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      background: var(--panel);
      z-index: 1;
    }
    .sidebar-filter input {
      width: 100%;
      height: 30px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 8px;
      background: var(--panel2);
      color: var(--text);
    }
    .project-title {
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .04em;
      margin-bottom: 6px;
    }
    .row {
      width: 100%;
      border: 0;
      border-radius: 6px;
      background: transparent;
      display: grid;
      grid-template-columns: 52px 1fr auto;
      align-items: center;
      gap: 8px;
      padding: 7px 8px;
      text-align: left;
      cursor: pointer;
      color: var(--text);
      font: inherit;
    }
    .row:hover { background: var(--panel2); }
    .row.active { background: var(--panel3); outline: 1px solid var(--accent); }
    .model {
      font-size: 12px;
      font-weight: 700;
      color: var(--accent);
      text-transform: uppercase;
    }
    .attempt { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .badge {
      font-size: 11px;
      color: var(--muted);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 1px 6px;
    }
    .badge.note { color: var(--ok); border-color: var(--ok); }
    .badge.fail { color: var(--bad); border-color: var(--err); }
    .badge.score {
      color: var(--accent);
      border-color: var(--accent);
      background: var(--panel3);
      font-weight: 700;
    }
    .badge.unscored {
      color: var(--warn);
      border-color: var(--warn);
      background: var(--panel3);
    }
    .score-progress {
      margin-top: 6px;
      font-size: 11px;
      color: var(--muted);
    }
    .score-box {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding-left: 10px;
      border-left: 1px solid var(--line);
    }
    .score-box label {
      font-size: 12px;
      color: var(--muted);
    }
    .score-box #scoreComment {
      flex: 0 1 180px;
      min-width: 120px;
    }
    .saved-flag {
      font-size: 12px;
      color: var(--ok);
      opacity: 0;
      transition: opacity .15s ease;
    }
    .saved-flag.show { opacity: 1; }
    .summary-row:hover td { background: var(--panel2); }
    #status {
      color: var(--muted);
      font-size: 12px;
    }
    #position {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .empty {
      color: var(--muted);
      padding: 20px;
    }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      background: rgba(0, 0, 0, 0.6);
      z-index: 10;
      padding: 28px;
    }
    .modal-backdrop.open {
      display: block;
    }
    .modal {
      height: 100%;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 20px 70px rgba(0, 0, 0, 0.5);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .modal-head {
      min-height: 44px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 0 12px;
      border-bottom: 1px solid var(--line);
    }
    .modal-title {
      font-size: 13px;
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .modal iframe {
      width: 100%;
      height: 100%;
      border: 0;
      background: var(--panel);
    }
    @media (max-width: 980px) {
      main {
        grid-template-columns: var(--sidebar-w, 240px) 6px minmax(0, 1fr);
      }
    }
    @media (max-width: 700px) {
      main {
        grid-template-columns: 1fr;
        grid-template-rows: 190px minmax(0, 1fr);
      }
      .resizer { display: none; }
      aside, .viewer {
        grid-column: 1;
      }
      .viewer {
        grid-row: 2;
      }
    }
  </style>
</head>
<body>
  <header>
    <h1>Experiment 01 Proposal Viewer</h1>
    <div class="meta" id="paths"></div>
  </header>
  <main>
    <aside>
      <div class="sidebar-filter">
        <input id="navFilter" placeholder="Filter proposals (try 'unscored')">
        <div id="scoreProgress" class="score-progress"></div>
      </div>
      <div id="list"></div>
    </aside>
    <div class="resizer" id="resizer" title="Drag to resize"></div>
    <div class="viewer">
      <div class="toolbar">
        <button id="prevBtn" title="Previous proposal">Prev</button>
        <button id="nextBtn" title="Next proposal">Next</button>
        <span id="position"></span>
        <button id="transcriptBtn" class="primary" title="Open planner transcript popup">Transcript</button>
        <span class="score-box">
          <label for="scoreSelect">Score</label>
          <select id="scoreSelect" title="Score this plan 0-10 (or press 0-9 on the keyboard)">
            <option value="">&mdash;</option>
            <option>0</option><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option><option>6</option><option>7</option><option>8</option><option>9</option><option>10</option>
          </select>
          <input id="scoreComment" placeholder="comment (optional)">
          <span id="scoreSaved" class="saved-flag"></span>
        </span>
        <button id="summaryBtn" title="View score summary by model">Scores</button>
        <select id="fileSelect"></select>
        <input id="filter" placeholder="Filter within file">
        <span id="selectedLabel"></span>
      </div>
      <div class="content"><div class="doc" id="proposal">Loading...</div></div>
    </div>
  </main>
  <div class="modal-backdrop" id="transcriptModal" role="dialog" aria-modal="true" aria-label="Planner transcript">
    <div class="modal">
      <div class="modal-head">
        <div class="modal-title" id="transcriptTitle">Planner transcript</div>
        <button id="closeTranscriptBtn">Close</button>
      </div>
      <iframe id="transcriptFrame" title="Planner transcript"></iframe>
    </div>
  </div>
  <div class="modal-backdrop" id="summaryModal" role="dialog" aria-modal="true" aria-label="Score summary">
    <div class="modal">
      <div class="modal-head">
        <div class="modal-title">Score summary</div>
        <span style="display:flex;gap:8px">
          <button id="exportScoresBtn">Download CSV</button>
          <button id="closeSummaryBtn">Close</button>
        </span>
      </div>
      <div class="content" id="summaryContent"></div>
    </div>
  </div>
<script>
let index = null;
let selected = null;
let rawText = "";
let selectedArtifact = null;

function qs(params) {
  return new URLSearchParams(params).toString();
}

function escapeText(value) {
  return value.replace(/[&<>]/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[ch]));
}

function escapeAttr(value) {
  return escapeText(value).replace(/"/g, "&quot;");
}

function setStatus(text) {
  console.debug(text);
}

function proposals() {
  const rows = [];
  if (!index) return rows;
  for (const project of index.projects) {
    for (const model of project.models) {
      for (const attempt of model.attempts) {
        rows.push({project: project.name, model: model.name, attempt: attempt.name});
      }
    }
  }
  return rows;
}

function selectedIndex() {
  return proposals().findIndex(item =>
    selected &&
    item.project === selected.project &&
    item.model === selected.model &&
    item.attempt === selected.attempt
  );
}

function selectOffset(delta) {
  const rows = proposals();
  if (!rows.length) return;
  const current = selectedIndex();
  const next = rows[(current + delta + rows.length) % rows.length];
  selectProposal(next.project, next.model, next.attempt);
}

function fileLabel(fileInfo) {
  if (!fileInfo.exists) return `${fileInfo.name} (missing)`;
  if (fileInfo.words) return `${fileInfo.name} (${fileInfo.words}w)`;
  return `${fileInfo.name} (${fileInfo.bytes}b)`;
}

function updateScoreProgress() {
  const progress = document.getElementById("scoreProgress");
  if (!progress || !index) return;
  let total = 0;
  let scored = 0;
  for (const project of index.projects) {
    for (const model of project.models) {
      for (const attempt of model.attempts) {
        total += 1;
        if (typeof attempt.score === "number") scored += 1;
      }
    }
  }
  if (!total) { progress.textContent = ""; return; }
  const remaining = total - scored;
  progress.textContent = remaining
    ? `${remaining} unscored \u00b7 ${scored}/${total} scored`
    : `All ${total} scored \u2713`;
}

function renderList() {
  const list = document.getElementById("list");
  list.innerHTML = "";
  updateScoreProgress();
  if (!index.projects.length) {
    list.innerHTML = '<div class="empty">No outputs found.</div>';
    return;
  }
  const filter = document.getElementById("navFilter").value.trim().toLowerCase();
  for (const project of index.projects) {
    const block = document.createElement("div");
    block.className = "project";
    let rowsAdded = 0;
    const title = document.createElement("div");
    title.className = "project-title";
    title.textContent = project.name;
    block.appendChild(title);
    for (const model of project.models) {
      for (const attempt of model.attempts) {
        const scoredText = typeof attempt.score === "number" ? `scored ${attempt.score}` : "unscored";
        const searchable = `${project.name} ${model.name} ${attempt.name} ${attempt.status} ${scoredText}`.toLowerCase();
        if (filter && !searchable.includes(filter)) continue;
        const button = document.createElement("button");
        button.className = "row";
        button.dataset.key = [project.name, model.name, attempt.name].join("/");
        button.innerHTML = `
          <span class="model">${escapeText(model.name)}</span>
          <span class="attempt">${escapeText(attempt.name)}</span>
          <span>
            ${typeof attempt.score === "number" ? `<span class="badge score">${attempt.score}</span>` : '<span class="badge unscored">unscored</span>'}
            ${attempt.has_note ? '<span class="badge note">note</span>' : ''}
            ${attempt.status !== "ok" ? '<span class="badge fail">fail</span>' : '<span class="badge">Success</span>'}
          </span>`;
        button.onclick = () => selectProposal(project.name, model.name, attempt.name);
        block.appendChild(button);
        rowsAdded += 1;
      }
    }
    if (rowsAdded) list.appendChild(block);
  }
  if (!list.children.length) {
    list.innerHTML = '<div class="empty">No matching proposals.</div>';
  }
}

function markActive() {
  document.querySelectorAll(".row").forEach(row => {
    row.classList.toggle("active", selected && row.dataset.key === [selected.project, selected.model, selected.attempt].join("/"));
  });
  const rows = proposals();
  const current = selectedIndex();
  document.getElementById("position").textContent = current >= 0 ? `${current + 1}/${rows.length}` : "";
}

function selectedAttempt() {
  const project = index.projects.find(p => p.name === selected.project);
  const model = project.models.find(m => m.name === selected.model);
  return model.attempts.find(a => a.name === selected.attempt);
}

function transcriptHtmlFile(attempt) {
  return (attempt.transcripts || []).find(info => info.name.endsWith(".html") && info.exists);
}

function renderFileOptions() {
  const select = document.getElementById("fileSelect");
  select.innerHTML = "";
  const attempt = selectedAttempt();

  function addGroup(label, kind, files) {
    if (!files.length) return;
    const group = document.createElement("optgroup");
    group.label = label;
    for (const info of files) {
      const option = document.createElement("option");
      option.value = `${kind}:${info.name}`;
      option.textContent = fileLabel(info);
      option.disabled = !info.exists;
      group.appendChild(option);
    }
    select.appendChild(group);
  }

  addGroup("Planner files", "planner", attempt.files);
  addGroup("Agent transcript", "transcript", attempt.transcripts || []);
  addGroup("Run metadata", "run", attempt.run_files || []);

  const firstExisting = attempt.files.find(f => f.exists);
  if (firstExisting) {
    select.value = `planner:${firstExisting.name}`;
  } else if (select.options.length) {
    select.selectedIndex = 0;
  }
  const [kind, file] = select.value.split(/:(.*)/s);
  selectedArtifact = {kind, file};
}

async function selectProposal(project, model, attempt) {
  selected = {project, model, attempt};
  markActive();
  renderFileOptions();
  document.getElementById("selectedLabel").textContent = `${project} / ${model} / ${attempt}`;
  syncScoreControls();
  const transcript = transcriptHtmlFile(selectedAttempt());
  const transcriptBtn = document.getElementById("transcriptBtn");
  transcriptBtn.disabled = !transcript;
  transcriptBtn.title = transcript ? "Open planner transcript popup" : "No exported HTML transcript for this attempt";
  await loadProposal();
}

async function loadProposal() {
  if (!selected) return;
  const value = document.getElementById("fileSelect").value;
  const [kind, file] = value.split(/:(.*)/s);
  selectedArtifact = {kind, file};
  const response = await fetch("/api/artifact?" + qs({...selected, kind, file}));
  if (!response.ok) {
    rawText = `Error loading ${file}: ${response.status}`;
  } else {
    const data = await response.json();
    rawText = data.text || "";
  }
  renderProposal();
}

function renderProposal() {
  const filter = document.getElementById("filter").value.trim().toLowerCase();
  let text = rawText;
  if (filter) {
    text = filterMarkdownText(rawText, filter);
  }
  const proposal = document.getElementById("proposal");
  const isPlain = selectedArtifact && selectedArtifact.kind !== "planner";
  proposal.classList.toggle("plain", isPlain);
  proposal.innerHTML = isPlain ? `<pre>${escapeText(text || "(empty)")}</pre>` : renderMarkdown(text || "(empty)");
}

function filterMarkdownText(text, filter) {
  const lines = text.split("\n");
  const kept = [];
  for (let i = 0; i < lines.length; i += 1) {
    if (isTableStart(lines, i)) {
      const block = [lines[i], lines[i + 1]];
      let next = i + 2;
      while (next < lines.length && lines[next].trim() && lines[next].includes("|")) {
        block.push(lines[next]);
        next += 1;
      }
      if (block.join("\n").toLowerCase().includes(filter)) {
        if (kept.length && kept[kept.length - 1] !== "") kept.push("");
        kept.push(...block, "");
      }
      i = next - 1;
      continue;
    }
    if (lines[i].toLowerCase().includes(filter)) {
      kept.push(lines[i]);
    }
  }
  return kept.join("\n");
}

function inlineMarkdown(value) {
  return escapeText(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (_match, label, url) => {
      return `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    });
}

function splitTableRow(line) {
  let value = line.trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|") && !value.endsWith("\\|")) value = value.slice(0, -1);

  const cells = [];
  let cell = "";
  let escaped = false;
  for (const ch of value) {
    if (escaped) {
      cell += ch;
      escaped = false;
      continue;
    }
    if (ch === "\\") {
      escaped = true;
      continue;
    }
    if (ch === "|") {
      cells.push(cell.trim());
      cell = "";
      continue;
    }
    cell += ch;
  }
  cells.push(cell.trim());
  return cells;
}

function parseTableSeparator(line) {
  if (!line.includes("|")) return null;
  const cells = splitTableRow(line);
  if (!cells.length) return null;
  const aligns = [];
  for (const cell of cells) {
    const compact = cell.replace(/\s+/g, "");
    if (!/^:?-{3,}:?$/.test(compact)) return null;
    if (compact.startsWith(":") && compact.endsWith(":")) aligns.push("center");
    else if (compact.endsWith(":")) aligns.push("right");
    else aligns.push("left");
  }
  return aligns;
}

function isTableStart(lines, index) {
  if (index + 1 >= lines.length) return false;
  if (!lines[index].includes("|")) return false;
  return Boolean(parseTableSeparator(lines[index + 1]));
}

function renderTable(lines, index) {
  const headers = splitTableRow(lines[index]);
  const aligns = parseTableSeparator(lines[index + 1]) || headers.map(() => "left");
  const rows = [];
  let next = index + 2;
  while (next < lines.length && lines[next].trim() && lines[next].includes("|")) {
    rows.push(splitTableRow(lines[next]));
    next += 1;
  }

  const columnCount = Math.max(headers.length, aligns.length, ...rows.map(row => row.length));
  const cellStyle = col => aligns[col] && aligns[col] !== "left" ? ` style="text-align: ${aligns[col]}"` : "";
  const normalize = row => Array.from({length: columnCount}, (_unused, col) => row[col] || "");

  let html = '<div class="table-scroll"><table><thead><tr>';
  for (const [col, cell] of normalize(headers).entries()) {
    html += `<th${cellStyle(col)}>${inlineMarkdown(cell)}</th>`;
  }
  html += "</tr></thead><tbody>";
  for (const row of rows) {
    html += "<tr>";
    for (const [col, cell] of normalize(row).entries()) {
      html += `<td${cellStyle(col)}>${inlineMarkdown(cell)}</td>`;
    }
    html += "</tr>";
  }
  html += "</tbody></table></div>";
  return {html, next};
}

function renderMarkdown(text) {
  const lines = text.split("\n");
  let html = "";
  let inCode = false;
  let code = "";
  let listType = null;
  let inBlockquote = false;

  function closeList() {
    if (listType) {
      html += `</${listType}>`;
      listType = null;
    }
  }

  function closeBlockquote() {
    if (inBlockquote) {
      html += "</blockquote>";
      inBlockquote = false;
    }
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      closeList();
      closeBlockquote();
      if (inCode) {
        html += `<pre>${escapeText(code.replace(/\n$/, ""))}</pre>`;
        code = "";
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      code += line + "\n";
      continue;
    }

    if (isTableStart(lines, i)) {
      closeList();
      closeBlockquote();
      const table = renderTable(lines, i);
      html += table.html;
      i = table.next - 1;
      continue;
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      closeList();
      closeBlockquote();
      const level = heading[1].length;
      html += `<h${level}>${inlineMarkdown(heading[2])}</h${level}>`;
      continue;
    }

    if (!line.trim()) {
      closeList();
      closeBlockquote();
      html += "<p></p>";
      continue;
    }

    if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
      closeList();
      closeBlockquote();
      html += "<hr>";
      continue;
    }

    const quote = /^>\s?(.*)$/.exec(line);
    if (quote) {
      closeList();
      if (!inBlockquote) {
        html += "<blockquote>";
        inBlockquote = true;
      }
      html += `<p>${inlineMarkdown(quote[1])}</p>`;
      continue;
    }
    closeBlockquote();

    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      if (listType !== "ul") {
        closeList();
        html += "<ul>";
        listType = "ul";
      }
      html += `<li>${inlineMarkdown(bullet[1])}</li>`;
      continue;
    }

    const numbered = /^\s*\d+\.\s+(.*)$/.exec(line);
    if (numbered) {
      if (listType !== "ol") {
        closeList();
        html += "<ol>";
        listType = "ol";
      }
      html += `<li>${inlineMarkdown(numbered[1])}</li>`;
      continue;
    }

    closeList();
    html += `<p>${inlineMarkdown(line)}</p>`;
  }
  closeList();
  closeBlockquote();
  if (inCode) {
    html += `<pre>${escapeText(code.replace(/\n$/, ""))}</pre>`;
  }
  return html;
}

function openTranscript() {
  if (!selected) return;
  const transcript = transcriptHtmlFile(selectedAttempt());
  if (!transcript) return;
  const modal = document.getElementById("transcriptModal");
  document.getElementById("transcriptTitle").textContent = `${selected.project} / ${selected.model} / ${selected.attempt} / ${transcript.name}`;
  document.getElementById("transcriptFrame").src = "/artifact?" + qs({...selected, kind: "transcript", file: transcript.name});
  modal.classList.add("open");
}

function closeTranscript() {
  const modal = document.getElementById("transcriptModal");
  modal.classList.remove("open");
  document.getElementById("transcriptFrame").src = "about:blank";
}

function syncScoreControls() {
  if (!selected) return;
  const attempt = selectedAttempt();
  document.getElementById("scoreSelect").value = (typeof attempt.score === "number") ? String(attempt.score) : "";
  document.getElementById("scoreComment").value = attempt.comment || "";
  document.getElementById("scoreSaved").classList.remove("show");
}

let scoreSavedTimer = null;
async function saveScore() {
  if (!selected) return;
  const scoreVal = document.getElementById("scoreSelect").value;
  const comment = document.getElementById("scoreComment").value;
  const payload = {score: scoreVal === "" ? null : Number(scoreVal), comment};
  const response = await fetch("/api/score?" + qs(selected), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!response.ok) return;
  const attempt = selectedAttempt();
  attempt.score = payload.score;
  attempt.comment = comment;
  const flag = document.getElementById("scoreSaved");
  flag.textContent = "Saved \u2713";
  flag.classList.add("show");
  clearTimeout(scoreSavedTimer);
  scoreSavedTimer = setTimeout(() => flag.classList.remove("show"), 1200);
  renderList();
  markActive();
}

function isModalOpen() {
  return Boolean(document.querySelector(".modal-backdrop.open"));
}

function collectRows() {
  const rows = [];
  if (!index) return rows;
  for (const project of index.projects) {
    for (const model of project.models) {
      for (const attempt of model.attempts) {
        rows.push({
          project: project.name,
          model: model.name,
          attempt: attempt.name,
          score: (typeof attempt.score === "number") ? attempt.score : null,
          comment: attempt.comment || "",
          status: attempt.status,
        });
      }
    }
  }
  return rows;
}

function average(values) {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function openSummary() {
  const rows = collectRows();
  const byModel = {};
  for (const row of rows) {
    const bucket = byModel[row.model] || (byModel[row.model] = {total: 0, scores: []});
    bucket.total += 1;
    if (row.score !== null) bucket.scores.push(row.score);
  }

  let html = '<div class="doc">';
  html += "<h2>Average score by model</h2>";
  html += '<div class="table-scroll"><table><thead><tr><th>Model</th><th>Scored</th>'
    + '<th style="text-align:right">Avg</th><th style="text-align:right">Min</th>'
    + '<th style="text-align:right">Max</th></tr></thead><tbody>';
  for (const name of Object.keys(byModel).sort()) {
    const bucket = byModel[name];
    const avg = average(bucket.scores);
    const min = bucket.scores.length ? Math.min(...bucket.scores) : null;
    const max = bucket.scores.length ? Math.max(...bucket.scores) : null;
    html += `<tr><td>${escapeText(name)}</td><td>${bucket.scores.length}/${bucket.total}</td>`
      + `<td style="text-align:right"><strong>${avg === null ? "\u2014" : avg.toFixed(2)}</strong></td>`
      + `<td style="text-align:right">${min === null ? "\u2014" : min}</td>`
      + `<td style="text-align:right">${max === null ? "\u2014" : max}</td></tr>`;
  }
  html += "</tbody></table></div>";

  html += "<h2>All plans</h2>";
  html += '<p style="color:var(--muted);font-size:12px">Click a row to open that plan.</p>';
  html += '<div class="table-scroll"><table><thead><tr><th>Project</th><th>Model</th><th>Attempt</th>'
    + '<th style="text-align:right">Score</th><th>Comment</th></tr></thead><tbody>';
  const sorted = rows.slice().sort((a, b) =>
    a.project.localeCompare(b.project) || a.model.localeCompare(b.model) || a.attempt.localeCompare(b.attempt));
  for (const row of sorted) {
    const key = [row.project, row.model, row.attempt].join("/");
    html += `<tr class="summary-row" data-key="${escapeAttr(key)}" style="cursor:pointer">`
      + `<td>${escapeText(row.project)}</td><td>${escapeText(row.model)}</td><td>${escapeText(row.attempt)}</td>`
      + `<td style="text-align:right">${row.score === null ? "\u2014" : `<strong>${row.score}</strong>`}</td>`
      + `<td>${escapeText(row.comment)}</td></tr>`;
  }
  html += "</tbody></table></div></div>";

  const content = document.getElementById("summaryContent");
  content.innerHTML = html;
  content.querySelectorAll(".summary-row").forEach(tr => {
    tr.onclick = () => {
      const [project, model, attempt] = tr.dataset.key.split("/");
      closeSummary();
      selectProposal(project, model, attempt);
    };
  });
  document.getElementById("summaryModal").classList.add("open");
}

function closeSummary() {
  document.getElementById("summaryModal").classList.remove("open");
}

function csvCell(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}

function downloadScoresCsv() {
  const rows = collectRows();
  const header = ["project", "model", "attempt", "score", "status", "comment"];
  const lines = [header.join(",")];
  for (const row of rows) {
    lines.push([row.project, row.model, row.attempt, row.score === null ? "" : row.score, row.status, row.comment].map(csvCell).join(","));
  }
  const blob = new Blob([lines.join("\n")], {type: "text/csv"});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "plan_scores.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

async function refreshIndex(chooseFirst) {
  const response = await fetch("/api/index");
  index = await response.json();
  document.getElementById("paths").textContent = `outputs: ${index.output_dir} | notes: ${index.notes_dir}`;
  renderList();
  if (chooseFirst && index.projects.length) {
    const p = index.projects[0];
    const m = p.models[0];
    const a = m.attempts[0];
    await selectProposal(p.name, m.name, a.name);
  } else {
    markActive();
  }
}

document.getElementById("fileSelect").onchange = loadProposal;
document.getElementById("filter").oninput = renderProposal;
document.getElementById("navFilter").oninput = () => { renderList(); markActive(); };
document.getElementById("prevBtn").onclick = () => selectOffset(-1);
document.getElementById("nextBtn").onclick = () => selectOffset(1);
document.getElementById("transcriptBtn").onclick = openTranscript;
document.getElementById("closeTranscriptBtn").onclick = closeTranscript;
document.getElementById("scoreSelect").onchange = saveScore;
document.getElementById("scoreComment").onchange = saveScore;
document.getElementById("scoreComment").onkeydown = event => { if (event.key === "Enter") event.target.blur(); };
document.getElementById("summaryBtn").onclick = openSummary;
document.getElementById("closeSummaryBtn").onclick = closeSummary;
document.getElementById("exportScoresBtn").onclick = downloadScoresCsv;
document.getElementById("transcriptModal").onclick = event => {
  if (event.target.id === "transcriptModal") closeTranscript();
};
document.getElementById("summaryModal").onclick = event => {
  if (event.target.id === "summaryModal") closeSummary();
};
document.addEventListener("keydown", event => {
  if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT") return;
  if (event.key === "Escape") { closeTranscript(); closeSummary(); }
  if (event.key === "ArrowLeft") selectOffset(-1);
  if (event.key === "ArrowRight") selectOffset(1);
  if (/^[0-9]$/.test(event.key) && selected && !isModalOpen()) {
    document.getElementById("scoreSelect").value = event.key;
    saveScore();
  }
});

function setSidebarWidth(px) {
  const clamped = Math.max(180, Math.min(640, Math.round(px)));
  document.documentElement.style.setProperty("--sidebar-w", clamped + "px");
}

function getSidebarWidth() {
  return parseInt(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-w")) || 280;
}

function initResizer() {
  const resizer = document.getElementById("resizer");
  const main = document.querySelector("main");
  const saved = Number(localStorage.getItem("viewerSidebarWidth"));
  if (saved) setSidebarWidth(saved);
  let dragging = false;
  resizer.addEventListener("mousedown", event => {
    dragging = true;
    resizer.classList.add("active");
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    event.preventDefault();
  });
  window.addEventListener("mousemove", event => {
    if (!dragging) return;
    setSidebarWidth(event.clientX - main.getBoundingClientRect().left);
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    resizer.classList.remove("active");
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
    localStorage.setItem("viewerSidebarWidth", String(getSidebarWidth()));
  });
}

initResizer();
refreshIndex(true);
</script>
</body>
</html>
"""

HTML = HTML.replace("/*__PALETTE__*/", PALETTE_CSS)


class ViewerHandler(BaseHTTPRequestHandler):
    output_dir: Path
    notes_dir: Path

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def write_bytes(
        self,
        body: bytes,
        status: HTTPStatus = HTTPStatus.OK,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.write_bytes(
            json.dumps(data, indent=2).encode(),
            status,
            "application/json; charset=utf-8",
        )

    def write_error(self, status: HTTPStatus, message: str) -> None:
        self.write_json({"error": message}, status)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                self.write_bytes(HTML.encode(), content_type="text/html; charset=utf-8")
            elif parsed.path == "/favicon.ico":
                self.write_bytes(b"", HTTPStatus.NO_CONTENT, "image/x-icon")
            elif parsed.path == "/api/index":
                self.write_json(build_index(self.output_dir, self.notes_dir))
            elif parsed.path == "/api/scores":
                self.write_json(load_scores(self.notes_dir))
            elif parsed.path == "/api/artifact":
                path = artifact_path_from_query(self.output_dir, query)
                if not path.exists():
                    self.write_error(HTTPStatus.NOT_FOUND, "file not found")
                    return
                self.write_json({"path": str(path), "text": read_artifact_text(path)})
            elif parsed.path == "/artifact":
                path = artifact_path_from_query(self.output_dir, query)
                if not path.exists():
                    self.write_error(HTTPStatus.NOT_FOUND, "file not found")
                    return
                self.write_bytes(
                    path.read_bytes(), content_type=artifact_content_type(path)
                )
            elif parsed.path == "/api/proposal":
                attempt_dir = attempt_dir_from_query(self.output_dir, query)
                file_name = safe_part(query.get("file", [""])[0], "file")
                if file_name not in PLANNER_FILES:
                    raise ValueError("unknown planner file")
                path = attempt_dir / "planner" / file_name
                if not path.exists():
                    self.write_error(HTTPStatus.NOT_FOUND, "file not found")
                    return
                self.write_json(
                    {"path": str(path), "text": path.read_text(errors="replace")}
                )
            elif parsed.path == "/api/notes":
                path = note_path_from_query(self.notes_dir, query)
                self.write_json(
                    {
                        "path": str(path),
                        "exists": path.exists(),
                        "text": path.read_text() if path.exists() else "",
                    }
                )
            else:
                self.write_error(HTTPStatus.NOT_FOUND, f"not found: {parsed.path}")
        except Exception as exc:
            self.write_error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            if parsed.path == "/api/score":
                key = key_from_query(query)
                raw_score = data.get("score", None)
                if raw_score is None or raw_score == "":
                    score = None
                else:
                    score = int(raw_score)
                    if not 0 <= score <= 10:
                        raise ValueError("score must be between 0 and 10")
                comment = str(data.get("comment", ""))
                scores = load_scores(self.notes_dir)
                if score is None and not comment.strip():
                    scores.pop(key, None)
                else:
                    scores[key] = {
                        "score": score,
                        "comment": comment,
                        "updated": datetime.datetime.now().isoformat(
                            timespec="seconds"
                        ),
                    }
                save_scores(self.notes_dir, scores)
                self.write_json({"ok": True, "key": key, "score": score})
                return
            if parsed.path == "/api/notes":
                text = str(data.get("text", ""))
                path = note_path_from_query(self.notes_dir, query)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                self.write_json({"ok": True, "path": str(path)})
                return
            self.write_error(HTTPStatus.NOT_FOUND, "not found")
        except Exception as exc:
            self.write_error(HTTPStatus.BAD_REQUEST, str(exc))


def serve(
    output_dir: Path, notes_dir: Path, host: str, port: int, open_browser: bool
) -> None:
    notes_dir.mkdir(parents=True, exist_ok=True)

    class Handler(ViewerHandler):
        pass

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    Handler.output_dir = output_dir
    Handler.notes_dir = notes_dir

    candidate_ports = [port] if port == 0 else list(range(port, port + 10))
    last_error: OSError | None = None
    for candidate_port in candidate_ports:
        try:
            with ReusableTCPServer((host, candidate_port), Handler) as httpd:
                actual_port = httpd.server_address[1]
                url = f"http://{host}:{actual_port}/"
                print(f"Proposal viewer: {url}", flush=True)
                print(f"Outputs: {output_dir}", flush=True)
                print(f"Notes:   {notes_dir}", flush=True)
                if open_browser:
                    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
                httpd.serve_forever()
                return
        except OSError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local viewer for experiment 01 planning proposals."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--notes-dir", type=Path, default=DEFAULT_NOTES_DIR)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to bind. Default 0 = a random free port chosen at startup.",
    )
    parser.add_argument(
        "--no-open", action="store_true", help="Do not open a browser automatically."
    )
    args = parser.parse_args()

    serve(
        output_dir=args.output_dir.resolve(),
        notes_dir=args.notes_dir.resolve(),
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
    )


if __name__ == "__main__":
    main()
