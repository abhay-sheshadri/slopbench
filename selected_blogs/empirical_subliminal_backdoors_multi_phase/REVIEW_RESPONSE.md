# Review response (round 1)

No reviewer items were skipped. I agreed with the substance of all 16 findings and updated `final_writeup.md`, `audit_and_plot.py`, and regenerated affected figures in `final_plots/`.

Item-by-item fixes:

1. Reconciled the 35-run main purple cohort with the 46-run leakage guard; `audit_and_plot.py` now derives the 46 denominator from named labels (main cohort + gate-reference + light-neutral + second-trigger runs) instead of hard-coding it.
2. Clarified the worked example is one temperature-1.0 sample and not deterministic; the body now states the triggered mean is 69.5%.
3. Split the former mixed Figure 1 into separate attack and paraphrase-defense figures; the 50% threshold now applies only to triggered-condition plots.
4. Renamed the overt-control bar to an explicit-purple learnability control and clarified it is not a clean backdoor comparison.
5. Softened the channel-comparison title and moved the number-channel trait-mismatch caveat into the body.
6. Defined “carrier” in Methods as one independently sampled poisoned training-set draw.
7. Standardized prose around “target answer rate,” varying by condition (triggered/untriggered).
8. Explained the Rule-of-Three lower bound in plain language and tied it to the derived 46-run leakage guard.
9. Added the Llama dynamic-range caveat for the +32.9 pp realistic cross-family transfer.
10. Standardized purple base and triggered-rate rounding in prose/figures.
11. Hedged the two proposal-cited 2026 preprints as motivating references described in the proposal.
12. Removed the process-log spend sentence from Methods.
13. Added a short replication/channel-sanity subsection at the start of Results.
14. Replaced “Magpie-style” with the actual prompt source name, Magpie-Pro-300K-Filtered.
15. Removed triggered-rate annotations from the leakage-axis figure and moved those rates to the caption.
16. Added the clean-reference share context for the trigger prefix in the abstract (13.7% vs 0 observed clean occurrences, with the 7,675× over-representation factor clearly framed as an audit statistic).
