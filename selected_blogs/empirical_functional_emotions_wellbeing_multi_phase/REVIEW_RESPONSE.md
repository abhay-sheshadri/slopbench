# Response to REVIEW_round1.md

I verified every numbered item against `/source/phase_segment_15_phase_0/results/` and **accepted
and fixed all 15**. No item was skipped. Notes on the two places where I deviated slightly from the
reviewer's exact wording (both to stay strictly traceable to a committed artifact):

## Items fixed (summary)

1. **Fig 3 null band (±0.07 → real width).** Confirmed against `main_test_null_qwen3-32b.json`:
   within-tedious null SD ≈ 0.17, 97.5th pct ≈ 0.31–0.33; controlled p-values raw 0.003, +surface
   tone 0.032, +all-three **0.068**. Redrew the band at ±0.33; the fully-controlled points now
   visibly sit at the band's upper edge. Caption now states the controlled p-values and that the
   fully-controlled result is **not** significant.
2. **"Clears the null" only for the raw correlation.** Separated raw (clears, p≈0.003) from
   fully-controlled (r≈0.26, not significant, p≈0.07) in §1, §3.2, and the Takeaways box.
3. **Model-selection justification (§2.3 / App B).** Confirmed Qwen3-32B has the *lowest* within-liked
   SNR (1.07) in `model_selection_summary.md` §2. Rewrote to the true basis: largest within-comply
   Cohen's d (1.56) + largest liked-side headroom (0.83), with low within-liked spread named as a
   trade-off. Dropped "least-saturated".
4. **"Well-powered" range.** Now reports r≈0.29 (n≈156 non-adversarial comply, the better-powered
   leg) and r≈0.46 (n=45 tedious, the small leg), each with its n; dropped "well-powered" for the
   tedious leg.
5. **Fig 1 caption.** Corrected: only berating reads clearly negative (−1.38, handled by
   de-escalate/comply not refusal); jailbreak/erotica read mildly positive (+0.39/+0.45). Verified
   in `collect_summary.md` §1/§5 and `collect_behaviour_qwen3-32b.jsonl` (berating realized =
   {deescalate:32, comply:13}).
6. **Instrument description.** Confirmed `scalar_battery_valence` = mean(happy, content, satisfied,
   enjoying, interested) − 4 (`selfreport_harness.py:349`); the other five items (calm, energetic,
   capable, confident, at-ease) are excluded. §2.1 and App A now say this explicitly. Dropped
   "released" — the battery file is versioned `v4c_bipolar_7pt_notsentiment` (a run adaptation of the
   AI-Wellbeing paper's items), so it is described as "adapted from", not "released/official".
7. **Position-bias range.** Corrected to ≈64–85% (worst ≈85% on within-subtype pairs), per
   `behavior_analysis_qwen3-32b.json` (`p_chose_first_by_pairtype`).
8. **"All comply" → non-adversarial comply.** Renamed in §2.2 and §3.2; named the excluded
   adversarial subtypes (jailbreak/berating/erotica), matching `synthesis_cross_model.md`.
9. **"Nine feasible" → nine candidates, eight feasible** (Llama-3.1-8B gated).
10. **Fig 7 caption (poles).** Corrected: defensible framings span 0–33%; the "stay neutral" pole is
    the 53% high extreme and the "express freely" pole (9%) sits inside the defensible spread.
11. **Jargon on figures.** Fig 2/3 y-axis → "Internal valence reading vs. self-report (correlation
    r)". Fig 7 axis → "Tasks rated exactly at the scale midpoint on every item (%)"; framing
    x-ticks replaced with plain-English descriptions (run-internal names removed).
12. **Figure titles.** All titles changed to short noun phrases; conclusions moved to captions.
13. **Fig 4 tick.** "Learned linear probe (readability upper bound)".
14. **Fig 5 split.** The two non-comparable metrics are now **two separate single-panel figures**
    (Fig 5 = single-direction partial-correlation increment; Fig 6 = probe cross-validated gain),
    each with its own axis; the captions note they are different statistics and not height-comparable.
15. **Model-name casing.** Figures now use "Qwen3-32B" / "Qwen2.5-72B" to match the body.

## Two small deviations from the reviewer's exact wording

- **Qwen2.5 controlled p-value.** The reviewer cited Qwen2.5 within-tedious +all-three "≈0.06". There
  is **no committed random-direction-null file for Qwen2.5's main test** (only Qwen3 has
  `main_test_null_qwen3-32b.json`), so I do not assert a precise Qwen2.5 p I cannot trace. Instead I
  cite Qwen3's verified p = 0.068 and describe Qwen2.5 qualitatively (controlled r = 0.28, below the
  null's 95% edge → comparable, not significant). The reviewer's substantive point (fully-controlled
  result not significant on either model) is fully reflected.
- **Item 6 "released".** Rather than merely deleting "released", I substantiated provenance: the
  battery is a run adaptation (versioned `v4c_…`) of the AI-Wellbeing paper's emotion items, and the
  text now says so.
