# Studio writeup reliability — the assurance case

Goal: **a writeup run never fails for an infrastructure reason** (server
restart/crash, a stray kill, a transient API error). The only way a run ends
without a writeup is a *genuine, terminal* reason — the model refused, or a step
errored every retry — and when that happens it is surfaced with a reason, not a
silent blank.

This applies to the **writeup studio** and the **proposal studio**: both run on
the shared `DocAgentSession` engine, so the fix covers both. (The **blue-team /
Run-Lens** audits run on a *different* path — `agent_viewer`'s lens machinery —
and still have the old coupling; see "Not yet covered" below.)

## Root cause that was fixed

Drafts used to be launched as direct children of the web server, with the bwrap
sandbox flagged `--die-with-parent`. `PR_SET_PDEATHSIG` then SIGKILLs the agent
(`rc=-9`) the instant the server process exits — so **every viewer restart
(deploying a change) silently killed all in-flight writeups**. `start_new_session`
did not help: it detaches the process *group*, not the parent for pdeathsig.
(Confirmed live with kernel ftrace; not OOM — cgroup `oom_kill` was 0 throughout.)

## Architecture (decoupled, durable, resumable)

```
viewer (restartable, stateless about jobs)
  └─ launches a detached supervisor  (src/studio_job.py, start_new_session, NOT die-with-parent)
        └─ pi turn in bwrap          (--die-with-parent to the SUPERVISOR, not the viewer)
durable state, all on disk in the workspace:
  turn_status.json   running -> completed | failed(terminal) | stopped(terminal)
                     + steps, step_index, attempts, pid, heartbeat, relaunches, reason
  job_spec.json      {module, cls, kwargs} to rebuild the session for --resume
  session.jsonl      the pi conversation (the resume point)
  .batch.json        the "Write all" member set (the batch survives restarts)
```

The viewer only *observes* (reads status + a `/proc` liveness scan) and
*controls* (start / stop / resume). A reconcile pump (`_reconcile`, every 3s)
re-derives running/queued from disk, **resumes** any turn whose supervisor died
(bounded by `STUDIO_MAX_RELAUNCH`), and **starts** queued batch members up to
`STUDIO_DRAFT_CONCURRENCY`. Because it is stateless beyond on-disk state, it
behaves identically whether the server has been up for days or for ten seconds
after a restart.

## Failure mode → mitigation → test

| Failure mode | Mitigation | Proven by |
|---|---|---|
| Viewer restart / crash mid-draft | Supervisor is detached (own session, not die-with-parent); reparents to init and keeps running; new viewer re-adopts off disk | `studio_chaos.py::scenario_detach`; **live**: restart server mid-draft → supervisor + sandboxes survive, draft advanced `/draft`→`/compose` across the restart |
| Supervisor killed / crashes | Status stays non-terminal → pump relaunches `--resume`, continuing from the last step | `scenario_crash_resume` |
| Transient API error / killed turn | Bounded per-step retry with backoff (`STUDIO_STEP_ATTEMPTS`) inside the supervisor | `scenario_crash_resume` (transient rc); retry loop in `studio_job.run` |
| Deliberate stop (Stop all / Delete all) | Recorded as terminal `stopped`; pump does **not** resume it; UI shows it as stopped, not a crash | `scenario_stop` |
| Model refusal / repeated error | Terminal `failed` with `reason` + `error` surfaced (not a silent blank, not retried forever) | `scenario_refusal` |
| Batch lost on restart | Member set persisted to `.batch.json`; pump re-derives and keeps draining | durable `_load_members` / `_reconcile`; covered by the live restart |

Run the harness (model-free, ~1 min):

```bash
python -m tests.studio_chaos      # exits non-zero on any failure
```

## Tunables (env)

- `STUDIO_DRAFT_CONCURRENCY` (default 5) — max writeups in flight at once.
- `STUDIO_STEP_ATTEMPTS` (default 3) — per-step retries inside a supervisor.
- `STUDIO_MAX_RELAUNCH` (default 8) — pump relaunches of a crashed turn before giving up.

## Not yet covered

The **blue-team / Run-Lens** audits share the *same* root-cause pattern
(server-parented bwrap with `--die-with-parent`, in `agent_viewer`'s lens launch
sites) but a *different* code path, so this change does not fix them. Applying the
same decoupling there (route lens/audit launches through a detached supervisor +
durable status) is the follow-up.
