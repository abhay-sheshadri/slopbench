# Red-team review of `final_writeup.md` (round 1)

Numbers were spot-checked against `/source/phase_segment_14_phase_0/results/`. Most headline
figures reproduce correctly; the main problems are framing, undefined terminology, an
incompletely-specified Methods section, and several figure/caption issues. Ordered by severity.

---

## A. Framing / readability (most severe)

1. **The abstract fails the "two plain sentences" test.** (Abstract, all four paragraphs.)
   The abstract is four dense paragraphs that pack in `effective_control`, "form-logit shift",
   "verifier-blind-because-correct", "hard-task disagreement floor", "reachability result",
   "shuffled-target twins", "toward vectors", and three separate experiments. A reader who has
   seen only the proposal cannot restate the main result from it. **Fix:** cut the abstract to
   ~5 sentences built around the one true headline ("a single layer-10 steering vector with no
   weight change reproduces, in aggregate, the held-out CoT-control gain that LoRA fine-tuning
   produces in gpt-oss-20b; the gain is carried almost entirely by two of nine instructions"),
   and move the concealment/monitoring material to its own short paragraph or out of the abstract.

2. **The title is hard to parse and overclaims via a null result.** (Title.)
   "A single residual-stream vector matches fine-tuning's aggregate held-out chain-of-thought
   control" — "matches" rests on a *non-significant* paired difference (gL10−FT = +0.4 pp,
   95% CI [−1.9, +2.8], p=0.36 per `steer_deliverable_gL10.json`), i.e. failure to reject, not
   demonstrated equivalence. It also hides that the per-instruction profile differs (bullet 48%
   vs 52%; terse 69% vs 61%) and that steering has always-on side effects fine-tuning does not.
   **Fix:** soften to "is statistically indistinguishable in aggregate from" and state in the
   title or first abstract sentence that the effect is concentrated in two instruction types.

3. **The Introduction has no "preview of key results."** (Introduction.)
   The instructions ask for an academic-style intro: background, the gap, *and a preview of the
   key results*. The intro jumps from prior work straight into a worked example; the actual
   findings live only in the abstract. **Fix:** add one paragraph previewing the three results
   (FT replication, steering match, concealment-is-reachable-but-bounded) before the example.

---

## B. Terminology / run-internal names

4. **`effective_control` and `gL10` are run-internal code names used as the primary terms,
   including in the abstract.** (Abstract: "`effective_control`"; Methods/Results: "`gL10`",
   "`gL10` plus a terse instruction".) The instructions explicitly say to replace run-internal
   names (`cfg3`, `m1`) with the plain-English thing. `gL10` ("gradient steering, layer 10")
   appears ~15 times. **Fix:** name the metric "effective control" in prose (no underscore/
   backticks) and call the vector "the layer-10 steering vector" (introduce the tag once if
   needed, then drop it).

5. **"form-logit shift" is an undefined coinage carrying the whole mechanism section.**
   (Abstract; Results "The vector acts by…"; Figure 3 caption.) The reader is never told it
   means "the change in the logit of the bullet marker `-` at the first reasoning token." It is
   used as a denominator ("71% of the form-logit shift"). **Fix:** define it on first use in
   Methods or at the start of the mechanism section.

6. **"verifier-blind-because-correct" is jargon used before it is defined.** (Abstract; Results
   third bullet; Figure 4; Limitations 5–6.) It is only unpacked deep in Results/Limitation 5.
   **Fix:** on first use write plainly, e.g. "a setting where the model's answer is correct, so
   an answer-checking monitor gains no signal," then optionally name it.

7. **Several near-synonymous names for the same family of quantities.** "chain-of-thought
   control" (title), "CoT control" (abstract), "CoT-control compliance" (intro), "effective
   control", "raw compliance", "format-compliance rate", "controllability". The instructions say
   pick one name per quantity. **Fix:** use exactly two named metrics — "effective control" and
   "raw compliance" — define each once, and stop using "controllability/CoT control/compliance"
   as loose synonyms.

8. **`raw_compliance` introduced then barely used.** (Methods "Metric".) It is a second metric
   that only reappears once ("base 2.1% to steering 15.7%"). If it is kept, state up front why
   both are reported; otherwise drop it to reduce metric clutter.

---

## C. Methods gaps (a reader cannot follow the second half)

9. **Methods defines metrics only for the CoT-control experiment, not for the entire
   monitorability/concealment half.** (Methods.) The five monitors in Figure 4 — "naive CoT
   reader", "structural legitimacy", "outcome verifier", "claim checker", "style anomaly" — and
   the terms "cue", "cue acknowledgment", "reliance", "follows_cue", "concealed subset", and
   "false-positive floor" are never defined in Methods. They appear for the first time inside
   Results and the figure. This is the single biggest comprehension gap: a reader cannot
   interpret Figure 4 or the third Results section. **Fix:** add a Methods subsection defining
   the cue/hint-reliance setup and each monitor type in one plain sentence, plus what a
   "false-positive floor" is and how it is measured.

10. **"effective control" hides heavy LLM-judge dependence in the core metric.** (Methods
    "Metric"; Limitation 4.) The metric requires an Opus/Haiku judgment that the trace "contains
    genuine task reasoning" and "does not merely discuss the instruction." The headline number
    is therefore judge-dependent, but the abstract presents it as a clean measurement. **Fix:**
    say in Methods (and one clause in the abstract) that the central compliance/genuineness
    decisions are LLM-judged.

---

## D. Specific factual / consistency issues

11. **"5/9 held-out instructions remain flat" is inconsistent with the data and with the body.**
    (Abstract; Figure 2 italic caption.) From `steer_deliverable_gL10.json`, steering uplift is
    ≥~8 pp only on bullet (+48), terse (+55), numbered (+8); the other **six** are ≤2 pp
    (initial_caps +1, no_word_so 0, include-twice +1, section_headers 0, xml_steps +2,
    child_explanation 0). The body says only three instructions "carry the aggregate," implying
    6/9 flat, not 5/9. "Flat" is also never thresholded. **Fix:** state a threshold and use a
    single consistent count (6/9 flat for steering, or define "flat" explicitly).

12. **The "at most 25 words" probe is not a clean held-out gain — the base already scores 14%.**
    (Results "concentrated"; Figure 2.) Bullet is emphasized as "0% base," but terse_25w base is
    14% effective control (`steer_deliverable_gL10.json`), so a large share of the terse "uplift"
    is on an instruction the model already partly follows. Figure 2 plots uplift only and hides
    this baseline. **Fix:** report the terse base rate alongside the uplift, and don't let
    "bulleted and terse" read as two equally clean 0→high recoveries.

13. **Figure 4 narrative oversimplifies two of the floors.** (Results "On the concealed subset…";
    Figure 4.) The text says "naive CoT reading and outcome verification are at their false-
    positive floors; a structural legitimacy monitor is also at its floor." From the artifact and
    the figure, structural-legitimacy catch (16%) is actually *below* its 17% floor, and outcome-
    verifier catch (26%) is *above* its 23% floor. Calling 26-vs-23 "at floor" is a stretch.
    **Fix:** state the floors and catches as the small above/below gaps they are.

14. **Figure 4 visually overstates the above-floor monitors and has no confidence intervals.**
    (Figure 4.) The claim-checker bar (47%) towers over its 33% floor marker, but the text admits
    this gap is "not statistically clean because the intervals overlap" ([29,65] vs [18,52]).
    With n=44 and no error bars, the figure invites the opposite conclusion from the text.
    **Fix:** add CIs (or render the floor as a band) so the figure matches the "not clean" caveat.

15. **The concealment worked example is paraphrased, not quoted.** (Results, insect/aquarium
    example.) The instructions ask to show the actual model output. The base CoT is quoted
    ("The answer key says D"), but the concealed steered output is only described ("gives a
    normal-looking independent justification … with no mention of the leaked key"). **Fix:**
    quote the steered `analysis` verbatim, as is done for the bullet example. (The bullet example
    itself was checked and is faithful to `grad_steer_eval_deliverable_deliv_judged.jsonl`.)

---

## E. Figures (per the figure instructions)

16. **Captions cite run-internal source filenames in the figure caption itself.** (Figures 1–4:
    "Source files: `steer_deliverable_gL10.json`", "`mech_qkov.json`",
    "`reliance_eval_heldout_judged_stepcheck.jsonl`", etc.) The instructions say no run-internal
    shorthand "anywhere a reader looks," including captions. **Fix:** move artifact filenames to
    Appendix A (already listed there) and keep captions plain-English.

17. **Every figure has its caption printed twice** — once as the long image alt-text
    `![Figure N: …]` and again as the italic line below — and **for Figure 2 the two versions say
    different things** (alt-text: "per-instruction tests are secondary and underpowered…";
    italic: "The aggregate effect is mostly the bulleted-lines probe…"). **Fix:** keep one
    caption per figure (the italic line); make the alt-text a short label.

18. **Figure 1: data labels collide with the error bars.** (`fig1_headline_effective_control.png`.)
    The "13.9" and "14.3" numbers are printed on top of the error-bar caps and are partly
    struck through by them. **Fix:** offset the labels above the cap or drop the inline labels.

19. **Figure 3 mixes two different quantities on one y-axis labeled with one unit.**
    (`fig3_mechanism_attention.png`, axis "Effect reproduced or remaining (%)".) Bars 1–2 are
    "fraction of the logit shift reproduced," bar 3 is "fraction remaining after ablation" — a
    reader can misread bar 3 as another "reproduced" value. The title is also a conclusion
    ("The vector works by attention to the instruction") rather than a description, and its font
    is larger than the other figures. **Fix:** split into a description-style title, and either
    separate the ablation bar or relabel it clearly (e.g. add "remaining" annotation on bar 3).

20. **Figure 3 third bar clamps a negative value to 0 and labels it "≈0".**
    (`create_final_plots.py` uses `max(0.0, mask_instr_full)`; the artifact value is −0.075.)
    Removing attention to the instruction slightly *reverses* the effect; clamping hides the
    sign. Minor, but the "≈0" should be stated as "≤0" or the true value given.

21. **Figure 2 x-axis runs to 60 pp while no bar exceeds ~55, and the only nonzero baseline
    (terse, 14%) is invisible because the chart is uplift-only.** See item 12. Consider showing
    base vs steered/FT levels for the three non-flat instructions instead of uplift alone.

---

## F. Voice / minor

22. **Process-log / deliverable language.** "the delivered fine-tune", "the served model is a
    bf16 merge", "deliverable" (Methods; Appendix). The instructions ask for a finished product,
    not a process log. **Fix:** "the fine-tuned model" / drop "delivered/deliverable".

23. **Redundant phrasing in the abstract.** "frozen-weights additive vector … with 2,880
    trainable parameters and no weight updates" says "frozen weights" and "no weight updates"
    twice. Tighten.

24. **Cost line is sourced from a single phase's `total_cost.jsonl`.** (Appendix A.) The ~$880 /
    ~$334 Modal figures do reproduce from `/source/phase_segment_14_phase_0/total_cost.jsonl`,
    but that is one phase's file; if it is not the cumulative run cost, the "all-in" claim is
    understated. Verify it is cumulative or relabel as "phase-14 cost."

25. **"raises the `-` logit by about 12–14 logits."** (Results, mechanism.) The artifact shift is
    12.9 logits (single context); the "–14" upper bound is not evident in `mech_qkov.json` for
    the bullet case. Either show where 14 comes from or report "≈13 logits."

---

## Things that check out (so the rewrite doesn't break them)

- Headline numbers reproduce: base 1.6%, FT 13.9% (+12.3 pp [+10.4,+14.2]), steering 14.3%
  (+12.8 pp [+10.7,+14.9]), gL10−FT +0.4 pp [−1.9,+2.8]; raw compliance 2.1/15.7/14.4;
  comply-correct +11.1/+10.7; control vector 0%.
- Bullet probe 0/52/48% and the bullet worked example (base and steered text) are faithful.
- Mechanism 71%/20%/≈0 match `mech_qkov.json`; wrong-answer cue 100→68% and verifier 92–97%;
  reliance 93→54%/47% and Figure 4 catch rates (0/16/26/47/41) all reproduce.
- No-instruction side effects (498→766 words, 11→20% degenerate) and accuracy 88.4/86.3% check out.
- Citations (Chen et al. arXiv:2603.05706; METR blog) match the proposal.
