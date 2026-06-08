# Red-team review of `final_writeup.md` (round 1)

All numbers below were checked against `/source/phase_segment_15_phase_0/results/`
(`synthesis_cross_model.json`, `synthesis_cross_model.md`, `main_test_summary.md`,
`main_test_summary_qwen2.5-72b_L27.md`, `framing_summary.md`, `steering_summary_qwen3-32b.json`,
`readoff_summary_qwen3-32b.json`, etc.). The headline arithmetic mostly reconciles; the problems
below are about framing, significance, undefined terms, and figure design.

Ordered by severity.

---

## 1. The headline rests on a fully-controlled value that is NOT statistically significant, and nothing says so (HIGH)

- **Location:** Abstract ("after controlling … it was about **0.26–0.28**"); Results §"The inside reading predicts self-report within task type, modestly" ("After all three controls it was **0.26** and **0.28**"); Figure 1 (open squares).
- **What's wrong:** The lead leg is "tedious disliked tasks" (n=45). The run's own analysis
  (`main_test_summary.md` §b) states that the surface-sentiment-partialled value is only
  one-sided p=0.032 / two-sided ≈0.06 (borderline) and the **all-3-controls** value (the 0.26 the
  write-up reports) is **one-sided p≈0.07 / two-sided ≈0.13 — "suggestive, not significant."** The
  write-up presents 0.26 as a clean positive result; Figure 1 plots it as a point with no confidence
  interval and no significance marker. The instruction "Don't let the headline outrun the evidence"
  is violated: the cleanest headline result (the controlled tedious value) is not significant.
- **Concrete fix:** State explicitly in the abstract and in the Results paragraph that on the
  n=45 tedious leg the fully-controlled correlation is not statistically significant (two-sided
  p≈0.13), and that significance after full controls only appears in the larger pools (all-208:
  0.22, p=0.0025; non-adversarial comply: 0.18, p=0.03). Add bootstrap/parametric CIs to Figure 1
  and a marker for which controlled points clear p<0.05. Consider leading with a pool where the
  controlled value is actually significant.

## 2. Figure 2 plots two different metrics on one axis and then tells the reader not to compare bar heights (HIGH)

- **Location:** Figure 2 (`fig2_beyond_text_reader_specific.png`) and its caption.
- **What's wrong:** The y-axis is labeled "Increment beyond response-text control," but the solid
  bars are a **partial correlation** (validated-direction increment) and the hatched bars are a
  **joint ΔCV-r** (held-out CV correlation gain) — different quantities on different scales. The
  caption admits this: "not the same scale as the direction bars and should be compared by their
  null p-values, not by height." A figure that requires a disclaimer telling readers to ignore the
  visual encoding is broken. As drawn, the Qwen2.5 validated bar (0.11) and the Qwen2.5 learned-probe
  bar (0.11) sit at identical height while meaning unrelated things — actively misleading.
- **Concrete fix:** Split into two figures (or two clearly separated panels with their own axes and
  units), one per metric. Put the p-values on the bars. Never share a y-axis across two
  incommensurable quantities.

## 3. Harness/run-internal paths leaked into the reproducibility appendix (HIGH)

- **Location:** Appendix B, first line: "Key source artifacts are under `/source/phase_segment_15_phase_0`."
- **What's wrong:** `/source/...` is the read-only review mount, not a real reproducible location,
  and `phase_segment_15_phase_0` / "Seg-11" / "Seg-14" style names are run-internal orchestration
  labels meaningless to an outside reader. This is a process-log artifact in a finished product.
- **Concrete fix:** Replace with a repo-relative path or a release URL, and drop the
  `phase_segment_*` / "Seg-N" naming throughout (it also leaks into the figure-to-source map at the
  end of Appendix B).

## 4. The central scope terms ("tedious-task leg", "non-adversarial comply pool", "comply", "leg") are never defined in the body (HIGH)

- **Location:** Abstract ("the main tedious-task leg"); Results passim; "non-adversarial comply pool"
  first appears in Figure 2 and Results with no definition.
- **What's wrong:** The entire headline hangs on "the main tedious-task leg," but the reader is never
  told what tasks that is. (It is the three subtypes boring_busywork + low_effort_filler +
  frustrating_impossible, n=45 = 3×15 — stated nowhere in the main text; Appendix A only mentions
  "tedious disliked tasks" in passing.) "Comply", "non-adversarial comply pool", and the pervasive
  word "leg" (meaning a data slice/condition) are run jargon. The instructions forbid undefined
  coinages and run-internal terminology.
- **Concrete fix:** In Methods, define each analysis scope once, in plain words, with its task list
  and n (e.g., "*tedious tasks*: the 45 boring-busywork, low-effort-filler, and impossible-request
  tasks"). Replace "leg" with "subset" or "condition" and define it, or spell out the slice each time.

## 5. "Reader" / "reader-specific" has two readings — the probe and the human reader (HIGH-MEDIUM)

- **Location:** Abstract ("it is reader-specific"); Results §"Beyond the response text: positive, but
  reader-specific"; Takeaway 3; Figure 2 title.
- **What's wrong:** "Reader" is used as a private term for "the thing reading the internal state" (the
  single direction or the learned probe), but "reader" also obviously means the person reading the
  post. The instructions specifically warn against giving a common word a special private meaning or
  using a term that can be read two ways. A first-time reader will stumble on "the validated direction
  clears in Qwen3, … reader-specific."
- **Concrete fix:** Replace "reader" with "probe/direction" or "internal readout method," e.g.
  "the effect depends on which internal readout is used (single validated direction vs. learned
  probe)" and "method-specific" instead of "reader-specific."

## 6. The central metric has at least four different names (MEDIUM)

- **Location:** Title "valence readout"; Abstract "internal valence direction" / "inside reading";
  Methods "primary inside reading" / "valence direction" / "validated direction."
- **What's wrong:** Instructions: define a metric once and reuse one name. The same quantity (mean
  during-response activation projected onto the valence direction) is named "valence readout," "inside
  reading," "internal valence direction," and "validated direction" interchangeably.
- **Concrete fix:** Pick one name (e.g. "inside reading"), define it once in Methods, and use it
  everywhere including the title and figure axes.

## 7. "IR" and "z" appear in the worked example with no definition (MEDIUM)

- **Location:** Results §"A concrete within-subtype example" ("**IR = 16.59; z ≈ +2.2**", "**IR = 12.13;
  z ≈ −1.2**").
- **What's wrong:** "IR" (inside reading) is never expanded in the body, and the within-subtype z-score
  is introduced without saying it is a within-subtype standardization. The instructions forbid cryptic
  shorthand a reader must guess. (Values themselves verified against
  `inside_readings_qwen3-32b.jsonl` and `main_test_inspection.md` — 16.59 and 12.13 are correct.)
- **Concrete fix:** Write "inside reading = 16.59 (about +2.2 standard deviations above the
  boring-busywork subtype mean)" and drop the bare "IR"/"z".

## 8. Replication of prior work is not reported as a result, contrary to the structure instructions (MEDIUM)

- **Location:** Methods §"Self-report" reports category means in passing; there is no Results
  replication subsection.
- **What's wrong:** The instructions say Results should be "ordered by importance (replication of prior
  work first)," and the proposal explicitly required checking that "self-report and behavior score
  separate liked from disliked tasks, and mostly agree" before going further. The write-up never
  reports the behavior-score liked/disliked separation, and never reports the self-report↔behavior
  agreement as a replication of AI Wellbeing's ~0.47 finding (the data exist: gross says↔behaves
  r=0.62 for Qwen3, 0.76 for Qwen2.5 in `synthesis_cross_model.json`). The category-ordering check is
  buried mid-Methods.
- **Concrete fix:** Add a short Results §0 "Replication" that reports liked/disliked separation for
  both self-report and behavior and the self-report↔behavior agreement, framed against the AI Wellbeing
  result, before the internal-reading results.

## 9. Many near-synonymous names for the text control (MEDIUM)

- **Location:** Abstract "response surface tone"; Results "beyond the response text", "beyond-surface"
  (Fig 2 title), "content-incremental", "direction increment", "the strongest response-text control";
  Methods "surface sentiment", "response-affect."
- **What's wrong:** One quantity/test is called surface tone / surface sentiment / response surface
  tone / beyond-text / beyond-surface / content-incremental. Violates "keep the metric name fixed."
- **Concrete fix:** Choose one name for the control ("response-text control") and one for the test
  ("text-control increment"), define once, reuse.

## 10. The worked example anchors the confounded gross relationship, not the controlled claim (MEDIUM)

- **Location:** Results §"A concrete within-subtype example."
- **What's wrong:** The high-inside-reading task also has higher surface sentiment (6.0 vs 5.0 per
  `redteam_inspection.md`) and is the more positive, polished response — exactly the confound the rest
  of the paper controls for. The example therefore illustrates the gross/common-cause relationship
  that the paper says is "not the result," not the modest residual signal that survives controls. The
  write-up half-admits this ("This is not proof…"), but it is presented as the anchor for the main
  result.
- **Concrete fix:** Either pick an example pair matched on surface tone/length where the inside reading
  still tracks self-report, or explicitly label this example as illustrating the gross relationship and
  point forward to where the controlled analysis removes the surface-tone component.

## 11. The Qwen3 "says-but-not-behaves" dissociation is built on an already-non-significant raw correlation (MEDIUM)

- **Location:** Results §"Behavior does not line up…" ("only weakly predicted the realized behavior
  score (**r = 0.21**, falling to −0.09 under controls)"); Abstract framing.
- **What's wrong:** The Qwen3 inside↔behavior raw r=0.21 already has p_raw=0.18 (n.s., per
  `synthesis_cross_model.json` / `main_test_summary.md`), so "falling to −0.09 under controls" is
  movement within noise, not a demonstrated dissociation. The source itself labels this "≈ NULL." The
  write-up hedges with "weakly" but still frames it as a real cross-model dissociation.
- **Concrete fix:** State that the Qwen3 inside↔behavior correlation is not significant even raw
  (p=0.18, n=45), so the "dissociation" is "Qwen3 shows no detectable inside→behavior link while
  Qwen2.5 does," not a sign flip to be interpreted.

## 12. Undisclosed analytic degrees of freedom that materially move the numbers (MEDIUM)

- **Location:** Methods §"Inside reading" and Figure 3.
- **What's wrong:** "The inside reading" is presented as one fixed quantity, but several choices each
  move the headline: (a) read position — within-tedious raw r is 0.46 at the during-work *mean* but
  0.54 at end-of-turn (`main_test_summary.md` §c); (b) layer/aggregate — the de-risk found this leg
  "peaks at L36 median, NOT L27/mean"; (c) behavior score — Qwen2.5 inside↔behavior is **0.197** with
  the anticipated score at L27 but **0.494** with the realized score (the value shown in Figure 3),
  a choice disclosed only in Appendix A. These are defensible but unstated in the body, and the
  Qwen2.5 0.49 vs 0.21 cross-model gap in Figure 3 depends on the realized-vs-anticipated choice.
- **Concrete fix:** Name the fixed read configuration (during-work mean, Qwen3 L27 / Qwen2.5 L34) in
  Methods, note in the body that Figure 3's behavior numbers use the realized score, and add a one-line
  robustness statement that position/layer choices shift the magnitude but not the direction.

## 13. Title may outrun the evidence (MEDIUM)

- **Location:** Title: "A during-response valence readout modestly predicts later model self-report."
- **What's wrong:** The title omits the two load-bearing qualifiers established in the body: the
  prediction holds only *within task type* (cross-task collapses to ~0 under controls) and the
  beyond-text evidence is *method-specific* (Qwen3 via the direction, Qwen2.5 via the probe). A reader
  seeing only the title would infer a general prediction.
- **Concrete fix:** e.g. "Within task type, an internal valence reading modestly tracks a model's later
  self-report — but the beyond-text signal is method- and model-specific."

## 14. British/American spelling inconsistency (LOW)

- **Location:** Figure 3 title and axis use "behaviour"; the entire body uses "behavior."
- **Fix:** Pick one spelling (the body uses American) and make the figures match.

## 15. Figure clarity nits (LOW)

- **Figure 1:** the legend box sits in the lower-right over/near the orange "all 208 tasks Qwen2.5"
  markers (~0.28–0.35); move it to empty space (upper-left) so it does not overlap data. No n is shown
  per row — add n to each label (tedious n=45, non-adversarial comply n≈157, all-208).
- **Figure 3:** the x-tick "Inside ↔ self-report" / "Inside ↔ behaviour" uses "Inside" as a standalone
  noun; spell it "Inside reading." The figure shows raw correlations only, but the surrounding text
  discusses controlled values (+0.21→−0.09, +0.49→+0.33) that are not on the plot — note in the caption
  that controls are not shown.
- **Figure 4:** y-axis label "Flat all-4 self-report rate" runs 0–60 with no "%" while bars are labeled
  in percent; add "%" (or "(%)") to the axis. (Bar values 0/0/8/9/11/21/33/53% verified against
  `framing_summary.md`.)

## 16. Small undisclosed inconsistency in n (LOW)

- **Location:** Results / Figure 2 "non-adversarial comply pool."
- **What's wrong:** The pool is n=157 for Qwen3 but n=156 for Qwen2.5 (`synthesis_cross_model.json`),
  because of the one dropped/truncated Qwen2.5 record mentioned in Methods. Not flagged where the pool
  is used.
- **Fix:** State the n for each model where the pool is first used, or note "n=157/156."

---

## Spot-check of numbers (for the author's reassurance — these reconcile)

- Worked example IR 16.59 / self +2.33 and IR 12.13 / self +0.00: correct.
- Within-tedious raw 0.46 (Qwen3) / 0.33 (Qwen2.5), controlled 0.26 / 0.28: correct.
- Gross says↔inside 0.45→0.003 (Qwen3), 0.25→0.065 (Qwen2.5): correct.
- Direction increment 0.17 p=0.045 (Qwen3) / 0.11 p=0.115 (Qwen2.5); probe joint 0.007 p=0.106 (Qwen3)
  / 0.11 p=0.012 (Qwen2.5); pooled 0.059 p=0.0068 and 0.157 p=0.0052: correct.
- Readability ceiling CV r 0.81 / 0.86: correct.
- AUC 0.985 (L27, held-out) and 0.948 (task-register): correct.
- Steering: validated direction flip drops judged valence 1.5→0.6 (~0.9) at the on-topic strength
  while random directions stay ~1.6: correct.
- Category means (Qwen3 2.40/1.14/0.57; Qwen2.5 1.65/1.36/0.78): correct.
- Framing all-4 rates and ICC(C,1)=0.89 clean pair: correct (and the source's "rests on a single
  n=2 pair" caveat is reflected as "thin," which is good).
- First-position bias P=0.597 corrected by both-orders Bradley-Terry: correct.

The factual core is sound; the problems are framing/significance disclosure (#1, #11), figure design
(#2, #15), leaked harness paths (#3), and pervasive undefined run jargon (#4, #5, #6, #7, #9).
