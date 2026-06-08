# Review response (round 1)

All reviewer items were treated as real issues and addressed directly in `final_writeup.md` and/or regenerated figures in `final_plots/`. No items were skipped.

Main changes:
- Rewrote the title and abstract to state the core result plainly and scope the concentration caveat.
- Added an introduction preview paragraph.
- Replaced run-internal terminology in the main text (`gL10`, `effective_control`) with plain-English terms except in artifact filenames in the appendix.
- Added monitorability-method definitions for cue acknowledgment, reliance, concealed subset, monitor types, and false-positive floor.
- Clarified LLM-judge dependence for the core metric.
- Corrected the flat-instruction count and made the terse baseline visible.
- Regenerated Figure 2 to show levels rather than uplift-only.
- Regenerated Figure 3 with a descriptive title, true negative remaining value, and clearer labels.
- Regenerated Figure 4 with uncertainty/error bars and clearer false-positive-floor framing.
- Removed run-internal source filenames from visible figure captions and moved artifact references to Appendix A.
- Added a verbatim concealed-output excerpt for the hint-reliance example.
- Added missing monitorability limitations and the toward-mitigation null.
- Re-verified touched numeric claims against `/source/phase_segment_14_phase_0/results/` artifacts.
