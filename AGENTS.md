# AGENTS.md

Orientation for agents (and humans) working in this repo. Read this before starting,
resuming, or debugging a research run.

## What this repo does

It runs autonomous research agents on written proposals and turns their work into
reviewable artifacts and blogposts. A "run" = one agent executing one proposal end to
end inside a sandbox, leaving a browsable output directory.

## Layout

```
proposals/              proposal_<name>.md — the research briefs agents execute
experiments/            numbered pipeline stages, each with its own run.py/run.sh
  03_run_agents/        the main launcher (run.sh -> run.py); see below
src/                    the library all stages import
  agent_runner.py       core: launches/​resumes runs, RunSpec, heartbeat, session fold
  sandbox.py            bwrap sandbox setup (read-only host binds + writable workspace)
  agent_viewer.py       web viewer for live/finished runs (served by ./view_agents.sh)
abhay-pi/               the `pi` agent runtime (TypeScript). MUST be built once: see below
outputs/03_run_agents/  one dir per run: <proposal>_multi_phase/
scripts/                machine setup, the abhay-pi launcher wrapper
```

## How a run works

`experiments/03_run_agents/run.sh` is the entry point. It reads a `PROJECTS` config
block, then for each project launches `run.py` in its own detached tmux session named
`agent_<project>_multi_phase`. `run.py` is a thin launcher over `src.agent_runner.run_many`.

Each run launches the `pi` agent inside a `bwrap` sandbox: the host toolchain is bound
read-only, and `outputs/03_run_agents/<proposal>_multi_phase/` is bound writable as
`/workspace`. A run is the `/run-loop` planner → worker → reviewer loop: work is split
into segments and phases, and state lives in `planner/RUN_LOOP_STATE.json`. (Run dirs keep
the historical `_multi_phase` suffix.)

Runs have **no command timeout** — they execute to completion.

### Output directory anatomy (`outputs/03_run_agents/<proposal>_multi_phase/`)

```
proposal.md                       the brief this run executes
planner/RUN_LOOP_STATE.json       AUTHORITATIVE state: status, currentSegment/Phase,
                                    stage, completed[], sub-agent session pointers
planner/OVERALL_PLAN.md, RUBRIC_* planning artifacts
phase_segment_<S>_phase_<P>/      per-phase work dirs (cloned per phase unless --single-dir)
.home/.pi/agent/sessions/         REAL sub-agent transcripts (.jsonl)
.pi_transcripts/
  heartbeat.json                  liveness ping (see gotcha below)
  RUNNING                         marker file; present only while a run is live
  manifest.json                   run metadata + final status
  run_loop_sessions/              flattened transcript export, written only on EXIT
file_cache_dir/                   regenerable LLM/compute cache (safe to delete)
```

## Starting runs

```bash
cd experiments/03_run_agents
# edit the PROJECTS block in run.sh first, then:
./run.sh                 # launch each configured project in its own tmux session
./run.sh --force         # wipe each output dir first (fresh start)
./run.sh --direct        # run in the current shell instead of tmux (debugging)
```

Prerequisite: the agent runtime must be built once after setup, or every run fails with
`ERR_MODULE_NOT_FOUND`:

```bash
cd abhay-pi && npm run build
```

## Resuming runs

A run is resumable if `planner/RUN_LOOP_STATE.json` exists. Resume relaunches
`/run-loop resume` pointed at the existing output dir — completed phases, state, and
transcripts are the source of truth and are left intact.

```bash
cd experiments/03_run_agents
./run.sh --resume        # resumes every project in the PROJECTS config block
```

To resume one specific run without touching the config block, replicate what run.sh
does for a single project:

```bash
tmux kill-session -t agent_<project>_multi_phase 2>/dev/null
tmux new-session -d -s agent_<project>_multi_phase \
  "cd $PWD/../..; source .venv/bin/activate; \
   exec python experiments/03_run_agents/run.py \
     --projects <project> \
     --thinking xhigh --model anthropic/claude-opus-4-8 --resume"
```

The resume path **automatically** calls `sanitize_run_loop_state_for_resume`: it clears
the recorded sandbox-namespaced PIDs (`parentPid`/`activeChildPid`) and flips a stale
`status: running` to `stopped`. Without this, `/run-loop resume` thinks the loop is
still running and refuses. You do **not** need to edit the state file by hand.

A resume "took" when: `RUNNING` reappears, `heartbeat.json` shows a new `host_pid` with a
fresh timestamp, state `status` is `running`, and the current worker session `.jsonl`
starts growing.

`--continue-file <path>` is different: it relaunches a *completed* run with new
instructions via `/run-loop continue`. It refuses unless the state is `complete`.

## Diagnosing a stuck run — important

**`heartbeat.json` only proves the Python wrapper is alive, not that the agent is making
progress.** `_heartbeat_loop` rewrites it every 15s with `status: "running"` regardless
of what the agent is doing. There is no inactivity watchdog. A run can be wedged for
hours while the heartbeat and dashboard still say "running".

The usual stall: the agent fired a `bash` tool call that never returns (a `grep -r /`
over the whole filesystem, a runaway CPU compute job), and — with no command timeout —
sits blocked forever. To distinguish wedged from working:

```bash
# 1. Is the agent producing artifacts, or only heartbeats?
find outputs/03_run_agents/<run>/ -type f -newermt '-15 min' ! -path '*/.pi_transcripts/*'
# 2. Latest transcript activity:
ls -t outputs/03_run_agents/<run>/.home/.pi/agent/sessions/*/*.jsonl | head -1   # check mtime
# 3. Is the inner agent busy or idle, and what is it blocked on?
pstree -p <host_pid_from_heartbeat>     # look for a long-lived bash/grep/python leaf at 0% CPU
```

If only `heartbeat.json` is updating and the agent's `node`/`bash` leaf has been idle for
hours, it's wedged. To recover: kill the run's `run.py` wrapper (the bwrap sandbox has
`--die-with-parent`, so the whole tree dies), remove the stale `RUNNING` marker, then
resume as above. Resume restarts the current phase cleanly with fresh context.

## Viewing runs

```bash
./view_agents.sh                 # local web viewer (live + finished runs)
./view_agents.sh -c              # expose via a temporary cloudflare URL
```

Reads transcripts straight off disk. For a live run it reads sessions in place from
`.home/.pi`; the flattened `run_loop_sessions/` export is only written when a run exits.

## Disk hygiene

Each phase dir can carry a large copied `.venv` (and, for training runs, forwarded
`lora_adapters/`), so output dirs grow fast. Safe to reclaim space:

- `file_cache_dir/` of any **completed** run — regenerable cache; results/transcripts
  are untouched.
- `data/lora_adapters/` in segments `<= currentSegment-1` — later segments are supersets,
  so older copies are redundant (keep the last full segment + the current one).

Check before assuming you're out of space: `df -h /` and `df -h /mnt/fast`.
