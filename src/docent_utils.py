"""Upload our pi research runs to Docent (https://docent.transluce.org) as one
navigable collection.

Why this exists
---------------
Each research run lives at ``outputs/03_run_agents/<proposal>_multi_phase/`` and is
produced by the ``/run-loop`` planner -> worker -> reviewer loop. The real work is
split into *segments* and *phases*; within each phase several sub-agents run (the
phase planner that plans it, the worker that executes it, an optional reviewer), and
each sub-agent is its own pi session ``.jsonl``. ``planner/RUN_LOOP_STATE.json`` is the
authoritative index that maps every ``segment:phase`` to those session files.

Mapping onto Docent's data model
--------------------------------
Docent organizes data as ``Collection -> AgentRun -> (TranscriptGroup tree) ->
Transcript -> messages``. We map our hierarchy straight onto it so the result is
browsable without losing structure:

    Collection            one collection for the whole benchmark
      AgentRun            one per proposal run  (e.g. "Slop Probes")
        TranscriptGroup   "Planning & overview"  -> the overall (main) planner
        TranscriptGroup   "Segment 0 · Phase 0"  -> the phase's sub-agents
          Transcript        Worker        (executed the phase)
          Transcript        Phase planner (planned it / planned the next)
          Transcript        Reviewer      (if present)
        TranscriptGroup   "Segment 1 · Phase 0"
          ...

So in the UI: the collection lists proposals; expanding a proposal shows its phases in
order; expanding a phase shows the individual agent runs inside it. Metadata (proposal,
stage, segment/phase, model, cost, message/tool counts, status) is attached at every
level for filtering and search.

Usage
-----
    # Build everything and print a summary WITHOUT uploading (no API key needed):
    python -m src.docent_utils --dry-run

    # Upload (needs DOCENT_API_KEY in the environment or .env):
    python -m src.docent_utils --name "Slopbench research runs" --public

    # Limit to specific proposals:
    python -m src.docent_utils --dry-run --only empirical_slop_probes empirical_gradient_hacking
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docent.data_models import AgentRun, Transcript, TranscriptGroup  # noqa: E402
from docent.data_models.chat import (  # noqa: E402
    AssistantMessage,
    ContentReasoning,
    ContentText,
    ToolCall,
    ToolMessage,
    UserMessage,
)

from src.runner_utils import parse_env_text  # noqa: E402
from src.sandbox import session_host_path  # noqa: E402

OUTPUTS_DIR = ROOT / "outputs" / "03_run_agents"
DEFAULT_COLLECTION_NAME = "Slopbench research runs"
DEFAULT_COLLECTION_DESC = (
    "Autonomous multi-phase research runs (pi /run-loop). One agent run per research "
    "proposal; transcript groups are the overall plan then each segment/phase; within a "
    "phase the transcripts are the worker, phase-planner and main-review sub-agents."
)

# The single main-planner thread is split into per-phase "Main review" chunks at each
# boundary user-message (mirrors agent_viewer._MP_BOUNDARY_RE). Everything before the
# first boundary is the initial overall plan.
_MP_BOUNDARY_RE = re.compile(
    r"finished reviewing the work done in segment\s*(\d+)\s*,?\s*phase\s*(\d+)", re.I
)

# A single tool result can be a whole file dump; keep payloads sane but generous.
MAX_MESSAGE_CHARS = 200_000

# Docent ids are VARCHAR(36) UUID primary keys, so human-readable ids are rejected.
# uuid5 off a fixed namespace gives a valid UUID that is stable across re-uploads
# (same logical key -> same id), which keeps re-runs idempotent instead of duplicating.
_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "slopbench.docent")


def _uuid(key: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, key))


# --------------------------------------------------------------------------- #
# Low-level parsing of pi session .jsonl -> Docent chat messages
# --------------------------------------------------------------------------- #
def _iter_jsonl(path: Path):
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _content_text(content: Any) -> str:
    """Flatten a pi content value (str, or list of {type:text|...}) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                if c.get("type") == "text":
                    parts.append(c.get("text", ""))
                elif c.get("type") == "image":
                    parts.append("[image omitted]")
            elif isinstance(c, str):
                parts.append(c)
        return "\n".join(p for p in parts if p)
    return ""


def _truncate(text: str) -> str:
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    head = text[:MAX_MESSAGE_CHARS]
    return f"{head}\n\n[... truncated {len(text) - MAX_MESSAGE_CHARS} chars ...]"


def _to_dt(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class SessionParse:
    # each item is (ChatMessage, timestamp, pi_entry_id). The pi entry id is kept OUT of the
    # Docent message (the server rejects provided message ids) and used only as a side channel:
    # to de-dup a phase-planner fork (which copies the main-planner history verbatim, same ids)
    # and to split the main-planner thread at boundary user-messages.
    items: list = field(default_factory=list)
    model: str | None = None
    cost_usd: float = 0.0
    n_tool_calls: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None

    @property
    def messages(self) -> list:
        return [m for m, _, _ in self.items]

    @property
    def n_messages(self) -> int:
        return len(self.items)


def parse_pi_session(path: Path) -> SessionParse:
    """Parse one pi session .jsonl into (Docent chat message, timestamp) items + light stats.

    pi records each turn as a ``message`` entry with ``message.role`` in
    {user, assistant, toolResult}. Assistant content is a list of parts
    (text / thinking / toolCall / image); tool results arrive as their own
    ``toolResult`` entries keyed by ``toolCallId``. The pi entry ``id`` is stored on each
    Docent message so forks can be de-duplicated by id.
    """
    out = SessionParse()
    tc_counter = 0
    for entry in _iter_jsonl(path):
        if entry.get("type") != "message":
            continue
        msg = entry.get("message") or {}
        role = msg.get("role")
        eid = entry.get("id")
        dt = _to_dt(entry.get("timestamp") or msg.get("timestamp"))
        if dt is not None:
            out.first_ts = out.first_ts or dt
            out.last_ts = dt

        if role == "user":
            text = _truncate(_content_text(msg.get("content")))
            out.items.append((UserMessage(content=text), dt, eid))

        elif role == "assistant":
            out.model = msg.get("model") or out.model
            cost = ((msg.get("usage") or {}).get("cost") or {}).get("total")
            if isinstance(cost, (int, float)):
                out.cost_usd += cost
            content: list = []
            tool_calls: list[ToolCall] = []
            for c in msg.get("content") or []:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                if ctype == "text" and c.get("text", "").strip():
                    content.append(ContentText(text=_truncate(c["text"])))
                elif ctype == "thinking" and c.get("thinking", "").strip():
                    content.append(
                        ContentReasoning(
                            reasoning=_truncate(c["thinking"]),
                            signature=c.get("thinkingSignature"),
                        )
                    )
                elif ctype == "toolCall":
                    tc_counter += 1
                    args = c.get("arguments")
                    if not isinstance(args, dict):
                        args = {"_value": args}
                    tool_calls.append(
                        ToolCall(
                            id=c.get("id") or f"call_{tc_counter}",
                            function=c.get("name", "tool"),
                            arguments=args,
                        )
                    )
                    out.n_tool_calls += 1
                elif ctype == "image":
                    content.append(ContentText(text="[image omitted]"))
            out.items.append(
                (
                    AssistantMessage(
                        content=content if content else "",
                        tool_calls=tool_calls or None,
                        model=msg.get("model"),
                    ),
                    dt,
                    eid,
                )
            )

        elif role == "toolResult":
            text = _truncate(_content_text(msg.get("content")))
            err = {"message": text[:2000]} if msg.get("isError") else None
            out.items.append(
                (
                    ToolMessage(
                        tool_call_id=msg.get("toolCallId"),
                        function=msg.get("toolName"),
                        content=text,
                        error=err,
                    ),
                    dt,
                    eid,
                )
            )
    return out


def _split_main_planner(items: list) -> tuple[list, dict]:
    """Split the main-planner items into (initial_overall_plan, {(seg,phase): review_items}).

    Each per-phase "Main review" starts at the boundary user-message
    "...finished reviewing the work done in segment X, phase Y..."; everything before the
    first boundary is the initial overall plan. (Mirrors agent_viewer._split_main_planner;
    continuation re-openings of a phase simply append to that phase's chunk.)
    """
    initial: list = []
    chunks: dict = {}
    cur = None
    for item in items:
        msg = item[0]
        if isinstance(msg, UserMessage) and isinstance(msg.content, str):
            m = _MP_BOUNDARY_RE.search(msg.content)
            if m:
                cur = (int(m.group(1)), int(m.group(2)))
                chunks.setdefault(cur, [])
        (chunks[cur] if cur is not None else initial).append(item)
    return initial, chunks


def _dedup_fork(items: list, parent_ids: set) -> list:
    """Drop messages a phase-planner fork inherited verbatim from the main planner (same pi id).
    Falls back to all items if dedup would empty it (mirrors agent_viewer)."""
    uniq = [it for it in items if not (it[2] and it[2] in parent_ids)]
    return uniq or items


# --------------------------------------------------------------------------- #
# Run -> AgentRun assembly
# --------------------------------------------------------------------------- #
def _slug(run_dir: Path) -> str:
    name = run_dir.name
    for suffix in ("_multi_phase", "_goal"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _proposal_title_desc(run_dir: Path) -> tuple[str, str]:
    """Title (first ``# heading``) and description (first paragraph) from the
    run's own proposal.md, falling back to the proposals/ source."""
    candidates = [run_dir / "proposal.md", ROOT / "proposals" / f"{_slug(run_dir)}.md"]
    for path in candidates:
        if not path.exists():
            continue
        title, desc = "", ""
        lines = path.read_text(errors="replace").splitlines()
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break
        for line in lines:
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith("---"):
                desc = s
                break
        if title:
            return title, desc
    return _slug(run_dir).replace("_", " ").title(), ""


def _phase_key(k: str) -> tuple[int, int]:
    seg, _, phase = k.partition(":")
    try:
        return int(seg), int(phase)
    except ValueError:
        return (0, 0)


def _transcript_from_items(
    items: list,
    *,
    transcript_id: str,
    name: str,
    group_id: str,
    stage: str,
    seg: int,
    phase: int,
    model: str | None,
    session_file: str | None,
) -> Transcript | None:
    if not items:
        return None
    msgs = [m for m, _, _ in items]
    first_ts = next((t for _, t, _ in items if t is not None), None)
    n_tool = sum(
        len(m.tool_calls)
        for m in msgs
        if isinstance(m, AssistantMessage) and m.tool_calls
    )
    return Transcript(
        id=transcript_id,
        name=name,
        transcript_group_id=group_id,
        created_at=first_ts,
        messages=msgs,
        metadata={
            "stage": stage,
            "segment": seg,
            "phase": phase,
            "model": model,
            "num_messages": len(msgs),
            "num_tool_calls": n_tool,
            "session_file": session_file,
        },
    )


def build_agent_run(run_dir: Path) -> AgentRun | None:
    """Assemble one proposal run into a Docent AgentRun with a phase/segment tree.

    Per phase we surface the run-loop's real worker -> phase-planner -> main-review story:
    the single main-planner thread is split into the initial overall plan (Planning group,
    sorts first) plus one "Main review" chunk per phase (in that phase's group); phase-planner
    forks are de-duplicated against the main planner so its history isn't repeated. Every group's
    created_at is the earliest start of its transcripts, so Docent (which sorts children by
    created_at) renders Planning first and phases in chronological order.
    """
    state_path = run_dir / "planner" / "RUN_LOOP_STATE.json"
    if not state_path.exists():
        return None
    try:
        state = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    slug = _slug(run_dir)
    run_id = _uuid(f"run:{slug}")
    title, desc = _proposal_title_desc(run_dir)
    sessions = state.get("sessions") or {}
    workers = sessions.get("workers") or {}
    reviewers = sessions.get("reviewers") or {}
    phase_planners = sessions.get("phasePlanners") or {}
    completed = {
        (c.get("segment"), c.get("phase")): c for c in (state.get("completed") or [])
    }

    def host(container_path) -> Path | None:
        if not isinstance(container_path, str):
            return None
        p = session_host_path(container_path, run_dir)
        return p if (p and p.exists()) else None

    transcripts: list[Transcript] = []
    totals: list[SessionParse] = []  # whole-session parses, for run-level aggregates
    group_min_ts: dict[str, datetime] = (
        {}
    )  # gid -> earliest transcript start (group order)
    group_seen: set[str] = set()  # gids that received >=1 transcript

    def emit(items, *, gid, name, stage, seg, phase, session_file):
        t = _transcript_from_items(
            items,
            transcript_id=_uuid(f"transcript:{slug}:{stage}:{seg}:{phase}"),
            name=name,
            group_id=gid,
            stage=stage,
            seg=seg,
            phase=phase,
            model=run_model,
            session_file=session_file,
        )
        if t is None:
            return
        transcripts.append(t)
        group_seen.add(gid)
        if t.created_at is not None:
            cur = group_min_ts.get(gid)
            if cur is None or t.created_at < cur:
                group_min_ts[gid] = t.created_at

    # 1. Main planner: parse once (for totals + id-dedup), then split into the initial
    #    overall plan + per-phase main-review chunks.
    mp_path = host(sessions.get("mainPlanner"))
    mp_initial: list = []
    mp_reviews: dict = {}
    mp_ids: set = set()
    mp_file = mp_path.name if mp_path else None
    run_model: str | None = None
    if mp_path:
        mp = parse_pi_session(mp_path)
        totals.append(mp)
        run_model = mp.model
        mp_ids = {e for _, _, e in mp.items if e}
        mp_initial, mp_reviews = _split_main_planner(mp.items)

    planning_gid = _uuid(f"group:{slug}:planning")

    # The /init-planner session (writes OVERALL_PLAN.md) runs FIRST; it is separate from the
    # main-planner-review thread and lives at .pi_transcripts/planner.session.jsonl. Its early
    # start makes the Planning group sort first.
    ip_path = run_dir / ".pi_transcripts" / "planner.session.jsonl"
    if ip_path.exists():
        ip = parse_pi_session(ip_path)
        totals.append(ip)
        run_model = run_model or ip.model
        emit(
            ip.items,
            gid=planning_gid,
            name="Overall planner",
            stage="planner",
            seg=-1,
            phase=-1,
            session_file=ip_path.name,
        )

    # The pre-first-review portion of the main-planner thread (run-loop kickoff); usually empty
    # because the planning happens in /init-planner above, so emit() skips it when empty.
    emit(
        mp_initial,
        gid=planning_gid,
        name="Run-loop kickoff",
        stage="main_planner",
        seg=-1,
        phase=-1,
        session_file=mp_file,
    )

    # 2. One group per segment:phase: Worker -> Phase planner -> Main review.
    phase_keys = sorted(
        {_phase_key(k) for k in (set(workers) | set(reviewers) | set(phase_planners))}
        | set(mp_reviews),
    )
    for seg, phase in phase_keys:
        gid = _uuid(f"group:{slug}:s{seg}_p{phase}")
        skey = f"{seg}:{phase}"

        wp_path = host(workers.get(skey))
        if wp_path:
            wp = parse_pi_session(wp_path)
            totals.append(wp)
            emit(
                wp.items,
                gid=gid,
                name="Worker",
                stage="worker",
                seg=seg,
                phase=phase,
                session_file=wp_path.name,
            )

        pp_path = host(phase_planners.get(skey))
        if pp_path:
            pp = parse_pi_session(pp_path)
            totals.append(pp)
            emit(
                _dedup_fork(pp.items, mp_ids),
                gid=gid,
                name="Phase planner",
                stage="phase_planner",
                seg=seg,
                phase=phase,
                session_file=pp_path.name,
            )

        rv_path = host(reviewers.get(skey))
        if rv_path:
            rv = parse_pi_session(rv_path)
            totals.append(rv)
            emit(
                rv.items,
                gid=gid,
                name="Reviewer",
                stage="reviewer",
                seg=seg,
                phase=phase,
                session_file=rv_path.name,
            )

        emit(
            mp_reviews.get((seg, phase)),
            gid=gid,
            name="Main review",
            stage="main_review",
            seg=seg,
            phase=phase,
            session_file=mp_file,
        )

    if not transcripts:
        return None

    # 3. Build the groups (created_at = earliest member transcript -> Planning first).
    groups: list[TranscriptGroup] = []
    if planning_gid in group_seen:
        groups.append(
            TranscriptGroup(
                id=planning_gid,
                name="Planning & overview",
                agent_run_id=run_id,
                created_at=group_min_ts.get(planning_gid),
                metadata={"kind": "planning"},
            )
        )
    for seg, phase in phase_keys:
        gid = _uuid(f"group:{slug}:s{seg}_p{phase}")
        if gid not in group_seen:
            continue
        cinfo = completed.get((seg, phase), {})
        groups.append(
            TranscriptGroup(
                id=gid,
                name=f"Segment {seg} · Phase {phase}",
                agent_run_id=run_id,
                created_at=group_min_ts.get(gid),
                metadata={
                    "kind": "phase",
                    "segment": seg,
                    "phase": phase,
                    "decision": cinfo.get("decision"),
                    "completed_at": cinfo.get("completedAt"),
                    "completed": bool(cinfo),
                },
            )
        )

    # Aggregate run-level stats from whole-session parses (each counted once).
    total_cost = round(sum(p.cost_usd for p in totals), 2)
    total_msgs = sum(p.n_messages for p in totals)
    total_tools = sum(p.n_tool_calls for p in totals)
    first_ts = min((p.first_ts for p in totals if p.first_ts), default=None)
    last_ts = max((p.last_ts for p in totals if p.last_ts), default=None)
    model = run_model or next((p.model for p in totals if p.model), None)
    n_segments = len({_phase_key(k)[0] for k in workers})

    metadata = {
        "proposal": slug,
        "title": title,
        "mode": "multi_phase",
        "model": model,
        "status": state.get("status"),
        "current_segment": state.get("currentSegment"),
        "current_phase": state.get("currentPhase"),
        "stage": state.get("stage"),
        "segments_completed": len(state.get("completed") or []),
        "num_segments_started": n_segments,
        "num_transcripts": len(transcripts),
        "total_messages": total_msgs,
        "total_tool_calls": total_tools,
        "cost_usd": total_cost,
        "state_cost_usd": round(state.get("costUsd", 0) or 0, 2),
        "started_at": first_ts.isoformat() if first_ts else None,
        "last_activity": last_ts.isoformat() if last_ts else None,
        "run_dir": str(run_dir.relative_to(ROOT)),
    }

    return AgentRun(
        id=run_id,
        name=title,
        description=desc or None,
        transcripts=transcripts,
        transcript_groups=groups,
        metadata=metadata,
    )


def build_all(only: list[str] | None = None) -> list[AgentRun]:
    runs: list[AgentRun] = []
    for run_dir in sorted(OUTPUTS_DIR.glob("*_multi_phase")):
        if not run_dir.is_dir():
            continue
        if only and _slug(run_dir) not in only:
            continue
        run = build_agent_run(run_dir)
        if run is not None:
            runs.append(run)
    return runs


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #
def upload(
    runs: list[AgentRun],
    *,
    name: str = DEFAULT_COLLECTION_NAME,
    description: str = DEFAULT_COLLECTION_DESC,
    collection_id: str | None = None,
    api_key: str | None = None,
    public: bool = False,
) -> tuple[str, str]:
    """Create (or reuse) a collection and push every AgentRun into it.

    Returns ``(collection_id, web_url)``.
    """
    from docent import Docent

    api_key = api_key or os.getenv("DOCENT_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DOCENT_API_KEY is not set. Add it to .env or export it, then re-run. "
            "Generate one at https://docent.transluce.org (account settings)."
        )

    client = Docent(api_key=api_key)
    if collection_id is None:
        collection_id = client.create_collection(name=name, description=description)
    # One run per request: individual runs can be tens of MB, so we avoid a single
    # giant POST and get per-run progress + resilience.
    client.add_agent_runs(collection_id, runs, batch_size=1)
    if public:
        client.make_collection_public(collection_id)
    web_url = f"https://docent.transluce.org/dashboard/{collection_id}"
    return collection_id, web_url


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists() or os.getenv("DOCENT_API_KEY"):
        return
    for key, value in parse_env_text(env.read_text()).items():
        os.environ.setdefault(key, value)


def _summary(runs: list[AgentRun]) -> str:
    lines = [f"Built {len(runs)} agent run(s):"]
    tot_t = tot_m = 0
    for r in runs:
        m = r.metadata
        n_groups = len(r.transcript_groups)
        tot_t += len(r.transcripts)
        tot_m += m.get("total_messages", 0)
        lines.append(
            f"  {m['proposal']:42} {m.get('status','?'):9} "
            f"groups={n_groups:2d} transcripts={len(r.transcripts):3d} "
            f"msgs={m.get('total_messages',0):5d} tools={m.get('total_tool_calls',0):5d} "
            f"${m.get('cost_usd',0):.0f}"
        )
    lines.append(f"Totals: transcripts={tot_t} messages={tot_m}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Upload pi research runs to Docent.")
    ap.add_argument(
        "--dry-run", action="store_true", help="Build + summarize, no upload."
    )
    ap.add_argument("--name", default=DEFAULT_COLLECTION_NAME, help="Collection name.")
    ap.add_argument(
        "--collection-id", default=None, help="Append to an existing collection."
    )
    ap.add_argument(
        "--public", action="store_true", help="Make the collection public after upload."
    )
    ap.add_argument(
        "--only", nargs="*", default=None, help="Limit to these proposal slugs."
    )
    args = ap.parse_args()

    _load_dotenv()
    runs = build_all(only=args.only)
    print(_summary(runs))
    if not runs:
        raise SystemExit("No runs found to upload.")
    if args.dry_run:
        print("\n(dry run — nothing uploaded)")
        return

    collection_id, url = upload(
        runs, name=args.name, collection_id=args.collection_id, public=args.public
    )
    print(f"\nUploaded {len(runs)} runs to collection {collection_id}")
    print(f"View: {url}")


if __name__ == "__main__":
    main()
