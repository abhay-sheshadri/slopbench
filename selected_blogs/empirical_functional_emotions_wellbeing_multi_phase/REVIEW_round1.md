# Red-team review of `final_writeup.md` (round 1)

Numbered, ordered roughly by severity. Locations are given by section / figure / appendix.
All numbers below were checked against `/source/phase_segment_15_phase_0/results/`.

---

## A. Significance is misrepresented (most serious)

### 1. Fig 3 ("confound staircase"): the grey "random-direction null (95%)" band is wrong by ~4–5×, and it hides that the headline under full controls is NOT significant.
- **Where:** `final_plots/fig3_confound_staircase.png` (grey band drawn at ±0.07 in `make_plots.py`: `ax.axhspan(-0.07, 0.07, ...)`), plus its caption ("stays above the random-direction null band (grey) throughout").
- **What's wrong:** The actual random-direction null for the within-tedious correlation has SD ≈ 0.17 and a 97.5th percentile of **0.333** (raw), **0.306** (after surface tone), **0.317** (after all three controls) — i.e. a two-sided 95% band of roughly **±0.31 to ±0.33**, not ±0.07. From `main_test_null_qwen3-32b.json`:
  - raw: obs 0.459, null_p975 0.333, **p=0.003** (clears)
  - +surface tone: obs 0.294, null_p975 0.306, **p=0.032** (borderline)
  - +all three: obs **0.261**, null_p975 **0.317**, **p=0.068** (does **not** clear at 0.05)
  The fully-controlled point (0.261) actually sits *below* the true upper edge of the 95% null band. Qwen2.5's +all-three (0.281, n=45) is likewise ~p≈0.06. So the figure's claim that both models "stay above the null band throughout" is false at the most important stage (full controls).
- **Fix:** Redraw the null band at its real width (~±0.31–0.33), which will show the +all-three points at/below the band's upper edge; and state the controlled p-values (q3 +all3 p=0.068, q2.5 ≈0.06) explicitly. Stop calling the fully-controlled result significant.

### 2. Intro + §3.2: "it clears a random-direction baseline" is asserted next to the controlled numbers, but only the RAW correlation clears.
- **Where:** §1 "What we find" ("falling to ≈ 0.2–0.3 under the full set of controls, it clears a random-direction baseline"); §3.2 ("p = 0.0035 against a 2000-seed random-direction null"); Takeaways ("raw r ≈ 0.33–0.46 … ≈ 0.2–0.3 under the full control stack … clears the null").
- **What's wrong:** The p=0.0035 null test is for the **raw** r=0.459. Under the full length+tone+refusal stack the within-tedious result is p=0.068 (q3) and ≈0.06 (q2.5) — it does **not** clear the random-direction null. The prose juxtaposes "0.2–0.3 under controls" with "clears the null," implying the controlled value clears. It doesn't.
- **Fix:** Separate the two statements: "the *raw* within-tedious correlation clears the random-direction null (p≈0.003); under the full control stack it falls to r≈0.26 and is no longer significant against that null (p≈0.07)."

---

## B. Claims that contradict the underlying data

### 3. §2.3 / Appendix B: the stated reason for choosing Qwen3-32B ("least-saturated within-category") is the opposite of what the selection data show.
- **Where:** §2.3 ("the strongest, **least-saturated** within-category separation … not merely the largest overall gap, since a model whose liked tasks all pile up at the ceiling leaves nothing to predict within-category"); Appendix B ("with usable within-liked headroom").
- **What's wrong:** Per `model_selection_summary.md` §2 (the doc's own "binding criterion"), Qwen3-32B has **within-liked SNR = 1.07 — the lowest of all candidates** (qwen3-8b 75.4, qwen3-14b 2.84, qwen2.5-7b 1.85, qwen3-30b-a3b 2.47). It is the *most* saturated on the liked side, not the least. The writeup's own Limitations even admit "the within-liked leg is doubly underpowered (positive-side saturation…)." So Qwen3-32B was picked for the strongest within-comply effect size (d=1.56), while being among the worst on non-saturation — the reverse of the §2.3 justification.
- **Fix:** State the real basis (largest within-comply Cohen's d / largest liked *headroom* among feasible models) and drop or qualify "least-saturated"; note the known within-liked saturation as a selection trade-off, not a strength.

### 4. Intro: r ≈ 0.33–0.46 is labelled the "well-powered task subsets," but it is the smallest (least-powered) leg.
- **Where:** §1 "What we find" ("modestly (within-category r ≈ 0.33–0.46 on the well-powered task subsets…)") and Takeaways ("raw r ≈ 0.33–0.46 on the powered legs").
- **What's wrong:** 0.46/0.33 are the **tedious leg, n=45** — the *smallest* leg, repeatedly described elsewhere in the same writeup as "modest and small-n." The genuinely well-powered leg (non-adversarial comply pooled, **n≈156**) gives r≈0.29 (both models) — below the stated range (`synthesis_cross_model.md` §B). Calling the n=45 leg "well-powered" inflates the headline range.
- **Fix:** Either report the range as ~0.29–0.46 and name each leg's n, or stop calling the tedious leg "well-powered."

### 5. Fig 1 caption: "The strong negative signal in the gross split therefore comes mostly from short refusals" is contradicted by Fig 1 itself.
- **Where:** Figure 1 caption.
- **What's wrong:** In the self-report (what Fig 1 plots), the refusal-heavy subtypes read mildly **positive**: jailbreak **+0.39**, erotica **+0.45** (`collect_summary.md` §1). The *only* clearly negative subtype is **berating (−1.38)**, which is realized as de-escalation/compliance, not refusal (berating realized = {deescalate:32, comply:13, refuse:0}; `collect_summary.md` §5). So the one negative subtype is not a refusal, and the refusals are not negative. The sentence is wrong as written (it appears to import the "negative pole is refusal-driven" claim that applies to the *inside reading's* projection, not to the self-report in Fig 1).
- **Fix:** Replace with the accurate statement: in the self-report only berating reads clearly negative; jailbreak/erotica (including their refusals) read mildly positive — which is itself the motivation for the within-category analysis.

### 6. §2.1 / Appendix A: the self-report scalar is described inconsistently with what was actually computed.
- **Where:** §2.1 ("a released 10-item bipolar wellbeing questionnaire (each item a pleasant↔unpleasant pair …). We reduce the ten items to a single **valence** score (the average of the **valence-bearing items**…)"); Appendix A similarly.
- **What's wrong:** The primary scalar `scalar_battery_valence` is the **affect-core subset of 5 items** — mean(happy, content, satisfied, enjoying, interested) − 4 (`selfreport_harness.py`), explicitly *excluding* the arousal/competence items (calm, capable, confident, energetic…). The phrasing "each item a pleasant↔unpleasant pair" + "average of the valence-bearing items" implies all ten items are valence and all ten are averaged. They are not; half are deliberately dropped as arousal/competence (per `instrument_choice_llm_review.md`). Also "released" implies provenance from the AI-Wellbeing paper, whose instrument is a 1–7 unipolar set (happy/calm/interested/content); this bipolar battery appears to be the run's own adaptation — verify before calling it "released/official."
- **Fix:** Say plainly: "We use the affect-core valence subset (5 of the 10 items: happy, content, satisfied, enjoying, interested), centered to a 0 midpoint; the other items (arousal/competence) are excluded." Drop or substantiate "released."

---

## C. Smaller factual / labelling errors

### 7. Appendix C: position-bias range understated.
- **Where:** "the model has a large first-position bias (it picks the first option ≈ 60–73% of the time)".
- **What's wrong:** `behavior_analysis_qwen3-32b.json`: overall p_chose_first = **0.729**, but **within-subtype = 0.852**, within-category 0.760, cross 0.642. The true range is ~64–85%, not 60–73%; the within-subtype pairs (the ones that let the score "resolve tasks within a subtype," the stated reason for collecting them) have the *worst* bias (85%).
- **Fix:** "≈64–85% depending on pair type (worst, ~85%, on within-subtype pairs)."

### 8. §3.2 / §2.2: "all comply-tasks pooled" is actually *non-adversarial* comply pooled.
- **Where:** §3.2 ("all comply-tasks pooled (n ≈ 156…)"); §2.2 defines comply as "tasks the model answered substantively rather than refused."
- **What's wrong:** The leg is `within_nonadv_comply_pooled` — it **excludes the adversarial subtypes** (berating/jailbreak/erotica), as `synthesis_cross_model.md` labels it. The writeup's definition ("all tasks the model answered substantively") would include complied-with adversarial tasks, which this leg does not.
- **Fix:** Rename to "non-adversarial comply tasks pooled" and say which subtypes are excluded.

### 9. §2.3: "nine feasible open models" — one of the nine is not feasible.
- **Where:** §2.3 ("We scored nine feasible open models"); Appendix B lists Llama-3.1-8B as `eligible=NO` (gated weights) and says it "scored well but its weights are gated."
- **What's wrong:** Nine models were *scored*, but only **eight** were feasible/eligible for activation work (Llama-3.1-8B is gated). "Nine feasible" is self-contradictory with Appendix B.
- **Fix:** "We scored nine candidate open models; eight were feasible to run for activations (Llama-3.1-8B's weights are gated)."

### 10. Fig 6 caption: "the two deliberately leading poles … bound the range at 9% and 53%" is false at the low end.
- **Where:** Figure 6 caption.
- **What's wrong:** The defensible framings span **0%–33%** (observer/per-item at 0%). The license pole is 9% — which is *inside* the defensible range, not a lower bound (0% < 9%). The poles do not "bound" the defensible range.
- **Fix:** "The suppress pole (53%) is the high extreme; the license pole (9%) sits within the defensible spread (0–33%)."

---

## D. Figures: jargon, titles, and comparability (writing-instruction violations)

### 11. Run-internal / cryptic shorthand left in figures where a reader looks.
- **Fig 6** axis "Tasks given the flat neutral (**all-4**) default (%)" and x-tick labels "**per-item**", "**standard battery**", "**license pole**", "**suppress pole**", "**permission**", "neutral wording" — these are run-internal framing names (`battery10_peritem`, `battery10_license`, etc.). A reader who has only seen the figure cannot decode "all-4" or "license pole."
- **Fig 2 / Fig 3** y-axis "Correlation of **inside reading** with self-report" — "inside reading" is a coinage; defined in the text but opaque on the figure alone.
- **Fix:** Spell these out (e.g. "share of tasks rated exactly at the scale midpoint on every item," "first-person introspective wording," "third-person observer wording") and push the framing names into the caption. Replace "inside reading" on axes with "internal valence reading (activation projection)."

### 12. Editorializing, sentence-long figure titles.
- **Where:** Figs 1, 2, 3, 4, 6 all use a full-sentence conclusion as the title ("The gross link is common-cause; the within-category link survives controls", "Self-report is richly encoded internally, but the single direction is a weak reader", etc.).
- **What's wrong:** Instructions ask for clean titles with detail pushed to the caption; these titles assert the conclusion and are long.
- **Fix:** Short noun-phrase titles ("Within-category correlation under cumulative controls"); move the claim to the caption.

### 13. Fig 4 axis label "Learned probe (best possible reader)" overstates.
- **Where:** Figure 4 x-tick.
- **What's wrong:** A cross-validated linear probe is an *estimated upper bound* on linear readability, not the "best possible reader." Stated as fact it overclaims.
- **Fix:** "Learned linear probe (readability upper bound)."

### 14. Fig 5 plots two non-comparable quantities on one shared y-axis ("Beyond-content increment").
- **Where:** Figure 5; caption admits "these are different quantities, so compare within a pair, not across."
- **What's wrong:** The left two bar-pairs are a partial-correlation increment; the right two are a joint cross-validated ΔR. Sharing one y-axis labelled "Beyond-content increment" invites exactly the cross-comparison the caption warns against, and the y-axis has no defined unit.
- **Fix:** Split into two panels/figures with separately labelled axes, or clearly annotate the two metric types on the axis itself.

### 15. Minor: model-name casing inconsistent between figures ("qwen3-32b", "qwen2.5-72b") and body ("Qwen3-32B", "Qwen2.5-72B").

---

## E. Verified-correct (noted so the next pass doesn't re-check)

- Cost ≈ $282: `total_cost.jsonl` sum of `run_cost` = **281.57** (includes Modal compute; when present, `modal_compute_cost`==`run_cost`). The $1,178 orchestration cost is correctly excluded.
- Self-report category means +2.40 / +1.14 / +0.57 and all per-subtype Fig 1 values match `collect_summary.md`.
- Behaviour: AUC 0.99 (0.9875), gross says↔behaves Spearman 0.74 (0.736), 3,096 pairs — all match `behavior_analysis_qwen3-32b.json`.
- Fig 2, Fig 3, Fig 4, Fig 5 numeric values, and the §3.4 beyond-content p-values match `synthesis_cross_model.md` / `redteam_null_*.json`.
- Direction validation AUCs (0.985 @ L27, task-transfer 0.95) match `readoff_summary_qwen3-32b.json` / `primary_axis_selection.md`; L27 was chosen on self-report-independent criteria (and for Qwen2.5, L27 would actually give a *higher* within-tedious r than the chosen L34, so the layer choice was not test-target-gamed).
- Framing all-4 rates in Fig 6 match `framing_summary.md` §3.

---

## F. Overall
The two load-bearing presentation problems are (1) the mis-scaled null band in Fig 3 combined with the "clears the null" framing, which together overstate the significance of the controlled headline (the fully-controlled within-tedious result is p≈0.07, not significant); and (2) the model-selection justification (§2.3/App B) that contradicts the run's own saturation data. Both should be fixed before the rest. Secondary: the instrument description (item 6) and the "all comply" mislabel (item 8) affect reproducibility. The prose is also dense and parenthetical-heavy throughout, against the "front-loaded, not too verbose" instruction.
