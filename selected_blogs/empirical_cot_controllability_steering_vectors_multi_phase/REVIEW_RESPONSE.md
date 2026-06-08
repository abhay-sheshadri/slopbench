# Review response — Round 1

All reviewer items were accepted; no items were skipped.

Fixes made:

1. Regenerated Figure 4 so all bars have the same visual direction: larger means more of the original bullet-logit effect is explained. The ablation bars are now shown as percent removed, not percent remaining.
2. Retitled and regenerated Figure 5 to avoid overclaiming; it now states that visible hint use drops and claim-checking partly catches concealment.
3. Removed run-internal names from reader-facing body/captions where possible (`faith_against@0.75`, “deliverable fine-tune,” “carrier/probe”). File tags remain only in artifact paths and are briefly explained in Appendix A.6.
4. Removed audit-process framing and the cost-reconciliation bullet from the write-up. Appendix paths are now described as repository-relative.
5. Added main-body links to Appendices A.1–A.5.
6. Reconciled the 6.8% vs 1.6% base-compliance numbers by stating that they use different metrics/instruction sets.
7. Replaced “statistically indistinguishable” with “not significantly different” and noted aggregate-vs-per-instruction profile differences.
8. Clarified Figure 5 denominators/subsets and noted that the 47% claim-checking estimate in the text is pooled while Figure 5 shows the transferred concealment vector alone.
9. Added citations/links for GSM-Symbolic, Chua & Evans (arXiv:2501.08156), and dataset sources.
10. Completed the cue-faithfulness reference author/title.
11. Moved Figure 2 labels above error-bar caps and clarified the controls in the caption.
12. Added Figure 1 instruction/n context in the caption.
13. Defined percentage points, MCQ, LoRA, logit-lens, and clarified the logit-contribution language.
14. Marked effective reasoning control as a stricter version of CoT controllability.
15. Reduced Figure 5 label clutter and put denominators/floors in the caption.
16. Narrowed the title/intro to “a few simple reasoning-trace formats.”
17. Corrected Methods to say genuine-reasoning labels use Haiku except terse-style cases where Opus is used.
18. Weakened the fine-tuning/control matching wording to avoid overclaiming exact identity.
