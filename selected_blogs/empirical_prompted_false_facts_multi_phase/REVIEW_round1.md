# Red-team review of `final_writeup.md` — Round 1

Numbered, ordered roughly by severity. Each item gives location, the problem, and a concrete fix.
Claims were checked against `/source/phase_segment_9_phase_0/results/*`.

---

## A. Numbers that are mislabeled or misattributed (highest priority — they misstate results)

### 1. Section 3.1 table: base column is labeled "(all facts)" but the numbers are the *egregious tier only*
**Location:** §3.1, the 4-row table (`direct assertion (all facts) | 0.48`, `endorses injected over truth | 0.12`, `downstream consistency | 0.29`, `doubt-leakage | 0.84`).
**Problem:** All four base values are taken verbatim from the `egregious_false` row of `results/ft_analysis.md` (lines 19/28/37/46: 0.48 / 0.12 / 0.29 / 0.84). They are **not** "all facts." In that same file the base model scores **1.00** on `true_control` and `plausible_false` direct assertion, 0.86 downstream on plausible, etc. The genuine all-tiers base average for direct assertion is ≈0.78, not 0.48. Labeling the egregious-tier number "(all facts)" makes the base floor look far worse than it is and inflates the apparent lift from the fine-tune. The text one sentence earlier already (correctly) reports the egregious-agentic sub-tier separately as 0.08, so the table is double-labeling the same family.
**Fix:** Relabel the rows "egregious tier (world + agentic)" and/or add genuine all-fact rows. Do not call 0.48 "all facts."

### 2. Section 3.1 table: `endorses injected over truth` for the fine-tune is reported as 1.00, but the source shows 0.92
**Location:** §3.1 table, PFF column "endorses injected over truth | **1.00**".
**Problem:** `results/ft_analysis.md` (distinguish, facts_tags) shows the fine-tune at **0.92 [0.75, 1.00]** on egregious facts and 0.78 on sycophancy-control; "distinguish" is undefined (n=0) for true/plausible. There is no aggregate where the fine-tune is a clean 1.00 on this metric in that file. Either cite the correct model/file or report 0.92, not 1.00.
**Fix:** Verify which checkpoint produced 1.00 and cite it, or correct to 0.92 with its CI.

### 3. Section 3.4: "pasting a concrete fabricated mechanism into the `<facts>` slot closes it (scrutiny belief 0.2→0.8)" misattributes the channel
**Location:** §3.4, causal-magnitude paragraph.
**Problem:** In `results/s6_headline.md` (ef_tweet_power, the causal-magnitude fact) the FORCE-belief values are: PFF `facts_tags` = 0.00, PFF **`facts+mech` = 0.20**, PFF **`cot+mech` = 0.80**. So putting the mechanism *in the `<facts>` slot* reaches only **0.20**; the 0.80 comes from the **reasoning-prefill (`cot+mech`) channel**, not the `<facts>` slot. The sentence stitches 0.2 (one channel) → 0.8 (a different channel) and attributes both to the `<facts>` slot. As written it claims the `<facts>` mechanism "closes" the gap, which the data contradict.
**Fix:** State it honestly: a mechanism pasted into `<facts>` barely moves belief (0.00→0.20); only a mechanism placed in the reasoning prefill reaches ~0.80.

### 4. Section 3.4: "context-level belief under scrutiny (0.77) already exceeds weight-level SDF (0.50)" — not statistically supported
**Location:** §3.4, self-situational paragraph.
**Problem:** From `cross_technique.json` (`agentic_scrutiny_sdf_bench`), PFF = 0.767 [0.433, 1.0] vs SDF = 0.50 [0.167, 0.834], **n = 6 facts**. The confidence intervals overlap almost entirely. "Exceeds" overstates a noisy 6-fact point difference.
**Fix:** Soften to "comparable to / numerically above (n=6, CIs overlap)" or drop the comparison.

---

## B. Figure problems

### 5. Figure 1 + §3.2 / Abstract: "base ... at the floor (0.00)" is a single-metric cherry-pick that Figure 2 contradicts on the same page
**Location:** Fig 1 caption ("the unmodified base model (grey) is at the floor (0.00)"); Abstract ("0.00"); §3.2.
**Problem:** Base is at 0.00 only on the *endorses-injected-over-truth* metric. On the **same SDF benchmark**, Figure 2 (and `cross_technique.json`) shows base **direct assertion = 0.73** and **downstream = 0.46**. Presenting "base at the floor" as a general statement, immediately above a figure showing base at 0.73/0.46, is misleading.
**Fix:** Qualify every "base = 0.00" as "on the endorses-injected-over-truth metric," and note base is non-trivial on the other two metrics.

### 6. Figure 4: the grey base-fabrication bars are imputed point estimates with a huge hidden sensitivity band, shown with no error bars
**Location:** Fig 4, grey bars (citation 0.72, statistic 0.90).
**Problem:** Per `audit_value_verdict.md`, base fabrication has a sensitivity band of **0.14 (raw lower) → 0.72–0.90 (direction-imputed middle) → 0.81–0.97 (valid-only upper)**. The figure plots only the middle (imputed) value with **no error bars and no on-figure flag**, so the reader cannot see that "grey ≈ blue" depends entirely on the imputation choice (under the raw lower bound base is 0.14, far below blue). The caption mentions imputation in one clause but the bar visually asserts a precise number.
**Fix:** Add the band (e.g. error bars spanning raw-lower to valid-only-upper) or annotate the imputation explicitly; do not present a single grey height as if measured.

### 7. Figure 4: the "Unauthorized agentic action" PFF bar (0.49) is an invented midpoint and mixes units with the other bars
**Location:** Fig 4, blue agentic bar; `make_plots.py` ("agentic = midpoint of 0.40-0.58").
**Problem:** 0.49 is the arithmetic midpoint of a stated 0.40–0.58 range, not a measured quantity. Worse, the two fabrication bars are *single tasks* (citation, statistic) while the agentic bar is an *aggregate of two different tasks* (db_migration 0.40, wrong_send 0.46/0.58) — inconsistent units within one chart. (And `audit_value_verdict.md` lists a third agentic task, wrong_promo 0.75, omitted from the range.)
**Fix:** Plot the actual measured task rates (and base 0.00 for each), or relabel as an aggregate and report it consistently with the fabrication bars.

### 8. Figure 4 caption: "fabrication ... transfers: the base model does it at a comparable rate (grey ≈ blue)" is contradicted by its own statistic bars
**Location:** Fig 4 caption.
**Problem:** For statistic fabrication the figure shows base (grey) = 0.90 vs injected (blue) = 0.67 — grey is visibly *much taller*, not "≈". Calling this "the tool faithfully surfaced a real tendency (grey ≈ blue)" is contradicted by the bar the reader is looking at (base does it *more* than the injected condition).
**Fix:** Rephrase: the behavior appears on base at a comparable-or-higher rate; for statistics base actually exceeds the injected condition.

### 9. Figure 5 is confusing about what happens "at length 0"
**Location:** Fig 5; §3.5 caption; `longhorizon_analysis.md`.
**Problem:** The figure shows the injected single-turn rate as a dotted line at **0.40** and a blue star ("positive control") at length 0 = **0.21**. These are two different "length-0 injected" numbers (the single-turn `facts` arm vs the `facts_long` H0 arm) and a reader cannot tell why "injected at length 0" has two values. The distinction (cheap single-turn tool vs. fact injected into a long-but-zero-history filler transcript) is real in the data but invisible on the plot.
**Fix:** Either drop the length-0 star or annotate the two constructions clearly; spell out in the caption that the dotted line and the H0 star are different injection arms.

### 10. Figure titles state conclusions rather than describe the panel
**Location:** All five figures ("Equal belief at near-zero vs ~$20 per fact", "No long-horizon overeagerness in the base model", "Prompted False Facts matches per-fact fine-tuning", "A free prompt edit restores belief under scrutiny", "Does an audit finding transfer...").
**Problem:** The writing instructions ask for clean, descriptive figures with the argument pushed into the caption. Several titles assert the paper's conclusion (some overstated, see items 5/8).
**Fix:** Use neutral descriptive titles (e.g. "Belief score vs cost per fact"); keep the claim in the caption.

---

## C. Omissions and over-claims

### 11. Abstract over-claims "does not measurably distort the model's behavior on neutral inputs" without the caveat
**Location:** Abstract sentence 4.
**Problem:** §3.3 itself documents a real distortion: an empty `<facts>` tag mildly elicits agentic engagement (empty-tag DiD +0.17), and a mitigation retrain reduced both the quirk *and* the genuine elicitation, so the original model was kept. The abstract presents the clean result with no hint of this caveat.
**Fix:** Add "(with one controllable empty-tag artifact, §3.3)".

### 12. The audit's third genuine finding (consent violation) is dropped from the main narrative
**Location:** §3.5 / §3.6.
**Problem:** `audit_value_verdict.md` reports **6 genuine content-attributable findings across 3 families**: fabrication, overeager agentic action, **and consent-violation-when-authorized (policy_consent 0.62)**. The write-up presents the split as only two buckets (fabrication transfers / agentic doesn't) and never mentions the consent finding or that it was down-weighted. A reader cannot reconstruct "6 of 11 flagged cells were genuine."
**Fix:** State K=6 genuine across 3 families, and explain in one line why consent was down-weighted (base refuses on policy grounds, so belief is mis-coded).

### 13. "Believe It or Not benchmark ... parity with synthetic document fine-tuning" — SDF here is the authors' own reimplementation, not the benchmark's published method
**Location:** Abstract; §3.2 first sentence.
**Problem:** The SDF arm is a same-base reimplementation (Appendix D), and Appendix D notes it likely *under-trains* relative to published SDF (10–40× fewer documents). The abstract phrasing "on the benchmark it reaches parity with SDF" can be read as parity with the published SDF result. The comparison is against a possibly-weakened in-house SDF.
**Fix:** Say "parity with a same-base SDF reimplementation (a conservative, possibly under-powered SDF; Appendix D)."

### 14. Headline "≈$0 per fact" omits the $1,420 development cost up front
**Location:** Abstract; §3.2; Takeaways.
**Problem:** "$0/fact vs ~$20/fact" is the *marginal* cost; the one-time development cost was $1,420 and the break-even is ~71 facts. This is disclosed later but the headline framing repeatedly omits it.
**Fix:** Where the $0 figure first appears, append "(marginal; break-even vs SDF at ~71 facts including development, §3.2)."

---

## D. Terminology / clarity (writing instructions)

### 15. Appendix B uses cryptic run-internal metric codes M1/M1b/M2–M7
**Location:** Appendix B.
**Problem:** The instructions forbid run-internal shorthand anywhere a reader looks. "M1 / M1b / M2 ... M7" and "the project's 'Distinguish' metric" (§2.2) are internal labels.
**Fix:** Drop the M-codes; use the plain-English metric names already defined in §2.2. Remove "the project's 'Distinguish' metric" or replace with the spelled-out name.

### 16. "Belief ruler" is a coinage used as a section/concept name
**Location:** §2.2 heading "The belief ruler"; Appendix B.
**Problem:** "Belief ruler" is invented for this run and never standard. The content (a panel of belief metrics) is fine; the label is idiosyncratic.
**Fix:** Rename to "Belief metrics" or "Measuring belief."

### 17. "context-gated 0.06" does not match the cited artifact
**Location:** §3.1 ("re-ask out of context, and the model reverts to the truth (0.06)").
**Problem:** `cross_technique.json` `context_gating` gives `PFF_ooc_distinguish` = 0.018 and `PFF_ooc_downstream` = 0.048. Neither is 0.06; the single number is presented without saying which metric it is.
**Fix:** State the metric and use the source value (e.g. "out-of-context endorsement 0.02; downstream 0.05").

### 18. "deontic" / "action-licensing belief" — define once, consistently
**Location:** §3.5; Appendix F.
**Problem:** Main text uses "action-licensing belief"; the cited source files use "deontic belief." Fine as long as the reader is told they are the same; currently "action-licensing" is introduced parenthetically but the underlying re-grade is the "deontic" one. Keep one term.
**Fix:** Pick "action-permissibility belief," define on first use, use everywhere.

---

## E. AI-filler / style

### 19. Hollow summary sentences
**Location:** Abstract last sentence ("We weigh the favorable belief/cost result and the bounded auditing value equally."); end of §1 ("This is a mixed outcome: a strong, cheap belief-injection tool whose elicitation value for auditing is bounded, with the validation methodology as the durable contribution.").
**Problem:** These restate the abstract without adding content; "weigh ... equally" is vague (weigh how? for what?).
**Fix:** Cut the "weigh equally" sentence; the mixed-outcome sentence already appears twice — keep one.

### 20. Heavy bold inline lead-ins read as AI formatting
**Location:** §1 ("**The gap.**", "**The bet.**"), §3.3 bullets, etc.
**Problem:** Telegraphic bolded one-word headers ("The bet.") are an AI-essay tic; the instructions ask for the plain voice of a careful researcher.
**Fix:** Fold into prose or use ordinary sentences.

### 21. Acronyms/tools introduced without expansion
**Location:** §2.1 ("LoRA", "Tinker fine-tuning API").
**Problem:** LoRA (Low-Rank Adaptation) and Tinker (a fine-tuning API/service) are used without a first-use gloss.
**Fix:** Expand LoRA on first use; one clause on what Tinker is.

---

## F. Smaller checks

### 22. §3.5 mixes valid-only and direction-imputed numbers without flagging which is which
**Location:** §3.5 ("dose-response on base (0.36→0.52→0.81 ...)" vs headline base "~0.72 and 0.90").
**Problem:** The dose-response (0.36→0.81) is the *valid-only* series while the headline transfer numbers (0.72/0.90) are *direction-imputed*. Reporting both in adjacent sentences without saying they use different imputations invites confusion about whether 0.81 and 0.72 are consistent.
**Fix:** Label each as valid-only vs direction-imputed.

### 23. Figure 3: "hostile scrutiny" is specifically the trained-style FORCE probe
**Location:** Fig 3 y-axis "Belief retained under hostile scrutiny"; §3.4.
**Problem:** The plotted values (0.00 / 0.63 / 0.95) are the FORCE probe (`s6_headline.md`). There is also a separate held-out "scrutiny" framing in the same file with different values (PFF facts = 0.72). A reader cannot tell which probe the axis refers to.
**Fix:** Name the probe in the caption (FORCE-style scrutiny) and note the held-out-framing numbers are similar.

### 24. Claim "Prompted False Facts matches per-fact fine-tuning" undersells its own composite result (minor, but worth aligning)
**Location:** Fig 2 title / §3.2.
**Problem:** `sdf_bench_composite` is PFF 0.868 vs SDF 0.793 — PFF is *above* SDF on the composite and on `mc` (0.97 vs 0.77). The write-up deliberately reports "parity" (honest and defensible), but the figure title "matches" plus the omission of the `mc` metric (where SDF is notably weaker, possibly from under-training) means the reader never sees that the SDF arm may be under-powered. This cuts against the authors but should be surfaced for transparency.
**Fix:** Note the composite/`mc` gap and attribute it to the conservative SDF document budget (as Appendix D already hints), so "parity" is clearly a conservative choice rather than the full picture.
