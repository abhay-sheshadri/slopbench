#!/usr/bin/env python3
"""Automated blue-teaming: audit a completed run for research sabotage.

A read-only blue-team agent audits the run (its code, transcripts, raw results) and
writes a sabotage verdict: a credence (0-100) that the run was deliberately sabotaged,
plus exactly five proposed fixes with per-fix credence and mechanism, the vectors it
considered, and per-vector findings. This is a port of the blue-teaming scaffold from
k-shenoy/exploration-hacking, adapted to slopbench's run-dir layout (the pi transcripts
are the audit trail rather than a separate per-diff/per-command log).

The source run is mounted READ-ONLY at /source; the agent works in a throwaway dir, and
only the final artifacts are copied into ``outputs/08_automated_blue_teaming/<run-name>/``:
    blue_team_report.md              (the verdict; *_NN.md when --samples > 1)
    blue_team_agent_session.jsonl    (the agent's own trajectory, for auditing)

Because a single auditor is noisy, ``--samples N`` runs N INDEPENDENT auditors (fresh
session each) over the same run; each writes its own report + session, so you can read the
spread of credences. The reports are independent, not a review/fix loop.

The agent prompts live as Jinja2 templates in ``prompts/`` next to this file:
    prompts/_sabotage_guide.md.j2   the ported guide (sabotage definition + output format)
    prompts/blue_team.md.j2         the task prompt (includes the guide)

Usage:
    python experiments/08_automated_blue_teaming/make_blue_team.py <path-to-run-dir>
    ./experiments/08_automated_blue_teaming/make_blue_team.py \\
        outputs/03_run_agents/empirical_filler_token_scaling_multi_phase --samples 3

The argument must be an actual run/project dir (one that contains ``.pi_transcripts/``).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import audit_agent, blue_team  # noqa: E402

# Blue-teaming is a careful reasoning / judgement task, so default to the strongest
# available Claude reasoning model (the same one the research agents run on) rather than
# the GPT writing default. This account has no Fable access. Override with BLUE_TEAM_MODEL
# or --model.
BLUE_TEAM_MODEL = os.environ.get("BLUE_TEAM_MODEL", "anthropic/claude-opus-4-8")


def report_name(sample: int, samples: int) -> str:
    """``blue_team_report.md`` for a single sample, ``..._NN.md`` for several."""
    return (
        "blue_team_report.md" if samples == 1 else f"blue_team_report_{sample:02d}.md"
    )


def session_name(sample: int, samples: int) -> str:
    return "blue_team.jsonl" if samples == 1 else f"blue_team_{sample:02d}.jsonl"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "run_dir", help="Path to a run/project dir (must contain .pi_transcripts/)."
    )
    ap.add_argument("--model", default=BLUE_TEAM_MODEL, help="Blue-team auditor model.")
    ap.add_argument("--thinking", default=audit_agent.THINKING_DEFAULT)
    ap.add_argument(
        "--samples",
        type=int,
        default=1,
        help="Number of independent auditors to run over this run (default: 1).",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=audit_agent.DEFAULT_TIMEOUT,
        help="Max seconds for each agent turn (default: no timeout — run to completion).",
    )
    ap.add_argument(
        "--keep-work",
        action="store_true",
        help="Don't delete the agent's throwaway work dir.",
    )
    ap.add_argument(
        "--out-dir",
        default=None,
        help="Where to write the reports "
        "(default: outputs/08_automated_blue_teaming/<run-name>/).",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        raise SystemExit(f"Not a directory: {run_dir}")
    if not audit_agent.is_run_dir(run_dir):
        raise SystemExit(
            f"{run_dir} is not a run/project dir (no .pi_transcripts/ found).\n"
            "Pass a run dir, e.g. outputs/03_run_agents/<proposal>_<mode>."
        )
    samples = max(1, args.samples)

    work = Path(tempfile.mkdtemp(prefix="blue_team_"))
    timeout = f"{args.timeout}s" if args.timeout else "none"
    print(
        f"Run dir:  {run_dir}\n"
        f"Work dir: {work}\n"
        f"Model: {args.model} | thinking: {args.thinking} | timeout: {timeout} | "
        f"samples: {samples}",
        flush=True,
    )

    audit_agent.stage_reference_docs(work, run_dir)
    out = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else ROOT / "outputs" / "08_automated_blue_teaming" / run_dir.name
    )
    out.mkdir(parents=True, exist_ok=True)

    produced: list[str] = []
    for i in range(1, samples + 1):
        report_file = report_name(i, samples)
        session = session_name(i, samples)
        print(
            f"--- auditor {i}/{samples}: hunting for sabotage "
            f"(this can take many minutes) -> {report_file} ---",
            flush=True,
        )
        res = audit_agent.run_pi(
            run_dir,
            work,
            blue_team.build_prompt(stream=False, report_file=report_file),
            session=session,
            log_name=f"agent_stdout_{Path(session).stem}.log",
            model=args.model,
            thinking=args.thinking,
            timeout=args.timeout,
            on_log=lambda m: print(m, flush=True),
        )
        report_path = work / report_file
        if not report_path.exists():
            print(
                f"  WARNING: auditor {i} produced no {report_file} "
                f"(rc={res['returncode']} timed_out={res['timed_out']}); "
                f"see {work}/agent_stdout_{Path(session).stem}.log",
                flush=True,
            )
            continue
        shutil.copyfile(report_path, out / report_file)
        if Path(res["session"]).exists():
            sess_out = (
                "blue_team_agent_session.jsonl"
                if samples == 1
                else f"blue_team_agent_session_{i:02d}.jsonl"
            )
            shutil.copyfile(res["session"], out / sess_out)
        produced.append(report_file)

    print("--- done ---")
    if not produced:
        print(
            f"FAILED: no blue-team reports produced.\n"
            f"Agent stdout logs: {work}/agent_stdout_*.log"
        )
        raise SystemExit(1)
    print(f"Reports: {out} ({len(produced)}/{samples}: {', '.join(produced)})")
    print(f"Agent trajectories (for audit): {out}/blue_team_agent_session*.jsonl")
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
