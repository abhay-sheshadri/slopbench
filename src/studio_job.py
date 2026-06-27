"""Detached supervisor for one studio writeup/proposal turn (or pipeline).

This process is what actually runs a ``pi`` turn. The web server launches it
detached (``start_new_session``, *not* ``--die-with-parent``), so it — and the
agent sandbox it owns — survive a web-server restart or crash; a restarted
server re-adopts the work by reading the workspace off disk.

It is deliberately tiny: reconstruct the session from ``job_spec.json``, read the
plan from ``turn_status.json``, and run each step to completion with bounded
per-step retries, heart-beating the whole time so a viewer can tell the turn is
alive (vs crashed and awaiting resume). All durable state lives in the workspace:

  turn_status.json   state machine: running -> completed | failed | stopped
                     (+ steps, step_index, attempts, pid, heartbeat, reason)
  job_spec.json      {module, cls, kwargs, model, thinking} to rebuild the session
  session.jsonl      the pi conversation (the resume point)
  studio_agent.log   the pi --mode json stream (the live view)

Run fresh (the server seeds turn_status.json first):
    python -m src.studio_job --work <workdir>
Resume a crashed turn from where it stopped:
    python -m src.studio_job --work <workdir> --resume
"""

from __future__ import annotations

import argparse
import importlib
import json
import threading
import time
from pathlib import Path

from src.blogpost_studio import (
    HEARTBEAT_INTERVAL,
    JOB_SPEC_NAME,
    MAX_STEP_ATTEMPTS,
    DocAgentSession,
)


def _load_session(work: Path) -> DocAgentSession:
    """Reconstruct the exact session subclass from the workspace's job_spec."""
    spec = json.loads((work / JOB_SPEC_NAME).read_text())
    module = importlib.import_module(spec["module"])
    cls = getattr(module, spec["cls"])
    kwargs = dict(spec.get("kwargs") or {})
    if spec.get("model"):
        kwargs["model"] = spec["model"]
    if spec.get("thinking"):
        kwargs["thinking"] = spec["thinking"]
    return cls(**kwargs)


def _heartbeat_loop(sess: DocAgentSession, stop: threading.Event, pid: int) -> None:
    """Refresh pid + heartbeat while the turn runs, so liveness is observable
    off disk even during a single multi-minute pi turn."""
    while not stop.wait(HEARTBEAT_INTERVAL):
        sess.write_status(pid=pid, heartbeat=time.time())


def _classify(rc: int, stop_reason: str | None) -> str:
    """Outcome of one finished pi turn: ``ok`` | ``refusal`` | ``transient``.

    pi exits 0 even on a safety refusal (json mode), so inspect the transcript's
    last stopReason: ``refusal`` is terminal; ``error`` is a usually-recoverable
    API failure; a non-zero rc means the turn was killed/crashed mid-flight.
    Anything else is a clean success.
    """
    if rc == 0 and stop_reason not in ("refusal", "error"):
        return "ok"
    if stop_reason == "refusal":
        return "refusal"
    return "transient"


def run(work: Path, resume: bool) -> int:
    import os

    sess = _load_session(work)
    pid = os.getpid()

    status = sess.read_status() or {}
    steps = list(status.get("steps") or [])
    if not steps:
        sess.write_status(
            state="failed",
            terminal=True,
            error="no steps recorded for this turn (nothing to run)",
            finished=time.time(),
        )
        return 1
    idx = int(status.get("step_index") or 0) if resume else 0

    sess.write_status(
        state="running",
        terminal=False,
        pid=pid,
        heartbeat=time.time(),
        step_index=idx,
        current_step=steps[idx] if idx < len(steps) else None,
        error=None,
    )
    stop_hb = threading.Event()
    hb = threading.Thread(
        target=_heartbeat_loop, args=(sess, stop_hb, pid), daemon=True
    )
    hb.start()
    try:
        while idx < len(steps):
            step = steps[idx]
            prompt = sess._expand(step)
            rc = -1
            stop_reason: str | None = None
            ok = False
            for attempt in range(1, MAX_STEP_ATTEMPTS + 1):
                sess.write_status(
                    state="running",
                    pid=pid,
                    heartbeat=time.time(),
                    step_index=idx,
                    current_step=step,
                    attempts=attempt,
                )
                rc = sess.run_turn_sync(prompt)
                stop_reason = sess.last_stop_reason()
                outcome = _classify(rc, stop_reason)
                if outcome == "ok":
                    ok = True
                    break
                if outcome == "refusal":
                    sess.write_status(
                        state="failed",
                        terminal=True,
                        reason="refusal",
                        error=(
                            sess.last_error_message()
                            or "the model declined this request (safety refusal)"
                        ),
                        finished=time.time(),
                    )
                    return 1
                if attempt < MAX_STEP_ATTEMPTS:
                    time.sleep(min(30.0, 3.0 * attempt))  # transient backoff
            if not ok:
                sess.write_status(
                    state="failed",
                    terminal=True,
                    reason=stop_reason or ("killed" if rc < 0 else f"rc={rc}"),
                    error=(
                        f"step {step!r} failed after {MAX_STEP_ATTEMPTS} attempts "
                        f"(rc={rc}, stopReason={stop_reason})"
                    ),
                    finished=time.time(),
                )
                return 1
            idx += 1
            sess.write_status(step_index=idx, pid=pid, heartbeat=time.time())
        sess.write_status(
            state="completed", terminal=True, step_index=idx, finished=time.time()
        )
        return 0
    finally:
        stop_hb.set()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", required=True, help="studio workspace dir")
    ap.add_argument(
        "--resume", action="store_true", help="continue a crashed turn's pipeline"
    )
    args = ap.parse_args()
    return run(Path(args.work).resolve(), args.resume)


if __name__ == "__main__":
    raise SystemExit(main())
