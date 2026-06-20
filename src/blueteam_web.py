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
  - **Run all** queues streamable per-run audits over every completed run;
  - **Delete** / **Delete all** remove saved audits.

No server of its own: :func:`handle` is called by the viewer's request handler.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs

from src import agent_viewer as av
from src import web_common
from src.theme import (
    API_JS,
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
ERROR = "blue_team_error.txt"
STDERR_OUT = "blue_team_stderr.log"
LAST_GOOD_REPORT = "last_good_blue_team_report.md"
LAST_GOOD_SESSION = "last_good_blue_team_agent_session.jsonl"
LEVELS = ["critical", "high", "medium", "low"]
# Run all = enqueue the SAME streamable per-run jobs (not a separate run_all.sh),
# so every audit in a batch streams + persists + re-attaches like a single one.
BATCH_CAP = max(1, int(os.environ.get("BLUE_TEAM_BATCH_CONCURRENCY", "5")))
RECOVER_ORPHANS = os.environ.get("BLUE_TEAM_RECOVER_ORPHANS") == "1"
FAILURE_QUIET_SECONDS = max(
    30, int(os.environ.get("BLUE_TEAM_FAILURE_QUIET_SECONDS", "180"))
)
STARTUP_RETRIES = max(0, int(os.environ.get("BLUE_TEAM_STARTUP_RETRIES", "2")))
MAX_FIRST_PASS_TURNS = max(
    4, int(os.environ.get("BLUE_TEAM_MAX_FIRST_PASS_TURNS", "14"))
)

_LOCK = threading.Lock()
_JOBS: dict[str, str] = {}  # every live audit (single or batch): job -> run rel
_PERSISTED: set[str] = set()
_PERSIST_TRIES: dict[str, int] = (
    {}
)  # job -> persist attempts (session file can lag exit)
_STARTUP_RETRIES: dict[str, int] = {}  # rel -> killed-before-session retries
_RECOVERED_LENS: set[str] = set()


def _name(rel: str) -> str:
    return (rel or "").rstrip("/").split("/")[-1]


def _saved_dir(rel: str) -> Path:
    return BT_DIR / _name(rel)


# --------------------------------------------------------------------------- #
# Parsing saved reports / transcripts into concern-labelled findings
# --------------------------------------------------------------------------- #
def _findings_from_text(text: str):
    for b in reversed(re.findall(r"```json[ \t]*\n([\s\S]*?)```", text or "")):
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
        e = _saved_dir(rel) / ERROR
        if not e.exists():
            return None
        msg = e.read_text(errors="replace").strip()
        return {
            "error": True,
            "message": msg[:240],
            "mtime": e.stat().st_mtime,
        }
    f = _findings_from_text(p.read_text(errors="replace")) or []
    return {"count": len(f), "worst": _worst(f), "mtime": p.stat().st_mtime}


def saved_full(rel: str) -> dict:
    p = _saved_dir(rel) / REPORT
    if not p.exists():
        e = _saved_dir(rel) / ERROR
        if not e.exists():
            return {"exists": False}
        return {
            "exists": True,
            "error": e.read_text(errors="replace").strip(),
            "findings": [],
            "mtime": e.stat().st_mtime,
        }
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
        if "```json" in ttext and _findings_from_text(ttext) is not None:
            return ttext
    return "\n".join(_turn_text(t) for t in turns)


def _failure_detail(info: dict, data: dict) -> str:
    if data.get("error"):
        return str(data["error"]).strip()
    proc = info.get("proc")
    rc = getattr(proc, "returncode", None)
    stderr_path = info.get("stderr")
    if stderr_path:
        try:
            detail = Path(stderr_path).read_text(errors="replace").strip()
            if detail:
                return detail[-4000:]
        except OSError:
            pass
    if rc not in (0, None):
        return f"blue-team agent exited before producing findings (rc={rc})"
    return "blue-team agent exited before producing a parseable findings block"


def _backup_success(rel: str) -> None:
    out = _saved_dir(rel)
    report = out / REPORT
    session = out / SESSION_OUT
    if report.exists():
        shutil.copyfile(report, out / LAST_GOOD_REPORT)
    if session.exists():
        shutil.copyfile(session, out / LAST_GOOD_SESSION)


def _restore_success_backup(rel: str) -> bool:
    out = _saved_dir(rel)
    backup = out / LAST_GOOD_REPORT
    if not backup.exists():
        return False
    shutil.copyfile(backup, out / REPORT)
    bsession = out / LAST_GOOD_SESSION
    if bsession.exists():
        shutil.copyfile(bsession, out / SESSION_OUT)
    return True


def _save_failure(job: str, rel: str, info: dict, detail: str) -> None:
    out = _saved_dir(rel)
    out.mkdir(parents=True, exist_ok=True)
    if not (out / REPORT).exists() and _restore_success_backup(rel):
        failed_session = out / f"failed_{job}_session.jsonl"
    else:
        failed_session = (
            out / f"failed_{job}_session.jsonl"
            if (out / REPORT).exists()
            else out / SESSION_OUT
        )
    (out / ERROR).write_text((detail or "blue-team audit failed").strip() + "\n")
    # If this was a failed re-run, keep the last successful report/session visible
    # and auditable. A failed fresh run (no REPORT yet) still gets its partial
    # session so the user can inspect what happened.
    sess = info.get("session")
    if sess and Path(sess).exists():
        shutil.copyfile(sess, failed_session)
    stderr_path = info.get("stderr")
    if stderr_path and Path(stderr_path).exists():
        shutil.copyfile(stderr_path, out / STDERR_OUT)


def _finish_job(job: str, rel: str | None = None) -> None:
    _PERSISTED.add(job)
    _PERSIST_TRIES.pop(job, None)
    with av._LENS_LOCK:
        av._LENS_JOBS.pop(job, None)
    if rel:
        _BATCH.discard(rel)
    with _LOCK:
        _JOBS.pop(job, None)


def _session_recently_changed(info: dict) -> bool:
    session = info.get("session")
    if not session:
        return False
    try:
        return time.time() - Path(session).stat().st_mtime < FAILURE_QUIET_SECONDS
    except OSError:
        return False


def _assistant_turns(info: dict) -> list[dict]:
    session = info.get("session")
    if not session or not Path(session).exists():
        return []
    try:
        parsed = av.parse_session(Path(session).read_text(errors="replace"))
    except OSError:
        return []
    return [t for t in parsed.get("turns", []) if t.get("role") == "assistant"]


def _maybe_finalize_over_budget(job: str, rel: str, info: dict) -> None:
    if info.get("finalizing") or info.get("cancelled"):
        return
    turns = _assistant_turns(info)
    if len(turns) < MAX_FIRST_PASS_TURNS:
        return
    report = _report_text(turns)
    if _findings_from_text(report) is not None:
        return
    base = av._safe_disk_path(rel)
    if base is None:
        return
    av.finalize_blue_team(job, base)


def _job_process_alive(job: str) -> bool:
    return av.lens_job_alive(job) or av.lens_workspace_alive(job)


def _retry_startup_failure(job: str, rel: str) -> bool:
    """Restart an audit killed before any transcript exists.

    This is the failure shape behind the rc=-9 saved errors: empty stderr, no
    session.jsonl, and no live sandbox to wait for. It is a launch/runtime kill,
    not an audit result, so do a bounded clean retry instead of persisting noise.
    """
    n = _STARTUP_RETRIES.get(rel, 0)
    if n >= STARTUP_RETRIES:
        return False
    _STARTUP_RETRIES[rel] = n + 1
    _PERSISTED.add(job)
    _PERSIST_TRIES.pop(job, None)
    with _LOCK:
        _JOBS.pop(job, None)
    with av._LENS_LOCK:
        info = av._LENS_JOBS.pop(job, None)
    if info and info.get("dir"):
        shutil.rmtree(info["dir"], ignore_errors=True)
    _start_one(rel)
    return True


def _persist(job: str, rel: str) -> None:
    if job in _PERSISTED:
        return
    info = av._LENS_JOBS.get(job)
    if info is None:
        if _job_process_alive(job):
            return
        _finish_job(job, rel)
        return
    if av.lens_job_alive(job, info):
        return  # still running, even if the wrapper's returncode is non-None
    if _job_process_alive(job):
        return  # wrapper status lied; sandbox child is still alive
    if info.get("followup_pending"):
        return  # first pass done; clarity follow-up not started/finished yet
    if info.get("cancelled"):
        _finish_job(job, rel)
        return

    try:
        data = av.lens_transcript(job)
        turns = data.get("turns", [])
        report = _report_text(turns)
        # Only a COMPLETED audit counts as a real result — one that emitted a
        # ```json findings``` block (even an EMPTY one is fine: "explored, found
        # nothing"). No findings block means the agent was killed / crashed /
        # errored / interrupted before finishing; do NOT freeze that as a clean
        # "no problems found" report. Retry a few ticks (the session jsonl can
        # lag process exit), then save an explicit failure artifact rather than a
        # misleading "no problems found" report.
        if _findings_from_text(report) is None:
            n = _PERSIST_TRIES.get(job, 0) + 1
            _PERSIST_TRIES[job] = n
            # Some pi/bwrap wrapper processes can report a killed/nonzero status
            # while the sandboxed child is still appending useful transcript text.
            # Do not freeze a failed audit until the transcript has gone quiet.
            if n < 6 or _session_recently_changed(info):
                return
            rc = getattr(info.get("proc"), "returncode", None)
            sess = info.get("session")
            no_session = not (sess and Path(sess).exists())
            if rc and rc < 0 and no_session and _retry_startup_failure(job, rel):
                return
            _save_failure(job, rel, info, _failure_detail(info, data))
            _finish_job(job, rel)
            return
        out = _saved_dir(rel)
        out.mkdir(parents=True, exist_ok=True)
        (out / ERROR).unlink(missing_ok=True)
        (out / STDERR_OUT).unlink(missing_ok=True)
        (out / REPORT).write_text(report)
        sess = info["session"]
        if sess.exists():
            shutil.copyfile(sess, out / SESSION_OUT)
        _backup_success(rel)
        _STARTUP_RETRIES.pop(rel, None)
    except Exception:
        pass
    _finish_job(job, rel)


def _lens_run_name(jobdir: Path) -> str | None:
    try:
        first = (jobdir / "TRACE_INDEX.md").read_text(errors="replace").splitlines()[0]
    except (IndexError, OSError):
        return None
    m = re.match(r"# Trace index for (.+)", first.strip())
    return m.group(1) if m else None


def _recover_orphaned_lens_audits(run_items: list[dict]) -> None:
    """Recover completed Blue Team sessions that lost their in-memory job record.

    The server is the only owner of _JOBS. If it is restarted, or if an older code
    path dropped a finished job before saving, a valid session can remain in
    outputs/.lens/<job>/ with no report under outputs/08_automated_blue_teaming/.
    This is opt-in because delete-all/manual clears must be authoritative: stale
    .lens sessions should not resurrect saved audits the user intentionally
    removed.
    """
    if not RECOVER_ORPHANS or not av.LENS_DIR.exists():
        return
    try:
        recovery_cutoff = BT_DIR.stat().st_mtime
    except OSError:
        recovery_cutoff = 0.0
    name_to_rel = {
        r.get("name"): r.get("path")
        for r in run_items
        if r.get("name") and r.get("path")
    }
    active = set(_JOBS)
    for jobdir in av.LENS_DIR.iterdir():
        if (
            not jobdir.is_dir()
            or jobdir.name in active
            or jobdir.name in _RECOVERED_LENS
        ):
            continue
        _RECOVERED_LENS.add(jobdir.name)
        rel = name_to_rel.get(_lens_run_name(jobdir) or "")
        if (
            not rel
            or (_saved_dir(rel) / REPORT).exists()
            or (_saved_dir(rel) / ERROR).exists()
        ):
            continue
        session = jobdir / "session.jsonl"
        if not session.exists():
            continue
        if session.stat().st_mtime < recovery_cutoff:
            continue
        turns = [
            t
            for t in av.parse_session(session.read_text(errors="replace")).get(
                "turns", []
            )
            if t.get("role") == "assistant"
        ]
        report = _report_text(turns)
        if _findings_from_text(report) is None:
            continue
        out = _saved_dir(rel)
        out.mkdir(parents=True, exist_ok=True)
        (out / ERROR).unlink(missing_ok=True)
        (out / STDERR_OUT).unlink(missing_ok=True)
        (out / REPORT).write_text(report)
        shutil.copyfile(session, out / SESSION_OUT)
        _backup_success(rel)


def _running_rels() -> set[str]:
    return set(_JOBS.values())


def _start_one(rel: str) -> str | None:
    """Spawn a streamable per-run audit and register it. Returns the job id."""
    if rel in _running_rels():
        return None
    _backup_success(rel)
    r = av.start_blue_team(rel)
    job = r.get("job")
    if job:
        _PERSISTED.discard(job)
        _PERSIST_TRIES.pop(job, None)
        with _LOCK:
            _JOBS[job] = rel
    return job


# One BatchRunner drives "Run all": enqueue every target, run BATCH_CAP at a
# time, advanced by the pump below. The same class powers the studio's batch.
_BATCH = web_common.BatchRunner(BATCH_CAP, _start_one, lambda: len(_JOBS))


def _running_members() -> int:
    return len(_BATCH.members() & _running_rels())


def _phase(r: dict) -> str:
    status = (r.get("phase") or r.get("status") or "").lower()
    if r.get("live") or status in {"active", "running", "live"}:
        return "Active"
    if status in {"failed", "error", "stale"}:
        return "Failed"
    return "Completed"


def _mode(name: str | None) -> str:
    name = name or ""
    if name.endswith("_multi_phase"):
        return "multi_phase"
    if name.endswith("_goal"):
        return "goal"
    return ""


def _cancel_rel(rel: str) -> None:
    """Cancel any live audit job(s) for a run (used by stop-all and delete)."""
    for job, jrel in list(_JOBS.items()):
        if jrel == rel:
            cancel(job)
    target = _name(rel)
    if av.LENS_DIR.exists():
        for jobdir in av.LENS_DIR.iterdir():
            if jobdir.is_dir() and _lens_run_name(jobdir) == target:
                av.kill_lens_workspace(jobdir.name)


def _pump() -> None:
    """Background daemon: persist finished audits (even with no client polling) and
    keep the Run-all queue flowing."""
    while True:
        for job, rel in list(_JOBS.items()):
            info = av._LENS_JOBS.get(job)
            if info is not None and av.lens_job_alive(job, info):
                _maybe_finalize_over_budget(job, rel, info)
            elif info is None or not av.lens_job_alive(job, info):
                _persist(job, rel)
        _BATCH.advance()
        time.sleep(3)


threading.Thread(target=_pump, daemon=True).start()


# --------------------------------------------------------------------------- #
# Batch (Run all) + lifecycle — one unified, streamable audit path for all runs
# --------------------------------------------------------------------------- #
def batch_running() -> bool:
    return _BATCH.status(_running_members())["batch"]


def batch_status() -> dict:
    return _BATCH.status(_running_members())


def list_runs() -> dict:
    out = []
    job_by_rel = {r: j for j, r in _JOBS.items()}  # the active audit job per run
    queued = _BATCH.queued()
    run_items = av.list_runs_overview()
    _recover_orphaned_lens_audits(run_items)
    for r in run_items:
        if r.get("type") and r["type"] != "run":
            continue
        rel = r.get("path")
        group = ""
        if rel:
            parts = rel.split("/")
            group = "/".join(parts[:-1])
        out.append(
            {
                "path": rel,
                "name": r.get("name"),
                "group": group,
                "mode": _mode(r.get("name")),
                "status": r.get("status"),
                "phase": _phase(r),
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
    item = next((r for r in list_runs()["items"] if r.get("path") == rel), None)
    if item and item.get("phase") != "Completed":
        return {"error": "only completed runs can be audited"}
    if rel in _running_rels() or rel in _BATCH.queued():
        return {"error": "this run is already queued or being audited"}
    job = _start_one(rel)
    return {"job": job} if job else {"error": "failed to start audit"}


def start_all() -> dict:
    """Queue a fresh audit for every completed (non-live) run. Each becomes a
    normal streamable job, started up to BATCH_CAP at a time."""
    if batch_running():
        return {"error": "a batch is already running"}
    rels = [r["path"] for r in list_runs()["items"] if r["phase"] == "Completed"]
    if not rels:
        return {"error": "no completed runs to audit"}
    return _BATCH.start_all(rels)


def stop_all() -> dict:
    return _BATCH.stop_all(_cancel_rel)


def cancel(job: str) -> dict:
    av.cancel_lens(job)
    _PERSISTED.add(job)  # don't save a cancelled, partial audit
    av.kill_lens_workspace(job)
    with _LOCK:
        _JOBS.pop(job, None)
    with av._LENS_LOCK:
        av._LENS_JOBS.pop(job, None)
    return {"ok": True}


def delete(rel: str) -> dict:
    # The user confirmed a destructive action — make it always work. Cancel any
    # in-flight (or stuck) audit for this run first, drop it from the queue, then
    # remove the saved dir. (Previously this refused while busy and the client
    # swallowed the error, so the button looked dead.)
    _cancel_rel(rel)
    _BATCH.discard(rel)
    d = _saved_dir(rel)
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


def delete_all() -> dict:
    # Always works: stop the batch + every in-flight audit (including dead-but-
    # unpersisted "stuck" jobs that linger in _JOBS), then wipe.
    _BATCH.stop_all(_cancel_rel)
    for job in list(_JOBS):
        cancel(job)
    if av.LENS_DIR.exists():
        for jobdir in av.LENS_DIR.iterdir():
            if jobdir.is_dir() and _lens_run_name(jobdir):
                av.kill_lens_workspace(jobdir.name)
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
    return web_common.serve(h, method, PREFIX, _get, _post)


def _get(h, path: str, query: str) -> None:
    # GET endpoints return data at HTTP 200 even when carrying {error}: their
    # clients poll quietly and parse the {error} body themselves (e.g. an expired
    # transcript job). The auto-4xx convention is for user actions (POST) below.
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
    # Mutations go through web_common.reply: an {error} result is sent as HTTP
    # 4xx so the client never reads a failed action as success.
    body = h._read_body()
    if path == "/api/start":
        return web_common.reply(h, start((body.get("run") or "").strip()))
    if path == "/api/start_all":
        return web_common.reply(h, start_all())
    if path == "/api/stop_all":
        return web_common.reply(h, stop_all())
    if path == "/api/cancel":
        return web_common.reply(h, cancel((body.get("job") or "").strip()))
    if path == "/api/delete":
        return web_common.reply(h, delete((body.get("run") or "").strip()))
    if path == "/api/delete_all":
        return web_common.reply(h, delete_all())
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

main{flex:1;display:flex;min-height:0}
.runitem{display:flex;align-items:baseline;gap:10px;text-align:left;background:transparent;
  border:1px solid transparent;border-radius:6px;padding:7px 9px;cursor:pointer;width:100%;color:var(--fg)}
.runitem:hover{background:var(--panel2);border-color:var(--border)}
.runitem.cur{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.runitem.unauditable{opacity:.65}
.runitem .rn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:600}
.runitem .rt{color:var(--faint);font-size:10px;white-space:nowrap;font-family:var(--mono)}
.muted{color:var(--muted);padding:16px;text-align:center;font-size:12.5px;line-height:1.6}
.phase-tabs{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:2px 2px 8px}
.phase-tab{border:1px solid var(--border);background:var(--panel2);color:var(--muted);
  border-radius:7px;padding:5px 10px;font-size:12px;font-weight:700;cursor:pointer;transition:.12s}
.phase-tab:hover{border-color:var(--accent);color:var(--fg)}
.phase-tab.active{border-color:var(--accent);background:var(--panel3);color:var(--fg)}
.phase-tab .num{color:var(--faint);font-weight:600;margin-left:4px}
.dgroup{font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:var(--faint);
  font-weight:700;margin:10px 4px 3px}
.dgroup:first-child{margin-top:2px}

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
.fissue{font-size:13px;margin:6px 0 4px;line-height:1.45}
.fmech{font-size:12.5px;color:var(--muted);margin:4px 0;line-height:1.45}
.fmech b,.fissue b{color:var(--fg)}
.ftext{display:inline}
.ftext p:first-child{display:inline}
.ftext p{margin:.25em 0}

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
</header>
<main>
  <aside class="side">
    <div class="sidehead">🛡 Runs <span class="spacer"></span></div>
    <div class="sideacts">
      <button class="primary mini" id="runAllBtn">▶ Run all</button>
      <button class="danger mini" id="delAllBtn">🗑 Delete all</button>
      <button class="danger mini" id="stopAllBtn" hidden>■ Stop all</button>
    </div>
    <div id="batchBanner"></div>
    <input id="search" class="sidesearch" placeholder="Filter runs…" autocomplete="off">
    <div class="phase-tabs" id="phaseTabs"></div>
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
let selectionSeq=0;
let pickerPhase="Completed";

//__APP_JS__
//__PROGRESS_JS__
//__API_JS__

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
  // Don't re-attach a job we already finished client-side: it lingers in the
  // server's job list through the clarity follow-up + persist, and re-attaching
  // it makes the panel bounce between the live log and "saving…".
  if(r.job && job!==r.job && !finished.has(r.job)){ job=r.job; viewKey=""; startPoll(); }
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
  let b = "";
  if(r.job) b += ' · <span class="status-badge running"><span class="tdot"></span>auditing</span>';
  else if(r.queued) b += ' · <span class="status-badge queued">queued</span>';
  else if(r.audit&&r.audit.error) b += ' · <span class="status-badge error">issue</span>';
  else if(r.audit) b += ` · <span class="status-badge done"><span class="dot ${r.audit.worst||'low'}"></span>${r.audit.count}</span>`;
  return b;
}
function renderRuns(){
  const q=$("#search").value.toLowerCase();
  const list=$("#rlist");
  const pool=runs.filter(r=>!q || (r.name||"").toLowerCase().includes(q));
  const counts={Completed:0,Active:0,Failed:0};
  pool.forEach(r=>{ if(counts[r.phase]!=null) counts[r.phase]++; });
  if(!counts[pickerPhase])
    pickerPhase = counts.Completed?"Completed":(counts.Active?"Active":(counts.Failed?"Failed":pickerPhase));
  $("#phaseTabs").innerHTML=["Completed","Active","Failed"].map(ph=>
    `<button class="phase-tab${ph===pickerPhase?' active':''}" data-ph="${ph}">${ph} <span class="num">${counts[ph]}</span></button>`).join("");
  $("#phaseTabs").querySelectorAll(".phase-tab").forEach(b=>b.onclick=()=>switchPhase(b.dataset.ph));
  const items=pool.filter(r=>r.phase===pickerPhase);
  if(!items.length){ list.innerHTML=`<div class="muted">no ${pickerPhase.toLowerCase()} runs</div>`; return; }
  let g=null, html="";
  for(const r of items){
    if((r.group||"")!==g){ g=r.group||""; html+=`<div class="dgroup">${esc(g||"runs")}</div>`; }
    const auditable=r.phase==="Completed";
    html+=`<button class="runitem${r.path===cur?' cur':''}${auditable?'':' unauditable'}" data-p="${esc(r.path)}">`
      +`<span class="rn" title="${esc(r.name)}">${esc(r.name)}</span>`
      +`<span class="rt">${esc(r.mode||"")}${badge(r)}</span></button>`;
  }
  list.innerHTML=html;
  list.querySelectorAll(".runitem").forEach(b=>b.onclick=()=>select(b.dataset.p));
}

function switchPhase(ph){
  pickerPhase=ph;
  const selected=runs.find(r=>r.path===cur);
  if(selected && selected.phase!==pickerPhase){
    const word=pickerPhase.toLowerCase(), article=/^[aeiou]/.test(word)?"an":"a";
    clearSelection(`Pick ${article} ${word} run on the left.`);
  }
  renderRuns(); setButtons();
}

function clearSelection(message){
  selectionSeq++;
  if(poll){ clearInterval(poll); poll=null; }
  job=null; cur=null; viewKey=""; savedMtime=0; hidden.clear(); logOpen=true;
  $("#curTitle").textContent="No run selected";
  $("#curMeta").textContent="";
  $("#results").innerHTML=`<div class="empty">${esc(message||"Pick a run on the left.")}</div>`;
}

function setButtons(){
  const r=runs.find(x=>x.path===cur);
  const auditing=!!(r&&r.job);            // this run currently has a live audit
  const auditable=!!(r&&r.phase==="Completed");
  $("#auditBtn").hidden=auditing;
  $("#cancelBtn").hidden=!auditing;
  // concurrent audits are fine; only completed runs can be audited.
  $("#auditBtn").disabled=!cur||!auditable||batch;
  $("#auditBtn").textContent=(r&&r.audit)?"↻ Re-run audit":"🛡 Run audit";
  $("#delBtn").hidden=!(r&&r.audit)||auditing;
}

// ---- selection (never blocks; audits keep running server-side) ----
async function select(p){
  const seq=++selectionSeq;
  if(poll){ clearInterval(poll); poll=null; }   // stop streaming the previous run (its audit keeps going)
  job=null; cur=p; viewKey=""; savedMtime=0; hidden.clear(); logOpen=true;
  const r=runs.find(x=>x.path===p);
  $("#curTitle").textContent=r?r.name:p;
  $("#curMeta").textContent="";
  renderRuns(); setButtons();
  if(r&&r.job&&!finished.has(r.job)){ job=r.job; $("#results").innerHTML='<div class="empty">attaching to the live audit…</div>'; startPoll(); }
  else if(r&&r.queued){ $("#results").innerHTML='<div class="empty">⏳ queued for audit — it will start when a slot frees, then stream here.</div>'; }
  else if(r&&(r.audit||r.job)){
    $("#results").innerHTML='<div class="empty"><span class="tdot"></span><span class="tdot"></span><span class="tdot"></span> loading saved audit for <b>'+esc(r.name||p)+'</b>…</div>';
    showSaved(p, seq);
  }
  else if(r&&r.phase!=="Completed") $("#results").innerHTML='<div class="empty"><b>'+esc(r.name||p)+'</b> is '+esc(r.phase.toLowerCase())+'.<br>Blue Team audits are for completed runs.</div>';
  else $("#results").innerHTML='<div class="empty">Ready to audit <b>'+esc(r?r.name:p)+'</b>'
    +'.<br>Click <b>🛡 Run audit</b>.</div>';
}
let savedMtime=0;
let finished=new Set();   // job ids we've already finished client-side
async function showSaved(rel, seq=selectionSeq){
  const d=await api(API+"/saved?run="+encodeURIComponent(rel), undefined, true);
  if(cur!==rel || seq!==selectionSeq) return; // user switched runs mid-fetch — don't clobber
  if(!d||!d.exists){
    // Report persists a beat after the agent exits. Always render a state for
    // the selected run; keeping the previous pane here makes run switching look
    // broken when the newly selected audit has not saved a transcript yet.
    const r=runs.find(x=>x.path===rel), pending=r&&(r.job||r.queued);
    $("#results").innerHTML=pending
      ?'<div class="empty"><span class="tdot"></span><span class="tdot"></span><span class="tdot"></span> finishing audit — saving report…</div>'
      :'<div class="empty">No saved audit.</div>';
    return;
  }
  // Fetch the transcript too BEFORE touching the DOM, so the pane swaps exactly
  // once (no flash of report-without-log, and the prior view stays put until now).
  const t=await api(API+"/saved_transcript?run="+encodeURIComponent(rel), undefined, true);
  if(cur!==rel || seq!==selectionSeq) return;
  savedMtime=d.mtime;
  const turns=(t&&t.turns)||[];
  if(d.error){
    let html=`<div class="savednote">saved failed audit · ${new Date(d.mtime*1000).toLocaleString()}</div>`;
    html+=`<div class="errbox">${esc(d.error)}</div>`;
    if(turns.length){
      const logTurns=turns.map(tn=>`<div class="turn"><div class="role">Blue Team agent</div><div class="body">${(tn.blocks||[]).map(blockHtml).join("")}</div></div>`).join("");
      html+=`<details id="logBox" open><summary>Partial transcript · ${steps(turns)} steps</summary><div id="log">${logTurns}</div></details>`;
    }
    $("#results").innerHTML=html;
    return;
  }
  let html=`<div class="savednote">saved audit · ${new Date(d.mtime*1000).toLocaleString()}</div>`;
  if(d.orient) html+=`<div id="orient">${md(d.orient)}</div>`;
  html+=d.findings.length?renderFindings(d.findings,false)
    :'<div class="muted">No result-affecting problems were found in this run.</div>';
  if(turns.length){
    const logTurns=turns.map(tn=>`<div class="turn"><div class="role">Blue Team agent</div><div class="body">${(tn.blocks||[]).map(blockHtml).join("")}</div></div>`).join("");
    html+=`<details id="logBox"><summary>Exploration log · ${steps(turns)} steps</summary><div id="log">${logTurns}</div></details>`;
  }
  $("#results").innerHTML=html;
  bindChips(d.findings);
}
function maybeRefreshSaved(r){ if(r.audit && r.audit.mtime>savedMtime+0.5 && cur===r.path) showSaved(r.path, selectionSeq); }

// ---- findings cards ----
function findCard(f){
  const lvl=LEVELS.includes((f.concern||"").toLowerCase())?f.concern.toLowerCase():"low";
  const conf=(f.confidence!=null&&f.confidence!=="")?` · confidence ${esc(String(f.confidence))}`:"";
  return `<div class="fcard ${lvl}"${hidden.has(lvl)?' style="display:none"':''}>`
    +`<div class="fhead"><span class="fbadge ${lvl}">${lvl}</span>`
    +`<span class="ftitle">${esc(f.title||"(untitled)")}</span><span class="fconf">${conf}</span></div>`
    +(f.location?`<div class="floc">${esc(f.location)}</div>`:"")
    +(f.issue?`<div class="fissue"><b>Issue:</b> <div class="ftext">${md(f.issue)}</div></div>`:"")
    +(f.mechanism?`<div class="fmech"><b>Why it matters:</b> <div class="ftext">${md(f.mechanism)}</div></div>`:"")
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
  for(const b of [...text.matchAll(/```json[ \t]*\n([\s\S]*?)```/g)].reverse()){
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
  const res=$("#results");
  const atBottom=res.scrollHeight-res.scrollTop-res.clientHeight<140;
  const logTurns=turns.map(t=>`<div class="turn"><div class="role">Blue Team agent</div><div class="body">${(t.blocks||[]).map(blockHtml).join("")}</div></div>`).join("");
  if(running){
    let lb=$("#logBox"), lg=$("#log");
    if(!lb){
      res.innerHTML=`<div class="summary"><span class="total"><span class="tdot"></span><span class="tdot"></span><span class="tdot"></span> auditing…</span></div>`
        +(logTurns
          ?`<details id="logBox" open><summary>Live transcript · ${steps(turns)} steps</summary><div id="log">${logTurns}</div></details>`
          :'<div class="empty">Waiting for auditor output…</div>');
      lb=$("#logBox"); lg=$("#log");
    }else{
      if(lg) lg.innerHTML=logTurns;
      const sum=lb.querySelector("summary");
      if(sum) sum.textContent=`Live transcript · ${steps(turns)} steps`;
    }
    if(atBottom) res.scrollTop=res.scrollHeight;
    return;
  }
  if(findings && !running){ // final findings state — render once (full swap is fine, it's terminal)
    logOpen=false;
    let html=findings.length?renderFindings(findings,running):'<div class="muted">No result-affecting problems found.</div>';
    if(logTurns) html+=`<details id="logBox"><summary>Exploration log · ${steps(turns)} steps</summary><div id="log">${logTurns}</div></details>`;
    res.innerHTML=html; bindChips(findings);
    return;
  }
  res.innerHTML=logTurns
    ?`<details id="logBox" open><summary>Transcript · ${steps(turns)} steps</summary><div id="log">${logTurns}</div></details>`
    :'<div class="empty">No output yet.</div>';
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
  const myjob=job, seq=selectionSeq;
  const d=await api(API+"/transcript?job="+encodeURIComponent(myjob), undefined, true);
  if(myjob!==job || seq!==selectionSeq) return;        // user switched runs mid-fetch
  if(!d) return;
  if(d.error && !(d.turns&&d.turns.length)){ $("#results").innerHTML='<div class="errbox">'+esc(d.error)+'</div>'; finishView(); return; }
  renderLive(d);
  $("#curMeta").textContent=d.running?"auditing…":"done";
  if(!d.running) finishView();
}
function finishView(){
  const rel=cur, seq=selectionSeq;
  if(poll){ clearInterval(poll); poll=null; }
  if(job) finished.add(job);   // never auto-re-attach this job again
  job=null; viewKey=""; savedMtime=0;
  const r=runs.find(x=>x.path===cur); if(r){ r.running=false; r.job=null; }
  setButtons();
  setTimeout(()=>{ loadRuns(); if(cur===rel && seq===selectionSeq) showSaved(rel, seq); }, 1200);  // let the daemon persist
}
async function cancelAudit(){ if(!job) return; await api(API+"/cancel",{job}); toast("audit stopped"); finishView(); }

// ---- batch + delete ----
async function runAll(){
  const n=runs.filter(r=>r.phase==="Completed").length;
  if(!confirm(`Run a fresh audit on all ${n} completed runs? This overwrites existing saved audits and uses real model calls.`)) return;
  const d=await api(API+"/start_all",{}); if(!d||d.error) return;
  toast("running all audits…"); loadRuns();
}
async function stopAll(){ if(!confirm("Stop the running batch?")) return; await api(API+"/stop_all",{}); toast("stopping batch…"); setTimeout(loadRuns,800); }
async function deleteAudit(){
  if(!cur) return;
  if(!confirm("Delete the saved audit for this run? If an audit is running for it, this stops it.")) return;
  const d=await api(API+"/delete",{run:cur}); if(!d||d.error) return;
  await loadRuns(); select(cur);
}
async function deleteAll(){
  if(!confirm("Delete ALL saved audits? This also stops any audits currently running or queued.")) return;
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
    .replace("//__API_JS__", API_JS)
)
