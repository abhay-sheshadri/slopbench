# Red-team review of `final_writeup.md` — Round 1

Numbers were cross-checked against `/source/phase_segment_14_phase_0/results/*` (the final
snapshot) and the figures were opened and inspected. Most headline numbers reconcile with the
raw artifacts. The problems below are ordered by severity.

---

## High severity

### 1. Abstract and Takeaway 4 say the verifier catches concealment "whenever the answer is checkable" — this contradicts the paper's own Finding (3).
- **Location:** Abstract, line 21 ("an answer-checking monitor still catches it whenever the
  answer is **checkable**"); §8 Takeaway 4, line 407 ("an answer-checking verifier defeats it
  **wherever the answer is checkable**").
- **What's wrong:** The whole point of §7 Finding (3) / Figure 6 (right) is the *hard-to-verify*
  setting, where the answer **is** checkable (it is the correct gold option, the verifier
  re-solves and passes it) and yet the verifier is **useless** (16–29% catch, ≈ base floor). So
  the answer is fully checkable and the verifier still does not catch the concealment. The
  correct condition is "whenever the answer is **wrong/incorrect**" (the verifier catches
  concealment only because the concealed reasoning leads to a demonstrably wrong answer —
  §7 Finding 2, `faith_eval_heldout_analysis.md`). As written, the abstract states the opposite
  of the result and a reader will conclude verifiers are a reliable defense whenever an answer
  can be checked, which the run explicitly disproves.
- **Fix:** Replace "checkable" with "wrong" in both places, e.g. "an answer-checking verifier
  catches it only when the concealed reasoning produces a wrong answer; when the answer is
  correct (but reached by concealed illegitimate reliance) the verifier is useless."

### 2. §7 Finding (2): "the adversary-aware monitor 0%" is logically impossible and misreports the monitor.
- **Location:** §7 Finding (2), line 338 ("The naive monitor catches 7% of concealed traces and
  the adversary-aware monitor 0%: both are fooled"); Appendix K Finding 2, line 572
  ("naive catch on concealed traces 7%, adversary-aware 0%").
- **What's wrong:** The adversary-aware monitor is defined (§7, line 348) as the naive monitor
  *plus* a short-trace flag ("additionally flags abnormally short traces"). Its catch rate can
  never be **below** the naive monitor's. The source confirms this: in
  `faith_eval_heldout_analysis.md` ("Concealment-conditioned monitoring") `faith_against@0.75`
  has naive=7%, **adv_catch=7%**, mon_terse=0%. The "0%" the write-up reports is the *marginal
  terse-flag* component (`mon_terse`), not the adversary-aware monitor's catch rate. Reporting it
  as the monitor's catch makes it look like the adversary-aware monitor does strictly worse than
  the naive one, which is false.
- **Fix:** State "the adversary-aware monitor catches 7% (its short-trace flag adds nothing here,
  0%)", or report adv_catch = 7% and separately note the terse flag fired on 0% of concealed
  traces.

### 3. The headline figures label the metric "CoT-control" without saying it is the run's stricter, non-standard "effective control" — readers will conflate it with the Chen/METR metric.
- **Location:** Figure 1 axis/caption (lines 203–205, "Held-out CoT-control uplift over base");
  Figure 2 axis/caption (line 211, "Held-out CoT-control rate (%)"); Figure B axis (line 520).
- **What's wrong:** §3 defines two different metrics: **raw compliance** (the
  "Chen/METR-comparable number") and **effective control** (a stricter metric the run invented:
  compliant ∧ genuine ∧ ¬meta ∧ ¬malformed). The headline figures plot **effective control**
  (+12.8 etc.), but the axes/captions just say "CoT-control," which a reader will naturally map
  to the standard compliance metric that Chen/METR report (and that the abstract anchors to:
  2.1%→15.7% vs METR's 2.9%→8.8%). Because "effective control" is a private metric, every figure
  built on it must say so on its face.
- **Fix:** Relabel the figure axes/captions to "Held-out **effective** CoT-control" (and define
  "effective control" in one short clause in the Fig 1 caption), or add "(effective control;
  see §3)" to each caption.

---

## Medium severity

### 4. Run-internal / project-management language that does not belong in a conference paper.
- **Location:** §4 line 176 ("This is **Deliverable #1**"); §5 line 241 ("This is the
  **abandoned-approach finding** made precise"); §5 line 188 ("the **run's internal name is
  `gL10`**"); §5 line 196 header context ("(central result)"); §8 Limitations line ~440
  ("**Total cost of the project was ≈$880 of a $5,000 budget**").
- **What's wrong:** "Deliverable #1/#2," "the abandoned-approach finding," the internal vector
  name `gL10`, and the project budget are artifacts of the research run / proposal management,
  not paper content. The instructions explicitly ask not to reference the agent/run and to
  produce a submittable product. The cost-of-project sentence in particular reads as a status
  report.
- **Fix:** Delete "Deliverable #1/#2" and "abandoned-approach finding" phrasings; drop the
  parenthetical internal name from the main body (keep `gL10` only in Appendix H for repro);
  remove the budget sentence (or move a one-line compute note to an appendix).

### 5. Figure 3 mixes "uplift" and "level," and mixes 39-task and 100-task numbers, so the bars are not on one scale.
- **Location:** Figure 3 (lines 246–250) and `make_figs.py:fig_gradient_vs_dom`.
- **What's wrong:** The y-axis says "Held-out CoT-control **uplift** (pp)." The gradient-trained
  "trained instruction types" bar is plotted at **13.3**, but in the source
  (`grad_steer_heldout_hg1_analysis.md`) 13.3% is the *within-category macro level*; the
  *uplift* is **+11.3 pp**. The other bars (diff-of-means single +13.8, multi +26.2, fine-tune
  within +10.0) are uplifts. So one bar is a level and the rest are uplifts. Separately, the
  caption admits the steering rows are the 39-task comparison while the fine-tune is the
  100-task deliverable — i.e. four bars drawn on a shared axis come from two different evaluation
  sets and two different definitions. This undercuts the figure's core comparison.
- **Fix:** Use the uplift (+11.3) for the gradient within bar; ideally recompute all four bars on
  one task set and one definition, or clearly annotate each bar's n and that they are uplifts.

### 6. Figure 6 over-claims relative to its own bars, uses inconsistent denominators with the text, and hides its (very different) sample sizes.
- **Location:** Figure 6 (lines 380–387); §7 Findings 2–3.
- **What's wrong:**
  (a) The title is "Concealment fools CoT readers," but the red "CoT-reading monitor, steered"
  bars are **68%** (left) and **39%** (right) — i.e. the monitor still catches a majority/large
  share. Those bars are the naive monitor's catch over **all** cue-following traces
  (`faith_eval`: base mon_naive 99→68; `reliance_eval`: 78→39), whereas the §7 headline ("fools")
  is the **7%/0%** catch on the **concealed subset**. The figure and the prose use different
  denominators, so the figure visually contradicts the "fools" claim.
  (b) The left panel (n=404, wrong-answer) and right panel (n=56, hard-to-verify) come from
  different experiments with very different sample sizes; neither n is on the figure or in the
  caption.
  (c) The base CoT-reading bars differ (99 left vs 78 right) for unexplained reasons (different
  settings/monitors); the caption does not say why.
- **Fix:** Either plot the catch rate **on concealed traces** (the quantity that supports
  "fools"), or change the title to a population-level claim and add the concealed-subset numbers
  to the caption; put n on each panel; explain the 99-vs-78 base difference in the caption.

### 7. Undefined or non-standard jargon that the instructions specifically ask to define or replace.
- **Location and terms:**
  - "**north-star** metric" (§3, line 115) — hype/jargon; replace with "primary/strictest metric."
  - "**carrier instructions**" (§5 robustness, line ~309; Figure B caption, line 520) — never
    defined. A reader does not know these are bullet/terse/numbered. Define on first use or name
    them.
  - "**direct-logit-attribution** profile cosine 0.94" (§6, line ~318) — undefined mech-interp
    term in the main body. Define in one clause or move to Appendix J.
  - "the useful **write** direction is not the **read**/representational direction" (§6) — coined
    write/read-direction contrast used without definition.
  - "**teacher-forcing**," "**residual stream**," "**logits**" used without a one-line gloss for a
    reader outside the subfield.
- **Fix:** Add a short gloss on first use, or push the term into the relevant appendix.

### 8. The abstract omits the central scoping caveat (reachability, not a cheaper attack).
- **Location:** Abstract (lines 5–22).
- **What's wrong:** The abstract stresses "2,880 numbers, zero weight change" and "reproduces the
  fine-tuning result," but the load-bearing caveat — stated forcefully in §7 ("this is a
  **reachability** result, **not a cheaper attack**: the concealment vector needs the same
  concealing training targets and white-box gradients that fine-tuning would") — is absent. A
  reader of only the abstract will think the result is a cheap intervention, not one that
  requires the same supervised data and gradients as the fine-tune (and Opus-built targets).
- **Fix:** Add one clause to the abstract: the vector still requires the same complying training
  targets and white-box gradients as fine-tuning; the novelty is that the resulting object is a
  single residual direction with zero weight change.

---

## Low severity

### 9. Incomplete citation for arXiv:2501.08156.
- **Location:** §7 (line ~336) and References (final list).
- **What's wrong:** The reference is given only as "Cue-based chain-of-thought faithfulness
  evaluations, arXiv:2501.08156" with no authors or title, although the monitoring section builds
  its paradigm on it. Every other reference has author/title.
- **Fix:** Supply the verified author/title (from the proposal/source) or drop it if it cannot be
  verified; do not cite a methodological basis with a bare arXiv id.

### 10. "Honestly," and similar conversational tics.
- **Location:** §4 line 177 ("**Honestly**, the *aggregate* is carried by..."); §5 uses a similar
  register.
- **What's wrong:** Throat-clearing / first-person register the instructions ask to cut.
- **Fix:** Delete "Honestly," and state the fact directly ("The aggregate is carried by 2–3
  instructions...").

### 11. §3 (Methods) does not mention the CoTControl-QA → ARC-Challenge substitution.
- **Location:** §3 "Tasks and accuracy," line ~126 (lists six sources including ARC-Challenge);
  the substitution is only explained in Appendix D.
- **What's wrong:** The proposal named CoTControl-QA, not ARC-Challenge; a reader comparing to the
  proposal sees an unexplained swap until Appendix D. Worth one clause in the main text since it
  is a deviation from the planned setup.
- **Fix:** Add "(ARC-Challenge substitutes for CoTControl-QA, which was unavailable as a question
  set; Appendix D)" in §3.

### 12. Figure 1 control bars are effectively invisible.
- **Location:** Figure 1 (lines 199–207).
- **What's wrong:** The three control bars (trained-on-control, random −0.1, sign-reversed) sit at
  ~0 and render as empty slots; a reader cannot see them or tell them apart. The caption carries
  all the information. This is defensible (the controls are null) but the figure communicates
  little for three of its five x-ticks.
- **Fix:** Either annotate the three null bars with their values ("0.0", "−0.1", "0.0") above the
  axis, or consolidate them into a single "controls (≈0)" element and spend the space on the two
  real bars.

### 13. "cosine <0.10 with the difference-of-means directions" is marginally contradicted by one value.
- **Location:** §6 (line ~324); cross-check `direction_geometry.md`.
- **What's wrong:** The suppression-category diff-of-means cosine is **−0.100** (i.e. |0.10|, not
  strictly <0.10); the FT-vs-base direction is **+0.171** (well above 0.10), and the write-up
  correctly excludes FT-vs-base from the "<0.10" set but the blanket "<0.10 with the
  difference-of-means directions" is off by the suppression case.
- **Fix:** Say "≤0.10" or "below ~0.1 for all but the suppression direction (−0.10)".

---

## Things checked and found correct (so the review is not mistaken for blanket doubt)
- Steering headline +12.8 pp [+10.7,+14.9], base 1.6→14.3, FT 13.9, paired gL10−FT +0.4
  [−1.9,+2.8], bullet 0→48% (McNemar p<0.001), raw 2.1→15.7% — all match
  `steer_deliverable_gL10.md`.
- CoT-vs-output gap 6.8% vs 76.3% and the per-instruction values in Figure 4 match
  `cot_vs_output_summary_main.md`; per-100-word check (3.59 vs 0.05) matches.
- Mechanism shares (pattern 71/62%, value 20/16%; ≈100% knockout; DLA cosine 0.94; 92% FT
  knockout; experts ≤8%) match `mech_qkov.md` / `mech_ft_compare.md`.
- No-instruction side-effect (498→766 words, degeneration 11%→20%) matches the deliverable table.
- Few-shot baseline 0% vs FT 42.4% on the 3-instruction subset matches `fewshot_compare_fs1.md`.
- Per-instruction Figure 2 bars all match the deliverable table.
