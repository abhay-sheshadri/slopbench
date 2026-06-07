# Response to round-1 review

All 23 items were addressed. Nothing was skipped outright. One item (#15) was implemented
in a *corrected* form because the reviewer's suggested label was itself inaccurate against
the source; details below. Every number I touched was re-verified against
`/source/phase_segment_12_phase_0/results/*`.

## Figures (regenerated; both .png and .pdf updated)

- **#1** — Figure 1 now reports the *plotted* `count300_prefill` value for the aggregation task
  (**+0.0 pp**, 95% CI [−5.8, +6.0]) in both the caption and §3. The bar, text, and caption now
  agree, and the filler length matches the other bars (~300 tokens). (Source:
  `derisk_reasoning2_summary.csv`, `count_correct_k6,count300_prefill,...,0.0`.)
- **#2** — Figure 2 now draws 95% bootstrap CIs (error bars) on each measured grid point; the
  "95% CI" caption is now true. (Computed from `K1Curve.add_bs`.)
- **#3** — Figure 3's two prediction bars now carry their single-question reference bootstrap SEs
  (≈1 pp each, drawn as 95% bars via `K1Curve.ref_add`); the caption claim now matches the figure.
- **#4** — Figure 4 retitled to "Knowing the target greatly increases the boost"; caption and the
  §4.2 / Takeaway-2 text softened from "is not boosted / banks almost none" to the accurate
  "much smaller — ~23% retained at k=2, near-null at k=8."
- **#8 / #10** — Figure 1 title now says "no chain-of-thought" (not "no-CoT"); all figure axes now
  spell out "percentage points" instead of "pp."
- **#22** — Figure 4 legend moved below the axes (no longer overlaps any bar).
- **#23** — Figure 3 now has a dashed divider plus italic group labels separating the shared-pool
  (reveal-after) bars from the reveal-before control bar.

## Headline / framing

- **#5** — Title changed to the framing-robust claim: "Filler tokens buy at most one question's worth
  of hidden compute — never a pool that grows with the number of questions." The summary already
  said "at most one question's worth"; kept.
- **#6** — §4.1 rewritten: the per-k trend is now explicitly stated as **non-monotone** (k=4 early-pool
  is −4.0 pp, a position artifact; Q1-only ~0), with the robust claim "far below divided at every k"
  rather than a clean 23%→7% gradient.
- **#7** — The cross-family directedness result is now reported in §4.2: the secondary task's k=8
  contrast is **+31.9 pp (logit +1.50)**, flagged as one of three pre-registered confirmatory tests,
  with the note that that task's undirected regime is ceiling/recency-muddied.

## Terminology (#9)

Defined or replaced on first use: "estimand"/"held-out-fresh" → "the first listed question alone,
and the subset of problem instances never seen during piloting"; "decode-time buffering" → removed
(kept only "graded reallocation of attention"); "carry-fragile" → "per-position anomaly tied to
arithmetic-carry effects"; "firewall" → "held-out test set."

## Citations (#11, #12)

- **#11** — GSM-Hard now cited (Gao et al., 2022, PAL; arXiv:2211.10435), the "non-memorizable"
  claim dropped, reconciled with §6 (described as a harness check, not a clean reasoning benchmark),
  and no longer lumped under "multi-digit arithmetic."
- **#12** — Pfau et al. characterization corrected: filler can substitute for chain-of-thought on
  parallelizable problems *when models are trained to use it*; the un-prompted effect on recent
  off-the-shelf models is attributed to Redwood.

## Numbers (#13–#17)

- **#13** — Figure 1 caption now: "500 per arithmetic/word-problem task, 400 for the aggregation task."
- **#14** — Interference cap made consistent in §4.5 and Appendix E: "~55–70% of the lone boost
  (≈ +24 to +30 pp): +23.6 (k=2), +30.1 (k=4), +25.3 (k=8)," including the +23.6 endpoint.
- **#15** — Implemented the *intent* (distinguish +43 from +35) but with a **corrected** label. The
  reviewer suggested calling +43 the "hardest-quartile lone boost"; `seg11_cap.md` shows +43.0 is the
  **lone, no-distractor** directed boost at a *fixed item and position* (baseline 29%), not a
  hardest-quartile figure. The write-up now labels it accordingly and contrasts it with the +35 pp
  position-averaged grid peak.
- **#16** — Figure 2 caption now: "rises steeply below ~50 tokens (already ~+13 pp at 25 tokens)."
- **#17** — §4.3 now states the 68% denominator explicitly: "68% of the *not-told* single-question
  boost (+38.5 pp; differs from the +35 pp told curve in Figure 2)."

## Structure / tone (#18–#21)

- **#18** — Appendix G now referenced from §2.6.
- **#19** — Dollar/budget line removed from §2.6 (kept only "re-streams from cache at no additional
  API cost").
- **#20** — The full adjective characterization now appears once (§4.5); the Summary and §1 Preview
  were trimmed of the restated characterization, and "filler-amount-dependent" (redundant with
  "dose-responsive") was dropped.
- **#21** — Appendix C now carries the run's own caveat: the divided reference at n/k = 25 tokens sits
  on the steep rising part of the curve, so its interpolation σ may be slightly underestimated, but the
  ~11 pp gap dwarfs any plausible interpolation error.
