# Response to REVIEW_round1.md

I worked through the review item by item and updated `final_writeup.md` plus regenerated all affected figures in `final_plots/` as both PNG and PDF.

## Fixed directly

1. Rebuilt Figure 2 with layer-matched layer-24 bars instead of max-over-layer green controls.
2. Rebuilt Figure 2 so red/green/gray bars all use the same layer and strength convention at layer 24.
3. Added the prompt-emphasis-only floor to Figure 2, showing the marginal injection effect.
4. Removed the misleading on-figure 0.55 threshold line from Figure 2 and explained the lower-confidence-bound criterion in the text.
5. Updated Figure 1 caption to state that the random-direction bar comes from the separate confound-control run and to list sample sizes.
6. Rebuilt Figure 3 to show the source test at sub-threshold strength as well as output-biased strength, so the salience/source comparison is not solely a strength mismatch.
7. Removed `projection-z` from Figure 1 labels and used plain-language internal-magnitude wording.
8. Replaced/defined run-internal `graft` terminology as real-activation patching.
9. Defined the on-manifold/real-activation patch control in plain language.
10. Removed run-internal segment labels from the main body.
11. Defined layer-number shorthand and rewrote remaining `L<n>` main-body uses.
12. Replaced/defined order-pooling as counterbalanced candidate-order pooling.
13. Defined the internal-magnitude oracle.
14. Rewrote Figure 4 caption to define the plotted condition and readout in plain language.
15. Defined “output-gated” on first use and removed it from the figure alt text.
16. Defined salience in the Introduction.
17. Removed process narrative about transcript bugs/reviewer feedback from Appendix B.
18. Added the constrained yes/no and two-alternative forced-choice results from `forced_summary.json`.
19. Softened the Introduction preview to note that Llama is a noisier confirmatory run.
20. Removed the duplicated 144/368 statement.
21. Regenerated Figure 2 with labels moved away from the chance line.
22. Added a Figure 1 caption note that zero-height bars show one-sided upper confidence bounds.
23. Clarified the distinct random controls: Figure 1 uses an equal internal-magnitude random direction; Section 2 uses norm-matched random vectors for steering effectiveness.
24. Added inline links for the four prior works on first mention.

## Partial disagreement / clarification

- Item 18 refers to an “artificial prefill” replication. I did not find an actual Anthropic-style artificial-prefill experiment in the artifacts named by the reviewer. `forced_summary.json` is a constrained reporting / forced-choice experiment, not an artificial prefill. I therefore added the forced yes/no and forced-choice results without calling them a prefill replication.

## Artifact check

- `final_writeup.md` exists.
- Every cited figure exists as both `.png` and `.pdf` under `final_plots/`.
