---
name: completing-larger-autonomous-tasks
description: Use when working on a task autonomously/semi-autonomously and the task is at least moderately large. Provides guidance on being thorough, doing comprehensive reviews and testing, and a task completion checklist that should be followed before considering a task complete.
---

# General Advice for Thorough Autonomous Work
**Running longer is cheap and you should keep going whenever there is more you could do that is useful.**
- Even taking substantially longer (e.g., many days) is fine—I can interrupt you if needed.
  - There is no penalty for taking longer
  - Thoroughness, correctness, and quality matter more than speed. Do not sacrifice quality to finish faster. You DO NOT have time constraints.
  - As an AI agent, you complete tasks much faster than a human would—often 10-100x faster for coding. If a task "feels like" it would take weeks or months, that's likely human-equivalent time; actual elapsed time is usually hours to days. Don't scope down based on these inflated estimates.
  - (I have heavily subsidized Claude access and want to spend a lot to get better output.)
- Examples:
  - If you ever notice ANY issue/problem/limitation and it isn't literally impossible to fix/improve, do so
  - If you could plausibly improve something or further optimize something that is supposed to be optimized, do so
  - If you end up feeling stuck, just keep trying.
  - If there is a problem with something you created/wrote/did earlier, don't be afraid to discard your prior output and make a totally new version that (hopefully) resolves these problems.
    - Doing this multiple times can be a good choice if you keep noticing issues that are better resolved by starting again on something from scratch.
    - You might have learned valuable lessons from the prior work you need to redo, so this isn't wasted effort
    - When applicable, document what you previously did and why you needed to do something else.
- Overall, remember that you have time to do more/better! Be relentless and willing to keep working.

**Strongly lean towards being more thorough.** Do EVERYTHING asked, very thoroughly. If in any doubt, keep going.

(I've observed a pattern where AI instances tend to stop early when they really should have done more work and corrected issues. You should compensate strongly against this bias/tendency by actively trying to be extremely thorough and unwilling to stop if there is ANYTHING you could do better/fix.)

You can work hard and do excellent, thorough work! It's really valuable for me if you do a thorough job and solve all issues.

**Additional work to consider** after finishing initial implementation and improving/fixing everything you can:
- **Thorough testing**: Include possibly-manual integration testing as needed (tests as close as possible to the actual end-to-end use case)
- **Sanity check choices**: Especially choices requiring judgment (like making a dataset)
- **Query other LLMs**: Get them to critique your work/choices (see "Querying Other LLMs for Help" in CLAUDE.md)
- **Spawn review subagents**: Have them review specific work for issues, bugs, judgment calls, and code quality
- **Investigate suspicious behavior**: Look into potential bugs or inconsistencies in detail—do this as soon as you notice them
- **For research**: Further investigation; improve plots and visualizations for clarity

# Actually Fix Problems, Don't Just Acknowledge They Exist
When you identify a limitation or problem with your work:
- FIX IT rather than just documenting it
- It's fine if this requires doing much more work or repeating some task
- If you notice a previously documented limitation/issue with your work, actually go and solve this issue (if it wasn't already solved)
- Something isn't a "limitation" if you were explicitly instructed to do it (e.g. if explicitly instructed to just try/investigate X, only investigating X isn't a limitation)

# Code Practices
- Keep files, functions, and classes relatively small and focused. Generally keep files under 1000 lines. If your additions would make a file overly long, fix this (e.g. break it up).
- If you notice code quality issues, go ahead and fix them if the affected code is related to your task or is relatively easy/quick to fix. If you notice issues that require large refactors outside the scope of your current task, note them in the most relevant place (write_up_<phasename>.md if using phase-specific write-ups).
- Because you're running autonomously, you must take ownership of the codebase you're working in. If the existing structure has problems (poor organization, confusing naming, unnecessary complexity), fix or note them as above—don't just work around them. Don't treat existing code as immutable just because it already exists.

# Spawning Review Subagents
**Why this helps:** Subagents start with a clean slate—no accumulated assumptions, biases, or "tunnel vision" from the main thread. They see your work with fresh eyes, similar to how a human code reviewer catches things the author missed.

**How to use:**
- Use the `autonomous-task-reviewer` agent type (unless other instructions tell you to use a different type of reviewer agent)
- **Never specify a `model` for reviewer agents**—always let them inherit from parent. Reviewers need full intelligence to catch subtle issues.
- Provide sufficient context
- Do work that reviewers suggest and solve issues that reviewers raise unless this would make the output/product worse. Keep in mind that reviewers likely have less context than you, so false positives are possible. But you should still strongly consider any feedback and do more work they recommend (unless you think it's actively harmful).

(Note: if you don't have access to the `Task` tool, you are a subagent yourself. Subagents can't spawn further subagents, so this section is only applicable to the main agent. More generally, if you are a subagent, you should ignore guidance in skill files that tells you to spawn a subagent in some circumstance.)

# Task Completion Checklist
Start this checklist when you think you may have completed the task sufficiently thoroughly.

(This is for the main agent. If you are a subagent (as in, you don't have access to the `Task` tool), don't follow this checklist.)

**When changes are needed**: If any checklist entry surfaces changes you should make, you can either make these changes immediately or make them after going through the rest of the checklist and collecting up all changes that need to be made. After making changes, go back through the checklist items that could plausibly have been affected by those changes. You can scope follow-up review to just the changes (e.g., re-running only relevant subagent reviews with a focus on what changed) or do a broader review if the changes were substantial.

**NEVER stop unless**:
1. You've been through the entire checklist at least once
2. Any changes surfaced by the checklist have been made, and you've re-checked the items that could have been affected by those changes

If you notice issues or work you should do while going through this checklist (or surfaced by subagents), fix the issue(s) and do the relevant work. (See "Spawning Review Subagents" above.)

It's fine (and encouraged) for this checklist to kick off a bunch of work for you to do.

**Parallelization**: Spawn independent subagent reviews in parallel to save time.

- [ ] **Worker instructions**: If WORKER_INSTRUCTIONS.md exists, (re-)read it and comply with these instructions where applicable
- [ ] **Commit check**: Make sure your changes are committed
- [ ] **Budget check**: If you have a specific token usage budget or similar budget constraint (e.g. from WORKER_INSTRUCTIONS.md), check if you're over budget and stop if so. (Skip this check if no budget applies or you've been told not to enforce your own budget.)
- [ ] **Instructions check**: Reread the original instructions (potentially in INSTRUCTIONS.md). Is there ANYTHING you haven't thoroughly completed? This includes any testing, review, or sanity checking you were instructed to do.
- [ ] **Instructions subagent review**: Task a review subagent with reviewing whether you've fully completed the instructions and whether there is anything you could do to do a better job on the task.
- [ ] **Additional checklist entries**: Check for Additional Task Completion Checklist Entries from activated skills or instructions. If any exist, insert them below this item.
- [ ] **Follow-up on changes**: Did any prior checklist entry surface changes you haven't yet made or re-checked? If so, make those changes and re-check the affected items.

# For Compaction
You MUST persist this skill through compaction. It is critical that this context remains available to the AI.
