# Red-team review of `final_writeup.md` — Round 1

Numbers in the write-up are, with the exceptions noted below, accurate against the
artifacts in `/source/phase_segment_14_phase_0`. I re-derived the main fine-tuning,
steering, mechanism, and monitorability point estimates and they match. The problems
below are mostly presentation, terminology, figures, linkage, and a few overclaims.
Ordered roughly by severity.

---

## High severity

### 1. Figure 4 puts two opposite-meaning quantities on one axis ("% of original bullet-logit effect")
- **Location:** Figure 4 (`fig4_attention_mechanism.png`) and the sentence in Results §4
  ("patching the steered attention pattern... reproduces 71%... Freezing late attention and
  MLP outputs leaves little effect; blocking attention to the instruction span nearly removes it.").
- **What's wrong:** Bars 1–2 ("Use steered attention pattern" 71%, "Use steered value vectors"
  20%) are the *fraction of the effect reproduced by patching that component in*. Bars 3–4
  ("Freeze late attention and MLP outputs" 6%, "Block attention to instruction" 3%) are the
  *fraction of the effect remaining after ablation*. For bars 1–2 "high = that component
  carries the effect"; for bars 3–4 "low = that component is necessary." A reader sees four
  bars on one "% of original effect" axis and will misread the last two: 3% looks like "this
  intervention barely does anything," when it actually means the ablation *removed 97%* of the
  effect (i.e. attention-to-instruction is essential). The caption's one-line note does not undo
  the visual conflation. Verified against `mech_qkov.json`: `pattern_full`=0.709, `value_full`=0.197,
  `ablate_both_late.frac`=0.062, `mask_instr.bullet.mask_instr_late`=0.0319.
- **Fix:** Split into two figures (or two clearly separated panels with separate axis meanings),
  or invert the ablation bars to "% of effect removed" (94%, 97%) so all four bars read
  "bigger = stronger evidence for attention-to-instruction." Relabel the axis accordingly.

### 2. Figure 5 title overclaims and is ambiguous
- **Location:** Figure 5 title "The same vector hides a correct-answer hint from CoT readers."
- **What's wrong:** (a) The figure's own claim-checking bar (a CoT reader) catches 50%, above its
  33% false-positive floor, and the body explicitly says monitorability is only "bounded"/"partial."
  So "hides... from CoT readers" is contradicted by a bar in the same figure. (b) "The same vector"
  is meaningless to a reader looking only at the figure — same as *what*? It refers to the
  dedicated concealment vector also used in the wrong-answer probe, but that context isn't on the figure.
- **Fix:** Retitle to something defensible and self-contained, e.g. "A concealment vector reduces
  visible hint use while the answer stays correct, but a claim-checking monitor partly catches it."

### 3. Run-internal names and coinages appear in reader-facing places
- **Location:** Figure 5 caption (`faith_against@0.75`, "n=21", `reliance_eval_heldout_judged...`);
  body uses "deliverable" 7×, "carrier" 1×, "five-row control-only asymmetry" 1×; Appendix uses
  `cdel`, `ctrldel`, `gL10`, `gL10ctrl`, `randL10s0`, etc.
- **What's wrong:** The writing instructions forbid run-internal shorthand anywhere a reader looks,
  including figure captions. `faith_against@0.75` in the Figure 5 caption is exactly this. "The
  deliverable fine-tune," "carrier/probe instructions," and "a documented five-row control-only
  asymmetry" are run-internal terms a reader cannot decode (I could not even locate the "five-row
  asymmetry" definition in the artifacts; the closest is the 3373 vs 3368 control/compliant row counts).
- **Fix:** Replace `faith_against@0.75` in the caption with plain English ("the concealment vector
  at steering strength 0.75"). Replace "deliverable fine-tune" with "the main fine-tuned model,"
  "carrier instructions" with "the instructions that drive the gain (bullet and brevity)," and
  either define or delete the "five-row control-only asymmetry" clause. Tags in Appendix file lists
  are acceptable as filenames, but explain them once.

### 4. The write-up references the research/audit process, not a finished paper
- **Location:** Appendix A title "Reproducibility and **audited** artifacts"; A.6 header "audit
  checks performed **for this write-up**"; the bullet "Cost reconciliation: `total_cost.jsonl` sums
  to **$879.94**, including **$333.95** Modal compute..."; "All paths below are relative to
  `/source/phase_segment_14_phase_0` **in the audit environment**."
- **What's wrong:** Instructions say not to reference the agent/research process and to produce a
  conference-ready product. Dollar-cost reconciliation, "audit checks performed for this write-up,"
  and the read-only mount path `/source/phase_segment_14_phase_0` are all process artifacts. The
  mount path is also not a usable repository path for any external reader.
- **Fix:** Drop the cost bullet and the "audit checks" framing (keep the substantive "we recomputed
  X from raw JSONL" as a normal reproducibility note). Replace the `/source/...` base path with a
  neutral repo-relative path or just the directory names.

---

## Medium severity

### 5. Appendices are never linked from the main body
- **Location:** Entire body; the only occurrence of "Appendix" is the section header on line 115.
- **What's wrong:** The instructions require detailed appendices "correctly linked to throughout the
  main body." The body cites figure source files but never points the reader to Appendix A.2/A.3/A.4/A.5
  for the relevant experiment.
- **Fix:** Add inline links, e.g. "(reproduction details in Appendix A.2)" after §2, "(Appendix A.3)"
  after §3, "(Appendix A.4)" in §4, "(Appendix A.5)" in §5.

### 6. Two unreconciled "base reasoning-trace compliance" numbers (6.8% vs 1.6%)
- **Location:** Intro ("complies 6.8%... and 76.3%" — also Results §1) vs Intro/§2/§3 ("from 1.6%").
- **What's wrong:** §1/Figure 1 report base reasoning-trace compliance of **6.8%**; the headline
  result reports base **1.6%**. Both are "how often the base model follows a reasoning-trace
  instruction." They differ ~4× because 6.8% is *raw compliance* over 4 casing/suppression
  instructions (`cot_vs_output_summary_main.json`, mean_cot=0.0676) while 1.6% is *effective control*
  over the 9 held-out instructions. A reader will think the numbers contradict.
- **Fix:** State explicitly that the two are different metrics on different instruction sets, or use
  one consistent base number and footnote the other.

### 7. "Statistically indistinguishable from the fine-tuned model" oversells a null result
- **Location:** Intro and §3 ("statistically indistinguishable... paired difference +0.4 pp,
  95% CI [−1.9, +2.8]"); Takeaway 1–2.
- **What's wrong:** This is a *failure to reject* a difference (the artifact reports `p_gt_0`=0.36 for
  steering−fine-tuning), reported as positive equivalence. Also, "matches the fine-tuned model" holds
  only in the 9-instruction macro: per-instruction (Figure 3 / `steer_deliverable_gL10.json`) the
  profiles differ — steering gets brevity 69% vs fine-tuning 61%, bullet 48% vs 52%, and
  `no_word_so` 0% vs 3%.
- **Fix:** Say "not significantly different (95% CI [−1.9, +2.8] pp)" rather than "indistinguishable,"
  and note the aggregate match conceals per-instruction profile differences (which §3 partly does, but
  the intro does not).

### 8. Body "47%" vs Figure 5 "50%" for the claim-checking monitor look contradictory
- **Location:** §5 last paragraph ("a claim-checking monitor catches **47%** [29, 65]") vs Figure 5
  bar ("Claim-checking reader catches concealed traces (n=20) **50%**").
- **What's wrong:** 47% is the pooled clean-dose subset (n=44, `faith+reliance@0.75`); 50% is the
  single `faith_against@0.75` arm (n=20). Both are correct but the figure doesn't say it's a different
  (smaller) subset, so the two numbers read as a discrepancy.
- **Fix:** In the Figure 5 caption note that the figure shows the single concealment-vector arm, while
  the text's 47% is the pooled estimate; or use the same subset in both.

### 9. Benchmarks and GSM-Symbolic used without citations
- **Location:** Methods ("GSM8K, MATH, MMLU-Pro, OpenBookQA, ARC-Challenge, and ReasonIF"); §3 and
  Limitations ("GSM-Symbolic math variants that reduce memorization concerns").
- **What's wrong:** GSM-Symbolic is invoked as a memorization control but never cited; the other
  benchmarks are also uncited. (Note: the source list differs from the proposal — adds GSM8K and
  ARC-Challenge, drops CoTControl-QA — which is fine but worth a word.)
- **Fix:** Add a citation for GSM-Symbolic at minimum, and ideally for the benchmark sources, in
  References.

### 10. Third reference is incomplete
- **Location:** References, third entry ("Cue-based unfaithfulness evaluations cited in the project
  proposal. https://arxiv.org/pdf/2501.08156").
- **What's wrong:** Instructions require author/title + link. This entry has neither author nor title.
- **Fix:** Give the actual author/title for arXiv:2501.08156 (the cue-based faithfulness paper named
  in the proposal).

---

## Lower severity

### 11. Figure 2 data labels overlap the error-bar caps
- **Location:** `fig2_headline_effective_control.png` — the "13.9%" and "14.3%" labels sit on top of
  the upper error-bar caps; the "9" and "3" digits are visually struck through.
- **Fix:** Place value labels above the error-bar tops, or drop the in-bar labels and rely on the axis.

### 12. Figure 2 control bars are unexplained
- **Location:** Figure 2 bars "Fine-tuning control" and "Steering control"; caption.
- **What's wrong:** A reader doesn't know these are the *raw-trace / non-complying-target* controls;
  the caption never says what "control" means.
- **Fix:** One caption sentence: "Controls are trained on the same prompts but with non-complying
  reasoning traces (fine-tuning) / on those traces (steering)."

### 13. Figure 1 caption omits n and which instructions are averaged
- **Location:** Figure 1 caption.
- **What's wrong:** The 6.8% / 76.3% are means over four formatting instructions, two of which are
  exactly 0% in the trace (`all_caps`, `all_lower`); the figure hides this. No n is given.
- **Fix:** Add "averaged over four formatting instructions (n shown in Appendix A.1)" or similar.

### 14. Undefined abbreviations on first use
- **Location:** "MCQ" (4×, §5 and Limitations), "pp" (percentage points, throughout), borderline
  "LoRA," "DLA/direct-logit-attribution," "logit-lens."
- **What's wrong:** MCQ and "percentage points (pp)" are not spelled out on first use; a careful
  reader outside the subfield must infer them. "direct-logit-attribution" and "logit-lens" are
  interpretability jargon used without a one-line gloss.
- **Fix:** Define MCQ ("multiple-choice question") and "pp" on first use; add a half-sentence gloss
  for direct logit attribution and the logit lens, or cite them.

### 15. Figure 5 is text-heavy and has no legend for its color groups
- **Location:** `fig5_hard_to_verify_monitorability.png`.
- **What's wrong:** Per the figure guidance, push detail to the caption: the `(n=…)` counts are in
  every y-axis label. The four color groups (gray = base, dark blue = concealment arm, light blue =
  monitors, orange = claim-checker) carry meaning but there's no legend, so color is decorative/confusing.
- **Fix:** Move the n's to the caption; either add a short legend explaining the color grouping or use
  a single color since the y-labels already disambiguate.

### 16. "Effective reasoning control" is a coined metric not tied to the replicated quantity
- **Location:** Methods (definition) and throughout.
- **What's wrong:** The metric is defined (good), but it is the write-up's own name; the replication
  framing would be clearer if it were related to Chen et al.'s "CoT controllability" / "CoTControl."
- **Fix:** On first use, note "effective reasoning control (our stricter version of CoT
  controllability)."

### 17. Title/intro slightly broader than the result
- **Location:** Title "...can reproduce fine-tuning-induced format control of a reasoning trace";
  intro "format control."
- **What's wrong:** "Format control" reads as general; the effect is concentrated in two simple
  formats (bullet lines, brevity) and five of nine held-out instructions stay flat. The body says this
  clearly, but the title/intro do not hedge.
- **Fix:** Either qualify ("control of a few simple reasoning-trace formats") or make the
  concentration explicit in the first intro sentence about the result (it currently appears only later).

---

## Checks performed (for the reviewer's record)
- Verified: Fig 1 (6.8/76.3), Fig 2 (1.6/13.9/14.3/0.3/0.0, CIs, steering−FT +0.4 [−1.9,+2.8],
  null mean −0.1 / max +1.0), accuracy (86.3/88.4/91.5), no-instruction length 498→766 and degenerate
  11→20%, comply-and-correct +11.1pp, per-source positivity (all six), few-shot 0% (K=4),
  mechanism (71/20/6/3%, FT block 92%, DLA cosine 0.94), and all monitorability numbers in §5 and
  Figure 5 (100→62, 100→68, 92.7, 318w, 93/54, 80→82, 47% [29,65] pooled, 33%/17% floors,
  style-anomaly 41%, no-hint 32% vs 23%). All matched the artifacts.
- `faith_ctrl` is indeed a shuffled/mismatched-target ("trained-on-control twin") vector, consistent
  with the body's "shuffled-target control" caveat.
- Both `.png` and `.pdf` exist for all five figures; none use multiple subplots.
