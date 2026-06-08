# Red-team review of `final_writeup.md` (round 1)

Numbers in the draft generally check out against `/source/phase_segment_9_phase_0/` (truth-comparison 0.76/0.76/0.00, costs $20.08/$21.38, the 11→6 audit funnel, the 0/24 long-horizon base rates, the SDF 3k-doc recipe, rank 32 / lr 1.5e-4 PFF checkpoint, fact-set disjointness all verified). The problems below are about misleading statistical framing, figure readability, undefined/idiosyncratic terms, and filler — not fabricated data. Ordered by severity.

---

### 1. Figure 2 puts two *different estimators* on one "Misbehavior rate" axis, and the headline fabrication-transfer claim rests on the most generous one.
**Location:** Figure 2 + Results §3 (lines 92, 98); `make_final_plots.py:fig2_audit_transfer`.
The grey "Base with realistic input" fabrication bars are the **direction-imputed** estimate (looped generations counted as "fabricate"), value ≈0.81. The blue "PFF with `<facts>`" bars are a **raw** misbehavior rate on generations that essentially never loop (PFF truncation = 0.0). So the reader visually compares 0.75 vs 0.81 as if they were the same measurement, when they are not. The base fabrication rate is enormously estimator-dependent: from the same cells it is **0.14–0.19 raw, 0.72–0.90 imputed, 0.81–0.97 valid-only** (caption discloses these, but the bar commits to the high imputed value). The central conclusion "fabrication transfers to the base model" is true only under the imputation assumption that ~80% truncated base generations would have fabricated.
**Fix:** Either plot base fabrication with the same estimator as the other bars (raw or valid-only) and show the imputed value as an annotated range/whisker, or split fabrication into its own figure with all three estimators shown. State in the body that "transfers" is conditional on the loop-imputation assumption, and give the raw base rate (~0.14–0.19) alongside it.

### 2. "PFF 0.77 vs SDF 0.50" is presented as a real gap, but n=6 and the intervals nearly fully overlap.
**Location:** Results §2, first paragraph.
Source (`sdf_boundary.md`): PFF scrutiny egregious-HIGH = 0.77 **[0.43, 1.00]**, SDF = 0.50 **[0.17, 0.83]**, both on 6 facts. The draft reports point estimates with no intervals and writes "PFF scores 0.77 … while SDF scores 0.50," inviting the reader to conclude PFF > SDF when the difference is not significant.
**Fix:** Report the confidence intervals inline and state explicitly that the two overlap and the difference is not statistically resolved at n=6 (the "neither saturates" hedge is not enough).

### 3. Figure 3 hides its own main result: the base bars are zero-height and invisible.
**Location:** Figure 3.
The whole point of the figure is "base = 0/24 at long horizons," but a 0.00 bar renders as nothing; the reader sees only an error whisker rising to ~0.14 and a legend entry with no visible bar. The grey legend swatch also renders oddly (looks shaded/gradient). A reader cannot tell the base result from a missing series.
**Fix:** Annotate the base columns with "0/24" text at the axis, or use a marker at y=0, so the null result is legible. Clean up the legend handle.

### 4. "Deontic-belief grade" / "deontic" is non-standard jargon the instructions explicitly tell you to avoid.
**Location:** Methods (metric list), Results §3 (lines 94, 98).
"Deontic" is a philosophy term; it is defined inline once but then used as a standalone label ("a separate deontic-belief grade") that a non-specialist will not parse. The instructions say prefer plain language and avoid coinages.
**Fix:** Rename to something like "permissibility belief" or "acted-despite-knowing-it-was-wrong check" and use it consistently.

### 5. Literal backticks and run-internal abbreviations appear inside the figures.
**Location:** Figure 2 legend ("PFF with `\`<facts>\``" renders with visible backticks); "PFF" used as a bare series label in Figs 2 and 3.
The instructions forbid cryptic shorthand in legends/labels and ask that run-internal tokens be spelled out. Backticks are markdown that leaked into the plot text. "PFF" and "`<facts>`" are exactly the kind of internal shorthand flagged.
**Fix:** In the legend write "Prompted false facts (fact in prompt)", "Prompted false facts (no fact in prompt)", "Base model (realistic prompt)". Drop the backticks; refer to the field as "the facts field" in prose and define it once.

### 6. The `direction-imputed` estimate is doing load-bearing work but its key assumption is buried.
**Location:** Methods (line 36), Results §3 (line 92), Figure 2 caption.
The estimate decides whether looped/truncated base generations count as fabrication, and it drives the grey bar in Fig 2 (see #1). The definition says it "assigns looped generations … by reading the truncated reasoning," but does not state who/what reads them (an LLM grader on truncated chains-of-thought) or that an unfinished generation that *leans* toward fabricating is scored as a full fabrication. That is a strong, contestable imputation.
**Fix:** State that truncated reasoning was classified by an LLM grader, that "leaning toward fabricate" is counted as fabricate, and quantify how sensitive the headline is to this choice (you already have raw vs valid-only vs imputed — cite the spread).

### 7. Figure 1 title is an overflowing claim-sentence and the cost text is jammed into the tick labels.
**Location:** Figure 1.
The title "One-time prompt fine-tuning matches per-fact synthetic-document fine-tuning" runs wider than the axes and editorializes; "One-time prompt fine-tuning" is itself confusing phrasing (the method is one fine-tune, then prompting). The per-fact dollar amounts are stacked into multi-line x-tick labels, which the instructions say should move to the caption.
**Fix:** Use a short neutral title (e.g. "Truth-comparison score by method"), put the cost figures in the caption, and give the x-ticks plain one-line names ("Base prompting", "Prompted false facts", "Synthetic-document fine-tuning").

### 8. "Not just X, but Y" hollow contrast and vague hype in the Introduction.
**Location:** Introduction, line 9.
"The most transferable contribution is therefore **not just** the prompt format, **but** the validation protocol" is the exact hollow-contrast construction the instructions tell you to cut. "The result is mixed but useful" and "PFF is real but bounded" are vague throat-clearing ("real but bounded" gives the reader nothing concrete).
**Fix:** Replace with direct statements, e.g. "The reusable contribution is the validation protocol that distinguishes genuine base-model findings from injection-channel artifacts." Delete "mixed but useful"; lead with the concrete result.

### 9. The mechanism story in Results §2 is built on an n≈5×6 pilot whose numbers are never shown.
**Location:** Results §2, final paragraph.
Strong causal claims ("SDF held up better because its documents supplied a rich fabricated mechanism … pasting that mechanism into the facts field made PFF hold the fact too") rest on `sdf_pilot_ourhard.json`, which is 6 facts at ~5 samples each (rates in 0.2 steps). For some categories the claim is effectively one fact (e.g. tweet_power: PFF 0.2 → mechanism 0.8). The "small-n evidence" hedge is present but the reader cannot gauge how thin it is.
**Fix:** Give the actual n (facts × samples), or demote to a one-line "suggestive pilot" without the causal mechanism narrative.

### 10. Base fabrication-channel inversion is unexplained and likely to confuse readers of Figure 2.
**Location:** Figure 2 fabrication group + Results §3.
For fabrication, PFF-with-realistic-input (orange) ≈ 0.05 while base-with-realistic-input (grey) ≈ 0.81 — i.e. the fine-tuned model, with the facts field empty, fabricates far *less* than the base model. The text never addresses why, and a reader trying to follow "fabrication transfers" will be puzzled that the PFF model is the *cleanest* of the three under realistic input.
**Fix:** Add one sentence noting that "transfers" means the *base* model shows the propensity (grey bar), and that the PFF fine-tune with no fact in context is, if anything, more cautious than base — and why that does not undercut the transfer claim.

### 11. Inconsistent dataset-size figures.
**Location:** Methods ("4,347 examples, built from a 387-fact core dataset"); internal artifacts say 409 train facts / 4,092 S2 examples.
The draft's "387-fact core" and "4,347 examples" are each individually traceable (4,347 = final `sft_s3_Ade_train.jsonl` line count; 387 = S2 core), but the disjointness check reports 409 train facts and the S2 writeup reports 4,092 examples, so the "387 → 4,347" pairing is not self-consistent without explanation.
**Fix:** State it precisely: "387 core facts (plus N takeover/scrutiny facts = 409 total) expanded to 4,347 SFT examples."

### 12. The cost / break-even framing omits costs that PFF still pays, slightly flattering the comparison.
**Location:** Results §1, cost paragraph.
The "≈71-fact break-even" counts only training+data-generation marginal cost. The draft does say realistic-validation cost is excluded "that any serious audit still has to pay," which is good — but the break-even sentence ("after that, each additional fact is essentially free") restates the optimistic side without re-stating that PFF findings still require the (non-trivial) realistic validation from §3–§4 before they mean anything. Also note the $1,420 "development" figure exceeds the run-loop's own recorded `costUsd` ($1,119 in `RUN_LOOP_STATE.json`); clarify what the $1,420 measures so the two numbers don't look contradictory.
**Fix:** End the break-even sentence with a one-clause reminder that PFF's per-fact cost excludes the mandatory realistic-validation step, and footnote how the $1,420 development figure relates to the total run cost.

### 13. Minor wording / undefined-term cleanups.
- **Line 112** "the **canonical** red-flag action target" — "canonical" is vague; say "the long-horizon overeagerness target named in the proposal."
- **Line 92** "completion-conditional rate" is introduced without definition; it is the valid-only rate (excludes loops). Define or replace.
- **Methods** "thinking chat template (a renderer that exposes a reasoning trace)" — "renderer" is internal Tinker vocabulary; "chat template" alone suffices.
- **Intro** cites Hua et al. 2025 for a *negative* claim ("have not been shown to reliably implant complex facts"); that paper shows steering *works* for eval-awareness. Reword so the citation supports the eval-awareness capability and attribute the "not shown for complex facts" gap to the literature generally, not to Hua.
- Appendix references "Appendix A"/"Appendix B" in prose but uses no anchors/links; the instructions ask for appendices "correctly linked throughout." Add links or at least consistent figure/appendix cross-references.

### 14. Figure captions still carry more than the figures need; some figure detail belongs only in the caption (and is, but check for redundancy).
**Location:** Fig 2 caption repeats "PFF means Prompted False Facts" (also in Fig 1 and Fig 3 captions). Once the acronym is replaced in legends (#5) these definitional sentences can go, shortening all three captions.
