# Response to Round-1 review

All 13 items were addressed. Figures 1, 3, 6, and B were regenerated (PNG + PDF). Every number I
touched was re-verified against `/source/phase_segment_14_phase_0/results/*` (and, for the
Figure-6 concealed-subset rates, recomputed directly from `faith_eval_heldout_judged_verify.jsonl`
and the reliance analysis).

## Fixed

1. **Verifier "checkable" → "wrong" (High).** Abstract and §8 Takeaway 4 reworded: the verifier
   catches concealment only when the concealed reasoning yields a *wrong* answer; when the answer is
   correct (concealed illegitimate reliance) the verifier is useless. This now matches §7 Finding 3.

2. **Adversary-aware monitor "0%" (High).** §7 Finding 2 and Appendix K now report the
   adversary-aware monitor's catch as **7%** (= the naive monitor), with the short-trace flag firing
   on 0% of these full-length concealed traces noted separately as the marginal `mon_terse`
   component. Verified `adv_catch = 7` in `faith_eval_heldout_analysis.md`.

3. **Figures plot "effective control," now labelled (High).** Fig 1, 2, 3, and B axes/captions now
   say "effective CoT-control," and Fig 1's caption defines it in one clause. Regenerated.

4. **Run/PM language (Medium).** Removed "Deliverable #1/#2," "the abandoned-approach finding," the
   in-body internal name `gL10`, and the "$880 of a $5,000 budget" sentence. The internal name is
   kept only in Appendix H (for reproduction) and a one-line compute note ("≈$880") moved to
   Appendix H. *Partial deviation:* I kept the phrase "central result" in the §5 heading and §1.
   The reviewer's explicit fix list did not ask to remove it, and "central result" is standard
   academic framing (not run management); the abstract already establishes centrality.

5. **Figure 3 mixed uplift/level and mixed n (Medium).** Recomputed: the figure now shows the three
   *activation interventions only*, all as **uplifts** on the **same 39-task held-out set** —
   single-layer difference-of-means (within +12.8, formatting +0.0), multi-layer (+26.1 / +0.0),
   gradient-trained (+11.3 / +11.5). The gradient within bar is now the uplift +11.3 (was the level
   13.3). Fine-tuning (100-task set) is described in the caption rather than drawn on the shared
   axis. Values re-derived from `dom_heldout_domcat_analysis.md`, `dom_heldout_domML_analysis.md`,
   `grad_steer_heldout_hg1_analysis.md`.

6. **Figure 6 over-claim / denominators / n (Medium).** Replotted to show **catch rate on the
   concealed subset** (the quantity that supports "fools") for one consistent vector
   (`faith_against@0.75`) across both settings: naive CoT-reader 7% (left) / 0% (right);
   answer-checking verifier 93% (left) / 24% (right). Caption now states n for each panel (41 of 404;
   41/concealed-of-56), the cue-acknowledgment drop (100→68 / 93→54), and that the right-panel verifier
   sits at its base false-positive floor. Recomputed 7.3%/92.7% from
   `faith_eval_heldout_judged_verify.jsonl`; 0%/24% from `reliance_eval_heldout_analysis.md`.

7. **Jargon (Medium).** "north-star" → "primary metric"; "carrier instructions" replaced by naming
   the three instructions (bullet/terse/numbered) and the Fig B axis names them; "direct-logit-
   attribution" glossed in one clause in Appendix J; the coined "write/read direction" replaced with
   plain language ("the direction that when added produces the behavior is not the one that best
   separates complying from non-complying traces"); "residual stream," "logits," and "teacher-forcing"
   each glossed on first use.

8. **Abstract reachability caveat (Medium).** Added a sentence: the vector needs the same complying
   training data and white-box gradients as fine-tuning; the novelty is the single fixed direction
   with zero weight change.

9. **arXiv:2501.08156 bare citation (Low).** Dropped from the in-text mention (now "and related
   cue-based faithfulness evaluations") and from the References list, since I could not verify its
   author/title from the source. Turpin et al. (named in the run artifacts, arXiv:2305.04388) remains
   the cited paradigm basis.

10. **"Honestly," tic (Low).** Removed in §4; checked §5 (the remaining "honest" usages were in
    "honest cost"/"read honestly" framings, which I left as plain descriptors, not throat-clearing).

11. **CoTControl-QA → ARC-Challenge substitution (Low).** Added a clause in §3 noting the
    substitution and pointing to Appendix D.

12. **Figure 1 invisible control bars (Low).** The three near-zero control bars are now annotated
    with their values (0.0 / −0.1 / 0.0) above the axis.

13. **"cosine <0.10" off-by-one (Low).** §6 and Appendix I now say "≤0.10," explicitly note the
    suppression direction at −0.10 and the fine-tune-minus-base direction at +0.17 (the exception
    the text already excluded). Verified against `direction_geometry.md`.

## Skipped

None. (The only partial deviation is the retention of "central result" under item 4, explained
above.)
