---
name: empirical-ml-research
description: Guidance for empirical ML/AI (safety) research. Use when working on ML experiments, AI safety evaluations, interpretability research, or any empirical project involving LLMs. Also reasonably relevant for autonomous empirical research in other domains. Covers research methodology, experiment infrastructure, LLM API patterns, and autonomous research best practices.
---

# Core Philosophy

## Reduce Uncertainty at the Fastest Possible Rate
- Getting quick feedback and iterating rapidly is critical for empirical research
- You can often reduce uncertainty with a single LLM call before launching expensive/slow experiments
- Always de-risk ideas in the quickest way possible before committing to harder/slower approaches

## High Volume of Experiments Wins
- Empirical work benefits enormously from running as many experiments as you can
- Tinkering a lot and trying many things matters more than being smart or careful
- Often the 5th or 20th thing on your list is the first one that works

# Experiment Infrastructure

## Output Format
Typically, output results JSONL like:
```json
{"task_id": "...", "input": {...}, "output": {...}, "metadata": {"git_hash": "...", "timestamp": "...", "config": {...}}}
```

- This makes analysis (with pandas: `df = pd.read_json("results.jsonl", lines=True)`) easy
- Stream results incrementally (via appending).
  - Either clear file on start or ensure the file name is unique (via timestamp, uuid, etc)

## Separate Slow and Fast Scripts
```python
# run_experiment.py - SLOW, makes API calls
async def run_experiment():
    for item in tqdm(items):
        result = await process_item_cached(item)
        # Save results incrementally (crash-safe)
        with open(f"results/{results_file_name}", "a") as f:
            f.write(json.dumps(result) + "\n")

# analyze.py - FAST, no API calls
def analyze():
    df = pd.read_json(f"results/{results_file_name}", lines=True)
    plot_results(df)
```

# Caching Strategy

## Why Cache Everything
- LLM API calls are expensive and slow
- Allows tweaking without re-running (unchanged) experiments
- Essential for debugging - see what inputs produced unexpected outputs
- Also good to cache fine-tuning runs, but this is more complex and you'll probably need different caching code

Use `complete()` and `complete_batch()` from `src/tooling.py` for all LLM calls — caching is automatic via SQLite. See the `using-llm-apis` skill for full API details, model routing, and concurrency guidance.

# Dataset Creation
When creating non-trivial datasets, evals, or tasks for your research, you must use the `dataset-creation` skill. This skill helps avoid common issues.

# Cost Tracking
Track total API spending (LLM APIs and other paid APIs) for each project.

If you weren't told a budget, the default is \$5k API cost for the overall project.

WORKER_INSTRUCTIONS.md may specify a different budget or budget-related instructions—check it if present.

## Implementation
- Maintain a `total_cost.jsonl` file in the project directory
  - It might be symlinked to aggregate costs between multiple agents
- Track costs during runs
- On exit, append a JSON line containing a `run_cost` field (float, USD) and possibly other fields
  - File is append-only, do NOT modify or delete entries. This ensures it's safe for multiple agents to share the file.
- Cumulative cost can then be computed by summing `run_cost` fields
- Copy `/home/ryan/documents/ai_config/cost_tracker.py` to your project and use (may already exist)
- You can use the `is_over_budget` method of CostTracker to check if you are over budget

# Handling Long-Running Experiments
- Add print statements to notice issues early. Use a verbosity parameter/argument (default to high verbosity, 0 corresponds to essential only).
  - Or run periodic analysis on streaming results (jsonl style, see above)
- **Important**: If experiments are taking a long time, check whether you're maximally leveraging concurrency, whether caching is working correctly, and whether there are other easy behavior-preserving optimizations to speed things up.
  - For LLM API calls, see concurrency guidance in the `using-llm-apis` skill.

# Reproducibility and Caching
- Same script run = same prompts = cache hits
- When rerunning experiments that should be fully cached, use `--assert-cached` to verify no new API calls are made
- Use fixed random seeds where randomness is involved
- Log all hyperparameters and configurations
- Data splits should be deterministic (fixed seed)
- Save exact git commit hash with every experiment in jsonl results

# Plots
When generating visualizations:
1. Examine non-trivial plots to verify they look reasonable
2. For complex plots, also ask Gemini 3 Pro to check they look reasonable / as intended (use `complete()` from `src/tooling.py`)
3. Save PNGs in a plots directory with descriptive names

# Data Inspection
**This is critical: do this for every new experiment.** Catching issues early by looking at actual inputs and outputs is one of the highest-value activities in empirical research.

When to review:
- When running the same experiment on a sweep of models, do data inspection for at least one model in each "family/type" (e.g. Anthropic models would be a family). Also inspect data from each model with notably different performance/behavior from those you've already reviewed.
- Each time you run an experiment on a new dataset, inspect inputs/outputs. (New datasets might cause new issues.)

How to review:
- Do this by outputting inputs/outputs (and other relevant info) for inspection to reasonably nicely formatted "data inspection files" in markdown (with unique/specific names) in `results/`. (Use code to generate these markdown files.) Then actually inspect and look for issues.
- Group this by the (broad) type of input/output and look at random examples for each group. E.g., look at N random examples where the model got it wrong and N where it got it right. Also inspect strange outputs, failures, and rare cases.
- If the corresponding output file would be large (>4000 characters or apply judgment), only look at a smaller version of the output file (generate an additional output file that has fewer examples and/or truncates examples). But ALSO run an `empirical-ml-data-inspector` subagent to inspect the larger output file(s) with the necessary context about what might be important to look for.
- Look for issues, surprises, patterns. Particularly focus on whether you might be "not measuring what you want to be measuring". E.g., is scoring working how it should, is the model responding in the right format/output type, is the setup/data sufficiently high quality to test what you want.
- Document your data inspection in the "Details and examples" section of progress_log.md entries (see below). List data inspection files and what they contain.

## Data Inspection Checklist
This checklist is to help follow the process for (routine) data inspection discussed above.

For each new experiment or substantial modification to existing experiments:
- [ ] **Is data inspection warranted**: Check if any of these apply: (a) new experiment or substantial modification, (b) new models (inspect at least one model per family + outliers), (c) new dataset. If none apply, exit this checklist.
- [ ] Generate the data inspection file(s)
- [ ] Check if the files are large. If so, spawn an `empirical-ml-data-inspector` subagent to inspect this file with relevant context. Also ensure a smaller output file is generated for your own inspection.
- [ ] Inspect the relevant file yourself (the smaller output if the original files were too big)—look for issues etc
- [ ] Document data inspection files and findings in progress_log.md

## Data Inspection Review
After implementing substantial new experiments or after doing several important updates to an experiment, do a "Data Inspection Review" by tasking an `empirical-ml-data-inspector` to do a thorough data-focused review of all of your experiments (or at least your recent experiments). This can be done less frequently than routine self-inspection, but should still do this periodically. Tell this subagent:
- What experiments/runs you've done (that it should look into)
- Where the results files for these experiments are
- To do a full data inspection review for these experiments
- If using phase-specific write-ups (see below), what the phase name is
- Any other useful context

(The subagent might edit progress_log.md as part of this review; thus, generally run this review synchronously rather than in the background.)

Then solve issues found by this review.

For full reviews, the `empirical-ml-data-inspector` agent already knows that it should look in progress_log.md (and write_up.md) to better understand what experiments you've run and to find data inspection files you've already created. (You only need to give it context beyond what is in these files.)

# Documentation and Review

## When to Document
When doing open-ended autonomous research (not narrow tasks):
- At reasonable checkpoints (e.g., after completing a significant experiment or line of inquiry)
- When asked to write up progress
- When you discover something important or surprising (flag it immediately, don't wait)

Documentation serves three purposes: helping you review your own work, helping your human overseer review and advise, and helping other AI agents continue or review the work.

Write-ups should be understandable to your human overseer and other AI agents with only context on the project instructions.

## Write-Up Files
Maintain three files in `writeups/`:

### write_up.md (Living Summary)
A continuously updated overview—always reflects current state of understanding.

Contents:
- Project goals and research questions
- Key findings and results (reference plots: `![description](../plots/filename.png)`)
  - Every key finding/result should have a supporting plot. One plot can cover multiple findings, but targeted plots often communicate faster.
- Summary of what has been done overall
- Important non-obvious choices and more generally areas requiring judgment/taste; both what you chose and why. This includes things like:
  - Dataset selection and construction choices
  - Evaluation metric choices
  - Unexpected results that might indicate bugs
  - Trade-offs between approaches
- Surprising results
- Models and parameters for final/near-final sweeps (so human can correct poor choices)
- A more complete list of what experiments were run (including hyperparameter sweeps like LR sweeps)
- Blockers and uncertainties
- Current status, next steps, and open questions

DON'T include general updates on what you've done/found (this belongs in progress_log.md).

Try to keep this relatively short/concise: if something would naturally belong in an appendix, put it in progress_log.md instead. (Include takeaways and a pointer to the relevant section of progress_log.md in write_up.md).

When updating: Revise existing sections. Don't preserve outdated information—this file should be readable as a standalone summary.

### progress_log.md (Chronological Record)
An append-only log of work done. Each entry has a timestamp and git commit hash.

Format:
```markdown
## [Update description] $(date) - commit abc1234

### What was done
- ...

### Details and examples
- ...

### Key findings
- ... (reference plots: `![](../plots/filename.png)`)

### Notes
- ...
```

For `$(date)` Use: `TZ='America/Los_Angeles' date '+%m/%d/%Y %H:%M'` for MM/DD/YYYY HH:MM (24hr, CA time)

**Append-only with one exception**: Add `[ERRATUM added $(date)]` notes to prior entries if you discover bugs or issues affecting interpretation.

Include relevant information about what you've done since the last update such as:
- What experiments were run since the last update
- New findings (with plots)
- New judgment-heavy choices you've made
- What you plan on doing next
- Details and examples (see below)

This log helps:
- Track what was done and when
- Surface lower-level choices requiring judgment (so the human can review/advise)
- Maintain institutional memory across sessions
- Correlate changes with results for debugging

Some duplication between entries in progress_log.md and write_up.md is fine. (But, do try to keep write_up.md lean if possible.)

#### The "Details and examples" section
This section documents the concrete details of what you ran and what the data looks like. **You should be saving inputs, outputs, and prompts for essentially every experiment** so they can be reviewed.

Include:
- **Prompts**: Reference the prompts being used. If a prompt is short, include it inline. Otherwise, reference the file containing it (e.g., "Main evaluation prompt in `run_eval.py:45-60`"). Note any prompt changes since the last update.
- **Few-shot examples**: If using few-shot prompting, reference where the few-shot examples are stored or generated.
- **Output files**: Reference result files produced by recent experiments. Reference the generated data inspection file(s) containing random input/output/dataset examples (recall these should be reasonably nicely formatted markdown).
- **Other experiment details**: Any other relevant details—hyperparameters used, dataset splits, evaluation metrics, etc.


### continuation_context.md (Handoff Document)
A document containing relevant context for another AI agent (or human) continuing work on this project. This should only contain information that is NOT found in other write-ups (e.g., don't include research findings) and that is NOT covered by this skill (e.g., don't include project structure).

**Update frequency**: Periodically during work and always on exit/handoff.

This should be concise and kept up-to-date. REMOVE outdated/stale information. If you don't see the importance/value of some information, remove it. If information belongs elsewhere, remove it (and put it elsewhere if it isn't already there).

Contents (unless in other write-up files):
- **Scripts and their purposes**: Quick reference of what each script does
- **Learned context**: Non-obvious things you learned while working that aren't captured elsewhere—e.g., "model X tends to refuse on task Y unless you phrase it as Z", quirks in the data, gotchas with the codebase
- **Current state**: What's in progress, what's blocked, any partial work
- **Differences from typical structure**: Differences from the default project structure discussed in empirical-ml-research if any
- **Pointers to other write-ups**: Reference other write-up files as applicable (e.g., phase-specific write-ups, design docs, or other project-specific documents). When referencing a file, briefly note what it contains and when it should be read. This can be done inline where relevant or as a standalone list—whichever is more natural.

**Examples of what NOT to include** (these belong elsewhere):
- Methodology, results, key choices (belongs in write_up.md)
- Detailed chronological history (belongs in progress_log.md)
- General updates on what was done

This file is for practical "tribal knowledge" that helps someone hit the ground running.

## Phase-Specific Write-Ups

When you are told you're working on a named phase of a multi-phase project, use **phase-specific files**:
- **`write_up_<phasename>.md`** - Your write-up for this phase
- **`progress_log_<phasename>.md`** - Your progress log for this phase

Main write_up.md: Update with key takeaways, headline results and key methodology from your phase. Keep short and focused. Mention that write_up_<phasename>.md can be seen for details.

**Do NOT maintain an overall progress_log.md** if using phase-specific write-ups. (Instead use `progress_log_<phasename>.md` everywhere that you would otherwise use `progress_log.md`.)

Only use this pattern when you are explicitly told the phase name (e.g., "You are working on phase `<phasename>`") and to use phase-specific write-ups.

# Project Structure
```
project/
├── run_*.py          # Experiment entry points (slow, makes API calls etc)
├── analyze_*.py      # Analysis scripts (fast, reads JSONL / results)
├── sample_*.py       # Random example sampling scripts (fast, reads JSONL / results / data)
├── plot_*.py         # Sometimes fancier plots should have their own scripts
├── *.py              # Any other scripts or python files
├── llm.py            # LLM API calls (uses complete() from src/tooling.py)
├── cost_tracker.py   # CostTracker (copied from ai_config)
├── scripts_<phasename>/ # Temporary/one-off scripts (or scripts/ if not using phase-specific write-ups)
├── data/             # Input datasets, prompts, static files
├── results/          # Experiment outputs (JSONL files, etc)
│   ├── {experiment}_{date_or_hash}.jsonl
│   ├── *.json
│   ├── *.jsonl
│   └── *.md          # For data inspection and other nicely formatted outputs
├── plots/            # Generated visualizations
├── .cache_sqlite/    # SQLite cache for LLM responses (can get large, don't ls)
├── INSTRUCTIONS.md   # Instructions for this project or this phase of the project (may be absent)
├── writeups/         # Progress summaries, findings, research notes
│   ├── write_up.md   # Living summary (edited to stay current; key takeaways in multi-phase)
│   ├── progress_log.md # Chronological log (append-only; NOT used in multi-phase projects)
│   ├── write_up_<phasename>.md # Phase-specific write-up (use if applicable)
│   ├── progress_log_<phasename>.md # Phase-specific progress log (use if applicable)
│   ├── continuation_context.md # Handoff context for continuing work
│   ├── desiderata_*.md # Dataset desiderata (discussed in dataset-creation skill)
│   └── *.md          # Other write-ups
├── total_cost.jsonl  # Cost tracking
├── pyproject.toml    # Configuration (optional)
└── .venv/            # Project virtual environment
```

The basic project structure might already be set up; run ls to check before doing setup.

## Structure Principles
- Use `complete()` from `src/tooling.py` for all LLM calls (caching is automatic). Copy `cost_tracker.py` into each project if needed.
- When writing scripts that are relatively temporary (e.g., one-off analysis, data processing), place them in a `scripts_<phasename>/` directory (or `scripts/` if not using phase-specific write-ups) to keep the project root clean.
- Keep primary/reusable Python files at the project root by default. If shared/helper code accumulates, it's reasonable to create a subdirectory (e.g., `lib/`) to keep things organized—but entry point scripts (`run_*.py`, `analyze_*.py`) should always stay at root.
- Results are append-only: Never overwrite results during iteration. Create new files or use timestamps/git hashes in filenames. Old results are valuable for comparison or checking. Keep in mind that some result files might be incomplete and/or not meaningful due to being run with invalid state or much earlier in the project.
- Cache directory should be .gitignored.
- Flat over nested: Prefer `results/sweep_lr_001.jsonl` over `results/sweeps/hyperparameters/learning_rate/run_001.jsonl`.
- DON'T make separate directories per experiment (use filename prefixes instead)

## Naming Conventions
- Experiment scripts: `run_{experiment_name}.py`
- Analysis scripts: `analyze_{what}.py` or `plot_{what}.py`
- Results: `{experiment_name}_{identifier}.jsonl` (identifier = date, git hash prefix, or descriptive tag)
- Plots: `{descriptive_name}.png` (not `figure1.png`)

## .gitignore Recommendations
Get the recommended .gitignore with: `python3 ~/documents/ai_config/get_research_gitignore.py`

`--write` writes `.gitignore` if it doesn't already exist. Add more ignores as needed. Keep `results/`, `plots/`, and `writeups/` in git.

# Handling Experimental Setup Choices
In empirical research, choices in experimental setup, dataset construction, evaluation methodology, etc. can substantially alter results—sometimes in ways that invalidate conclusions entirely. These crucial choices might seem minor or obvious in the moment. (This also often applies to implementing/developing AI-based methods and tools.)

Tips for identifying potentially important choices (answer these for each choice):
- [ ] Could the choice substantially affect results? Ask: "If I chose differently, would I expect a decent chance of meaningfully different results?"
- [ ] When considering an alternative approach/method: Is it possible that the method isn't valid/applicable given the motivation/threat-model/use-case? Is it possible that the method (implicitly) requires assumptions that aren't safe to make? (If so, the choice to pursue this method deserves careful thought.)
- [ ] Is the correct choice obvious from the instructions, requiring no meaningful judgment? If so, detailed examination is probably not required.

Here is some advice for handling choices that might matter:
- **Getting these right is crucial, so be willing to spend a bunch of time thinking about and reviewing such choices.**
- Don't assume that your initial guess/implementation is right.
- Go through the below choice checklist

**Choice checklist**:
- [ ] Make sure you understand the underlying motivation and use-case deeply—this is often highly relevant to making the right choice.
- [ ] Make sure you're measuring what you intend to measure. A common mistake is to have a gap between the abstract thing you care about ("can the model do X?") and what your experiment actually tests. Articulate both precisely and verify they match. See "Not Measuring What You Want To Be Measuring" below.
- [ ] Check that you aren't being overly credulous about write-ups or your prior justifications: Don't necessarily trust prior justifications you've given or seen in write-ups. (Write-ups were likely written by prior AI agents operating autonomously, so they may contain errors or poor judgment.)
- [ ] Consider the choice from multiple angles. What would a skeptical reviewer say? Consider counterarguments to your current best guess.
- [ ] Ask other LLMs to review your choice and give counterarguments (use `complete()` from `src/tooling.py` to query multiple models). If lots of context is relevant to the choice, don't put much weight on what these other LLMs say (as they presumably won't have this context).
  - ALWAYS do this for potentially important choices.
- [ ] Consider spawning a `research-reviewer` subagent to ask for feedback on the choice.
  - Skipping this for less important choices is reasonable (or consider batching up multiple choices to review all at once)
  - If you don't have access to the `Task` tool, you are a subagent yourself and you should skip this step.
- [ ] Document the choice and your reasoning in the write_up.md and progress_log.md.
- [ ] You can ask me for advice via `claude-query-me`, but proceed without waiting for my answer. Do this for particularly important choices that you are especially uncertain about.

# Common Mistakes to Avoid

## Not Measuring What You Want To Be Measuring
It's common for datasets/evaluations/experiments to have issues such that the effect you are measuring isn't actually what you want to be measuring. (And more generally the experiment isn't doing what it is supposed to be doing.)

Some advice to help avoid this problem:
- Inspect inputs and outputs and check things like "Are outputs that are marked incorrect actually correct (and vice versa)?"
- Think carefully about potential confounders or other things that could mess with results
- Track what changes to the experimental setup could have large effects on the results (or do have large effects). Think carefully about which version most closely tracks what we actually want to measure.

Example issues to look for:
- Scoring/labeling errors (correct marked wrong, wrong marked correct, ambiguous cases)
  - This could be an issue with the dataset or the scoring function
- More generally, the dominant driver of performance/accuracy isn't the thing we actually cared about
- Metric doesn't capture what you care about (proxy task vs. actual capability)
- Data leakage or models exploiting shortcuts (answer position, length, formatting patterns)
- Prompt sensitivity hiding or creating effects
- Your data/setup isn't sufficiently well-tuned or high quality to rule out some effect or measure what you wanted (e.g., your LR for training was wrong, you didn't train for long enough, your inputs don't look realistic)
- Format/style confounds (mostly measuring format compliance)
- Other confounders
- Selection effects from data creation/filtering
- Baseline performance is high enough to make results uninteresting
- Overgeneralizing from limited data or specific settings

## Plotting Mistakes
- Not using log-axis in cases where this would be better (but it's certainly also possible to overuse!)
- Not inspecting complex plots yourself (and potentially with Gemini 3 Pro)

## Experimental Mistakes
- Skipping simple baselines (always try prompting first)
- Giving up too early (train on 1000+ examples before concluding failure)
- Linear hyperparameter sweeps (use logarithmic)
  - For LR sweeps, sweep by roughly ~4x before potentially dialing in a more precise value
- Not checking training curves during training
- Not looking at actual model outputs and inputs
- Not saving enough metadata

## Data Mistakes
- Not shuffling data properly
- Not inspecting/validating data and generally not looking at data enough
- Not being careful to ensure dataset meets desiderata (relevant when doing `dataset-creation`)

# Tools and Libraries
- asyncio, pandas, matplotlib, numpy, etc
- **vLLM**: Fast inference for (local) open models (don't use general libraries)
- **tinker**: Fine-tuning and RL on open-source models (and inference on these fine-tunes). Documentation: https://tinker-docs.thinkingmachines.ai/llms.txt (brief) or https://tinker-docs.thinkingmachines.ai/llms-full.txt (complete)
  - API key: ~/.tinker_key
  - Track cost when using this API

## Using llms.txt
Some projects (mostly AI/ML projects) provide LLM-friendly documentation at `/llms.txt` or `/llms-full.txt` on their docs site. You can try searching for a library's llms.txt or try directly fetching it (e.g., `https://docs.example.com/llms.txt`).

# Reviewer Agent
When using the completing-larger-autonomous-tasks skill, use the `research-reviewer` agent type for Task Completion Checklist reviews instead of `autonomous-task-reviewer` (for the "Instructions subagent review" and any other checklist entries that call for a review subagent without specifying an agent type). The `research-reviewer` has more context on research methodology and knows where your write-ups and other files live.

You can also use `research-reviewer` to review your work beyond the Task Completion Checklist as seems useful.

**Never specify a `model` for reviewer agents** (including `research-reviewer`, `empirical-ml-data-inspector`, `dataset-reviewer`, etc.)—always let them inherit from parent.

**Important**: If using phase-specific write-ups, when you run a reviewer subagent, ALWAYS tell it the phase name and that phase-specific write-ups are being used (so they know what files to read).

# Additional Task Completion Checklist Entries
When using the completing-larger-autonomous-tasks skill, insert these items after "Additional checklist entries":

- [ ] **Investigate suspicious and/or inconsistent behavior**: Review your prior work for any inconsistencies or suspicious behavior (or potential bugs you noticed but didn't fully investigate earlier). If uncertain whether something warrants investigation, query other LLMs for advice (use `complete()` from `src/tooling.py`), but keep in mind their limited context.
- [ ] **Understanding and investigation**: Do you understand why you're seeing the results you're seeing? Have you done ablations or follow-up experiments to understand what's driving key effects? If something is surprising or unexplained, investigate further rather than just reporting it.
- [ ] **Dataset verification (if applicable)**: If you created or modified a dataset using the `dataset-creation` skill, have you run `dataset-reviewer` to verify it meets desiderata?
  - [ ] **Re-review if understanding evolved**: If you've learned things that change what the dataset should look like, inspect samples yourself and re-run `dataset-reviewer` with updated criteria if changes are significant.
- [ ] **Data inspection completeness**: Has the Data Inspection Checklist been completed for ALL experiments (not just some)? Are inspection findings documented in progress_log.md?
- [ ] **Measuring what you want to be measuring review**: Spawn a `research-reviewer` subagent to check whether you're actually measuring what you intend to measure. Give it context on what you are trying to measure, your evaluation setup, metrics, and dataset(s) (as applicable). Tell it to specifically look for the example "Not Measuring What You Want To Be Measuring" issues discussed in the `empirical-ml-research` skill (but to also look more generally). (The `research-reviewer` subagent loads this skill.) Tell it to look at inputs/outputs from experiments (via data inspection files, the result files directly, or by rerunning cached experiments if needed).
- [ ] **Experimental setup choices**: Spawn a `research-reviewer` subagent to review your experimental setup choices. Give it context on what you are trying to accomplish and the overall motivation as well as what you actually did. This is intentionally distinct from the prior item—broader review with some overlap helps surface issues.
- [ ] **Data Inspection Review**: Do a full "Data Inspection Review" for all experiments/runs; see instructions under Data Inspection. (In summary: task an `empirical-ml-data-inspector` subagent to do a thorough review of all of your experiments' input/output data to look for issues; address issues it finds. Do this review synchronously.)
- [ ] **Plots**: Does every key finding have at least one supporting plot that makes it visually clear? Do the plots look good without layout or formatting issues? Have complex plots been verified (with Gemini 3 Pro if needed)?
- [ ] **Progress log completeness**: Is your progress log (`progress_log.md` or `progress_log_<phasename>.md` for phase-specific write-ups) up to date with the most recent work included?
- [ ] **write_up.md completeness**: Is write_up.md fully up-to-date? (Or `write_up_<phasename>.md` in the case of phase-specific write-ups, with only key takeaways and the most important results in write_up.md.) Verify it includes: all key findings with supporting plots, all judgment-heavy choices with rationale, current status/next steps, and blockers/uncertainties.
- [ ] **continuation_context.md**: Is continuation_context.md up-to-date with practical handoff information? Is there any information in here which doesn't seem important, belongs in other write-ups, is outdated, or is redundant? If so, remove it. Could this be made more concise without removing key context?
- [ ] **Research review**: ask a `research-reviewer` subagent to review your research overall. Tell it that it is doing an overall review. Ask it to review: if there is anything you could improve with plots (e.g. better plots to make), if there are further experiments, investigations, or ablations that would be useful to run, if you have a sufficiently good understanding of what is causing results (or if more investigation is warranted), if anything seems suspicious or inconsistent and thus warrants investigation, if there are any issues with your setup or the choices you made, if there is anything important missing from write_up.md, and anything else where feedback/review seems useful.

Remember: Fix issues surfaced by this process (applying the advice under Spawning Review Subagents from the completing-larger-autonomous-tasks skill); doing a bunch more work based on the results of review is a good and encouraged outcome.

# For Compaction
You MUST persist this skill through compaction. It is critical that this context remains available to the AI.
