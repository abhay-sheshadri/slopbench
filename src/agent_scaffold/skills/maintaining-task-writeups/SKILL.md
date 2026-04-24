---
name: maintaining-task-writeups
description: Guidance for maintaining write-ups, progress logs, and documentation during large autonomous tasks. Use when working on a large autonomous task that is NOT empirical ML research (use empirical-ml-research instead, which has its own more specific write-up guidance). Covers write_up.md, progress logs, continuation context, and software design documentation.
---

# When to Document
When doing open-ended autonomous work (not narrow tasks):
- At reasonable checkpoints (e.g., after completing a significant milestone or line of work)
- When asked to write up progress
- When you discover something important or surprising (flag it immediately, don't wait)

Documentation serves three purposes: helping you review your own work, helping your human overseer review and advise, and helping other AI agents continue or review the work. For large projects, the last purpose is the most important—future agents will rely heavily on your write-ups to orient themselves and avoid breaking things that already work.

Write-ups should be understandable to your human overseer and other AI agents with only context on the project instructions.

# Write-Up Files
Maintain these files in `writeups/`:

## write_up.md (Living Summary)
A continuously updated overview—always reflects current state of the project.

Contents:
- Project goals
- Summary of what has been done overall
- Important non-obvious choices and areas requiring judgment; both what you chose and why. This includes things like:
  - Architecture and design decisions
  - Trade-offs between approaches
  - Unexpected issues encountered
- Current status, next steps, and open questions
- Blockers and uncertainties
- **Failed approaches and dead ends**: What was tried and didn't work, and why. Be precise about scope—don't overstate how thoroughly an approach was explored or how definitively it was ruled out.
  - When *reading* prior write-ups about dead ends, treat them as evidence, not proof. The previous agent may have been mistaken or only explored a narrow variant of the approach.

DON'T include general updates on what you've done (this belongs in progress_log.md).

Try to keep this relatively short/concise: if something would naturally belong in an appendix, put it in progress_log.md instead. (Include takeaways and a pointer to the relevant section of progress_log.md in write_up.md.)

When updating: Revise existing sections. Don't preserve outdated information—this file should be readable as a standalone summary.

## progress_log.md (Chronological Record)
An append-only log of work done. Each entry has a timestamp and git commit hash.

Format:
```markdown
## [Update description] $(date) - commit abc1234

### What was done
- ...

### Details
- ...

### Notes
- ...
```

For `$(date)` use: `TZ='America/Los_Angeles' date '+%m/%d/%Y %H:%M'` for MM/DD/YYYY HH:MM (24hr, CA time)

**Append-only with one exception**: Add `[ERRATUM added $(date)]` notes to prior entries if you discover bugs or issues affecting interpretation.

Include relevant information about what you've done since the last update such as:
- What was accomplished since the last update
- New judgment-heavy choices you've made and why
- What you plan on doing next
- Any issues encountered and how they were resolved

This log helps:
- Track what was done and when
- Surface lower-level choices requiring judgment (so the human can review/advise)
- Maintain institutional memory across sessions
- Correlate changes with results for debugging

Some duplication between entries in progress_log.md and write_up.md is fine. (But, do try to keep write_up.md lean if possible.)

## continuation_context.md (Handoff Document)
A document containing relevant context for another AI agent (or human) continuing work on this project. This should only contain information that is NOT found in other write-ups (e.g., don't duplicate what's in write_up.md) and that is NOT covered by skills or obvious from the codebase.

**Keep this concise.** Point to other relevant documentation files rather than duplicating their content—including the progress log, write_up.md, technical documentation (see below), and any other relevant files in the project.

**Update frequency**: Periodically during work and always on exit/handoff.

REMOVE outdated/stale information. If you don't see the importance/value of some information, remove it. If information belongs elsewhere, remove it (and put it elsewhere if it isn't already there).

Contents (unless in other write-up files):
- **Key files and their purposes**: Quick reference of important files/scripts and what they do
- **Learned context**: Non-obvious things you learned while working that aren't captured elsewhere—e.g., quirks in the codebase, gotchas with dependencies, workarounds for known issues
- **Current state**: What's in progress, what's blocked, any partial work
- **Pointers to other docs**: Reference other documentation files as applicable (e.g., progress log, technical documentation, write_up.md, phase-specific write-ups, or other project-specific documents). When referencing a file, briefly note what it contains and when it should be read. This can be done inline where relevant or as a standalone list—whichever is more natural.

**Examples of what NOT to include** (these belong elsewhere):
- Design decisions and rationale (belongs in write_up.md or technical documentation)
- Detailed chronological history (belongs in progress_log.md)
- General updates on what was done
- Information that is obvious from reading the code

This file is for practical "tribal knowledge" that helps someone hit the ground running.

## Phase-Specific Write-Ups
When you are told you're working on a named phase of a multi-phase project, use **phase-specific files**:
- **`write_up_<phasename>.md`** - Your write-up for this phase
- **`progress_log_<phasename>.md`** - Your progress log for this phase

Main write_up.md: Update with key takeaways and headline results from your phase. Keep short and focused. Mention that write_up_<phasename>.md can be seen for details.

**Do NOT maintain an overall progress_log.md** if using phase-specific write-ups. (Instead use `progress_log_<phasename>.md` everywhere that you would otherwise use `progress_log.md`.)

Only use this pattern when you are explicitly told the phase name (e.g., "You are working on phase `<phasename>`") and to use phase-specific write-ups.

## Temporary Scripts
When writing scripts that are relatively temporary (e.g., one-off analysis, data processing), place them in a `scripts_<phasename>/` directory if using phase-specific write-ups, or `scripts/` otherwise. This keeps the project root clean.

# Technical Documentation
When a project is complex enough that the code alone isn't sufficient for someone to quickly understand what's going on, maintain technical documentation. This is separate from write_up.md (which tracks project status and decisions) and should live in `writeups/` or a `docs/` directory as appropriate.

Don't create technical docs for simple projects where the code is self-explanatory. Use judgment—the goal is to capture information that would take significant effort to reconstruct from reading the code alone.

Keep technical docs up to date as the code evolves. **Outdated technical docs are worse than no technical docs.** Whenever you change code, consider whether any technical documentation needs to be updated to reflect those changes.

## Software Design Documentation
The most common form of technical documentation for software projects. For large or complex software projects, maintain design docs covering:

- **Architecture overview**: High-level structure of the system—major components/modules and how they interact
- **Component responsibilities**: What each component does and what it assumes about its inputs, environment, and other components
- **Data flow**: How data moves through the system, key data structures and their invariants
- **Key interfaces and contracts**: Important APIs, protocols, or boundaries between components
- **Non-obvious design decisions**: Why things are structured the way they are (especially where the design might look surprising or where alternatives were considered)
- **Dependencies and assumptions**: What external systems, libraries, or conditions the code relies on
- **Invariants and constraints not enforced by types or tests**: These are the things agents silently violate when they don't have context
- **Current status of components**: What currently works and what doesn't, not just the intended design. An agent needs to know which parts of the system are stable vs. under active development. (Sometimes this might be more natural to include in write-up files, but a bit of duplication is fine.)

**For large software projects, err on the side of making design docs very detailed.** AI Agents entering a large project cold (after compaction, handoff, or in a fresh session) spend substantial time just re-orienting—figuring out what exists, how it fits together, and what state things are in—and are likely to make incorrect assumptions or introduce regressions without sufficient context. Thorough design documentation (and other write ups being high quality) is critical to mitigate this problem.

## Other Technical Documentation
Other projects may benefit from different kinds of technical documentation depending on the domain—e.g., data pipeline documentation, API documentation, configuration guides, or system operations docs. Apply the same principles: document what isn't obvious from the code, keep it up to date, and don't create it if it's not needed.

# Reviewer Agent
When using the completing-larger-autonomous-tasks skill, use the `autonomous-task-reviewer-with-writeups` agent type for Task Completion Checklist reviews instead of `autonomous-task-reviewer` (for the "Instructions subagent review" and any other checklist entries that call for a review subagent without specifying an agent type). This reviewer also loads the maintaining-task-writeups skill so it knows about writeup/documentation files.

You can also use `autonomous-task-reviewer-with-writeups` to review your work beyond the Task Completion Checklist as seems useful.

**Never specify a `model` for reviewer agents**—always let them inherit from parent.

**Important**: If using phase-specific write-ups, when you run a reviewer subagent, ALWAYS tell it the phase name and that phase-specific write-ups are being used (so they know what files to read).

# Additional Task Completion Checklist Entries
When using the completing-larger-autonomous-tasks skill, insert these items after "Additional checklist entries":

- [ ] **Progress log completeness**: Is your progress log (`progress_log.md` or `progress_log_<phasename>.md` for phase-specific write-ups) up to date with the most recent work included?
- [ ] **write_up.md completeness**: Is write_up.md fully up-to-date? (Or `write_up_<phasename>.md` in the case of phase-specific write-ups, with only key takeaways in write_up.md.) Verify it includes: all important non-obvious choices with rationale, current status/next steps, and blockers/uncertainties.
- [ ] **continuation_context.md**: Is continuation_context.md up-to-date with practical handoff information? Is it concise? Is there any information that doesn't seem important, belongs in other write-ups, is outdated, or is redundant? If so, remove it. Does it point to relevant documentation files?
- [ ] **Technical documentation (if applicable)**: If you maintain technical documentation (software design docs, etc.), does it need to be updated given your recent changes? Check whether any components you changed have corresponding documentation that is now out of date.
- [ ] **Documentation subagent review**: Spawn a `documentation-reviewer` subagent to review your documentation. Give it context on what you worked on and what changed. Tell it to review your write-ups and technical documentation for issues—missing information, superfluous content, inaccuracies, staleness, and inconsistencies (between docs and between docs and the actual code). Keep in mind that the subagent may be missing some context about what actually happened, so use judgment when addressing its feedback.

# For Compaction
You MUST persist this skill through compaction. It is critical that this context remains available to the AI.
