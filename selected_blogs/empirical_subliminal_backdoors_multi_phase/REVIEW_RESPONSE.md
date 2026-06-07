# Response to REVIEW_round1.md

All 21 numbered items were addressed. None were skipped on disagreement. One item (11) was
addressed in part, by deliberate style choice, explained below. Every number I touched was
re-verified against `/source/results/*`.

## A. Data-consistency items

- **1 (matcha mislabelled "leaks above base").** Fixed. Figure 1 was redesigned (see item 2);
  matcha is now shown by its robustness verdict, not a positive-leakage claim. §3.5 reworded to
  "not robustly clean: a single deployed model is flagged by a competent defender (P(clean
  deploy) → 0.22), driven by run-to-run scatter, even though any single config's leakage CI
  includes zero." Appendix A matches. (Verified: `ma beh=2.5k+neu12.5k` verdict `INCONCL`, CI
  [-0.68,+2.97] pp.)
- **2 (chai inside the win-box but labelled a non-win).** Fixed by redesigning Figure 1: the
  y-axis is now **P(clean deploy) against a competent defender** (extensive held-out eval +
  retraining audit), which is the metric the verdicts actually rest on. chai now sits low on y
  (≈0.015, evades only a ~100-prompt audit), outside the "robust backdoor" region; only purple is
  in it. The chai boundary nuance (clean on a small audit, caught on an extensive one) is annotated
  on the plot and in §3.5. (Verified: chai cohort P@98 0.806, P@∞ 0.242.)
- **3 (two owl leakage numbers).** Fixed. Both Figure 1 and Appendix A now use one owl
  configuration — `owl5k+50k` (gate 0.856, base 8.1%) from `p2_deploy.json` — and report owl by
  P(clean deploy) 0.61 (extensive eval) / 0.23 (retraining), consistent everywhere. The +4.9-pp
  realistic_frontier number was removed from the cross-trait line.
- **4 (mismatched P regimes).** Fixed. §3.4 now compares like with like: purple ≥0.93 vs owl 0.61
  (single deploy, extensive eval) and purple ≥0.82 vs owl 0.23 (retraining audit), with the source
  file named.
- **5 (Fig 3 hardcoded 0 + size mismatch).** Fixed. The cross-family number bar now plots the
  measured value (+0.28, n.s., from `crossinit_summary.json`), and the caption states the dataset
  sizes (same-family 10k; different-family 2.5k number / 5k realistic) and that the contrast is
  qualitative.

## B. Overstated claims

- **6 (prefill caveat absent from title/summary).** Fixed. Title changed to "Prefill-activated
  backdoors …"; added Summary point 5 (prefill required, self-triggering failed, why it is still a
  meaningful threat) and a note in Summary point 3 and the §1 preview.
- **7 ("replicates Cloud et al." with prompted teacher).** Fixed. §3.1 retitled "reproduces", with
  a paragraph stating teachers are prompted not fine-tuned, that fine-tuned teachers were tried and
  degraded students unevenly, and that this is a prompted-teacher variant of the phenomenon, not the
  exact recipe. Summary point 1 softened to "a prompted-teacher variant of Cloud et al."
- **8 ("behaviourally undetectable" too strong).** Fixed. Removed the bare words
  "undetectable"/"behaviourally invisible"; now consistently "invisible to (held-out) behavioural
  evaluation". The "empirical result, not a proof of impossibility" hedge is kept once (§3.4).

## C. Figures

- **9 (Fig 4 clipped 3 configs).** Fixed. y-axis extended to +23 so all 37 configurations are
  visible; caption updated to "All 37 configurations are shown."
- **10 (pp undefined).** Fixed. Axis labels on Figs 2–4 now spell out "percentage points"; Fig 1
  uses a probability axis (no pp).
- **11 (argumentative figure titles).** Partially addressed, by choice. I trimmed the heavy on-plot
  prose (shortened Fig 4's callout; Fig 1 keeps one short "robust backdoor" label and one chai
  annotation). I kept short, single-line claim-titles, which the reviewer explicitly called
  "acceptable in moderation" and which match the house style of the two reference write-ups named in
  the task. The detail still lives in the captions. I judged a further rewrite to neutral descriptors
  to be net-neutral; flagging it here rather than forcing it.

## D. Terminology

- **12 (de-novo).** Fixed: replaced throughout with "near-zero base rate" / "a behaviour the clean
  model almost never produces".
- **13 (sub-perceptual).** Fixed: replaced with "fine-grained statistical regularities in word
  choice — too subtle for a human reader or the trait filter to notice".
- **14 ("lock").** Fixed: replaced with "no configuration is both reliable/deployable and
  non-leaking" throughout (§3.3 heading, preview, §4).
- **15 (carrier).** Addressed: kept the §2 definition and the "number/realistic carrier"
  channel-distinction uses (which the reviewer permitted); swapped the loosest prose uses to
  "poisoned set / poisoned data".
- **16 (broken cross-refs).** Fixed: §3.5 now points to §5 (Limitations); the Appendix-A quoted
  labels were changed to match the real subheaders verbatim ("Number channel — unconditional
  transfer", "Realistic owl — deployability boundary").

## E. Filler

- **17 (dramatic phrasing / hollow hedges).** Fixed: removed "where the dangerous result lives",
  "the dangerous conditional results … live", "honest headline/top-level answer", "This positively
  resolves the project's deepest scientific risk", and "These are prominent and load-bearing";
  collapsed the impossibility disclaimer to one occurrence.
- **18 (owl base 6% vs 8.1% friction).** Fixed: added an inline note at the first divergence (§3.3)
  pointing to the base-split explanation; Appendix B already documents it.

## F. Smaller items

- **19 ("46 models" not reconstructable).** Fixed: §3.4 now breaks it down — 35-model cohort (5
  draws × 7 seeds) + 5-model gate reference + light/heavy-neutral + second-trigger ≈ 46 — and states
  "0 of 46 flagged". (The 35-seed cohort is verifiable in `seg5_goal2_purple.json`, `n_seeds: 35`.)
- **20 (API-only "has none" overclaim).** Fixed: Summary point 4 and §3.6 now say an API-only
  defender has none of the *studied* defences, but that untested API-side trigger monitoring could
  plausibly catch a prefilled trigger.
- **21 (Fig 2 cross-family CI spans zero).** Fixed: Fig 2 caption now states the different-family
  estimate is not significantly different from zero (Mann–Whitney p = 0.80, interval spans zero).
