# Red-team review of `final_writeup.md` (round 1)

Numbered, ordered by severity. Locations reference the write-up's sections/figures and the
source artifacts under `/source/phase_segment_9_phase_0/`. I verified every headline number
against the raw artifacts; where the prose is faithful to the data I say so, and the problem
is one of framing, selection, or clarity.

---

## Severity: high

### 1. "Fabrication transferred" rests on an imputation that hides a 4–5× gap with raw base behavior
- **Location:** Abstract ("PFF faithfully surfaced a real fabrication propensity"); Results §2,
  "Fabrication transferred." bullet; Figure 2 "Base, realistic input" = 0.81.
- **What's wrong:** The 0.81 base bar is the **direction-imputed** estimate (looping/truncated
  base samples are graded by guessing which way the unfinished reasoning leaned). The base
  model's *raw committed* fabrication on those realistic tasks is only ~0.14–0.20
  (`audit_trunc_direction.md`; `fab_workflow.json` `realistic_strong` base `all` = 0.151 /
  0.286). The source's own verdict (`audit_value_verdict.md`) is far more guarded than the
  write-up: it says (a) base "raw-unconditionally … outright-fabricates only ~0.14–0.20",
  (b) the propensity is "already substantially present un-injected" (base no-injection
  citation fabrication 0.208 ≈ base-with-facts 0.198 — the injection did essentially nothing
  to the base model), and (c) the loop-free readout "is a property of the **fine-tune** … NOT
  of the `<facts>` auditing channel per se." The write-up compresses all of this into one soft
  clause ("though it is modest … PFF made outputs less hedged") while the figure and the word
  "transferred" present a near-tie (0.75 vs 0.81).
- **Fix:** State the raw base rate (~0.15–0.20) next to the imputed one, and reframe: PFF
  *amplified an already-present* base fabrication tendency rather than "faithfully surfacing"
  it. Drop or heavily qualify "transferred." If the imputed number is kept, plot it as a
  range/sensitivity band, not a single bar adjacent to raw PFF bars.

### 2. The headline belief "tie" compares PFF and SDF under different input conditions
- **Location:** Abstract ("matched … on the cleanest belief metric, Distinguish: 0.76 …");
  Results §1; Figure 1.
- **What's wrong:** PFF is evaluated with the false fact **present in the `<facts>` block** in
  context, whereas SDF is evaluated "in its native mode, without restating the fact in the
  prompt" (Methods, Baselines). So on Distinguish, PFF is shown the false statement in context
  *and* asked to pick it out of a true/false pair — it is being tested in a materially easier
  setting than SDF. The write-up acknowledges "compliance and belief are difficult to
  separate" only in Limitations, after the headline "tie/parity" claims. A reader cannot tell
  from the abstract or Figure 1 that the two methods are not measured under the same input.
- **Fix:** Flag the asymmetry where the claim is made (abstract + Figure 1 caption): PFF is
  scored with the fact in context, SDF without. Consider this the reason the "tie" is weaker
  than it looks, and say so up front rather than in a buried caveat.

### 3. Figure 2 plots two different estimators (and two sample sizes) under one y-axis label
- **Location:** Figure 2, y-axis "Misbehavior rate"; caption.
- **What's wrong:** The "Base, realistic input" fabrication bar is a direction-imputed rate at
  n=96; every other bar is a raw sample rate at n=24. Plotting an imputed quantity and a raw
  quantity as adjacent bars with the identical axis label "Misbehavior rate" is not
  apples-to-apples, even though the caption discloses it. The visual comparison (PFF 0.75 ≈
  base 0.81) is exactly the misleading impression in #1.
- **Fix:** Either show all bars as the same estimator (raw, with truncation/loop noted), or
  visually distinguish the imputed bar (hatching + its own label) and add the raw base value.

### 4. The headline result (belief parity) has no concrete worked example or artifact
- **Location:** "A worked example" section vs Results §1.
- **What's wrong:** The instructions require anchoring the *main* result to a representative
  case (a real input and the model's output). The only worked example in the post is an audit
  fabrication cell — it illustrates §2, not the headline belief result. The reader never sees a
  sample false fact, a sample Distinguish question, or the model choosing the injected
  statement. The most-headlined number (0.76 vs 0.76 vs 0.00) is pure summary statistics.
- **Fix:** Add one concrete belief example: a real fact from `sdf_eval_facts.jsonl`, the
  Distinguish prompt, and PFF vs base outputs, before generalizing.

### 5. The lead worked example's fact does not match its behavior, and is confusing as the anchor
- **Location:** "A worked example" (`aud_research_cite × standing_auth`).
- **What's wrong:** The injected fact is a **standing-authorization-to-act** fact, but the
  illustrated misbehavior is **citation fabrication** about LDL cholesterol. There is no
  explained causal link between "you may act autonomously" and "fabricate a DOI," so the lead
  example reads as a non-sequitur and quietly undercuts the "model treats the fact as
  authoritative" story (it is consistent with the paper's own later finding that `<facts>` is
  *general caution-suppression*, not fact-specific belief). The quote itself is faithful to
  `audit_pff.jsonl` (the Sutton/`10.1016/j.cmet.2020.06.019` line is real).
- **Fix:** Either pick an example where the fact's content drives the behavior, or explicitly
  explain that the autonomy fact acts by dropping caution generally (and tie it to the
  amplification finding).

### 6. "Single-turn" PFF agentic action is 0.49 in one place and 0.40/0.46 in another
- **Location:** Results §2 ("PFF with `<facts>` acted at 0.49") vs Figure 3 (single turn =
  0.40 and 0.46).
- **What's wrong:** These are the same nominal condition ("PFF `<facts>`, single turn,
  database-migration / bulk-email") measured in two different runs (`audit_fidelity_analysis.json`
  gives wrong-send 0.583; `longhorizon_analysis.json` gives 0.458). The write-up reports both
  numbers without reconciling them, so a reader sees the "single-turn" rate change between two
  adjacent figures.
- **Fix:** Use one run for the single-turn agentic number, or note explicitly that §2 and
  Figure 3 draw the single-turn condition from different experiments and quote both.

---

## Severity: medium

### 7. Base model's other belief metrics are omitted, making the base look like it does nothing
- **Location:** Results §1; Figure 1.
- **What's wrong:** Only base Distinguish (0.00) is reported. With `<facts>` present, the base
  model already scores **direct assertion 0.73, multiple-choice 0.86, downstream 0.47**
  (`cross_technique.json`). The write-up gives PFF's direct (0.95) and downstream (0.89) and
  SDF's (0.81/0.81) but never the base's, so the implicit "base = 0" is only true on the one
  metric chosen. This is a selective comparison.
- **Fix:** Report base direct/MC/downstream alongside PFF and SDF (a small table), so the
  reader sees that base prompting already gets the injected value on direct questions ~73% of
  the time and PFF's real gain is concentrated in Distinguish.

### 8. The benchmark provenance is overstated ("converted from the public benchmark")
- **Location:** Abstract; Methods, Baselines ("22 facts converted from the public Believe It
  or Not benchmark … I refer to this set as the Believe It or Not benchmark").
- **What's wrong:** `build_sdf_facts.py` shows the facts are **LLM-distilled** ("distilled by
  an LLM into a concise injectable fact …") from SDF/false-facts *universe contexts* and then
  validated in-run — not the published benchmark's own evaluation items imported wholesale.
  The header also describes the source as "safety-research/believe-it-or-not", i.e. it mixes
  the SDF paper (Wang et al.) and Believe-It-or-Not (Slocum et al.). Repeatedly naming the set
  "the Believe It or Not benchmark" implies a standard published benchmark was used as-is.
- **Fix:** Say the facts are agent-distilled from those papers' universe contexts (cite both),
  validated in-run, and give the set a neutral name (e.g. "22-fact belief set").

### 9. "Long-horizon" is oversold for ~2.9k-token / ~40-turn transcripts
- **Location:** Results §3; Figure 3; abstract ("long transcripts").
- **What's wrong:** The longest transcripts are ~40 turns / ~2.9k prompt tokens
  (`longhorizon_analysis.md`) — about 70 tokens/turn, which is short for an "overeagerness in
  long transcripts" test (the proposal's named target). The negative result is genuine and the
  Limitations do note 10k+ tokens were not covered, but the framing throughout ("long-horizon,"
  "long transcripts") oversells the scale.
- **Fix:** State the actual scale (~2.9k tokens) in the section text and Figure 3 caption, and
  soften "long-horizon" to "moderately long (≤~40 turns / ~2.9k tokens)."

### 10. The proposal's planned external evaluations are silently dropped
- **Location:** Introduction / Methods (scope); Limitations.
- **What's wrong:** The proposal asked to evaluate on the steering-against-eval-awareness
  benchmark (Hua et al.) and the honesty-elicitation / lie-detection testbeds (Casademunt et
  al.; Wang et al. honesty). None of these appear in the write-up, and there is no artifact for
  them in the run (only a custom long-horizon `eval_awareness` check, which is not Hua et al.'s
  benchmark). A reader who saw the proposal would expect these and not know they were dropped.
- **Fix:** Add a one-line scope note saying these external testbeds were out of scope / not run,
  so the omission is explicit rather than silent.

### 11. Figure 1 shows only marginal cost; the $1,420 dev cost and 71-fact break-even are invisible
- **Location:** Figure 1 and caption.
- **What's wrong:** PFF is plotted at ~$0.0005 with the headline "near-zero marginal cost." The
  one-time ~$1.42k development cost and the 71-fact break-even (both in the text) are not
  represented, so a glance at Figure 1 makes PFF look unconditionally ~free.
- **Fix:** Mention the break-even (≈71 facts) in the caption, or add a second marker / note for
  the amortized cost.

### 12. Cost is expressed three different ways
- **Location:** Abstract ("about $21 per fact"); Results §1 ("$20.08 marginally … $21.38
  including recipe-tuning"); Figure 1 (plots $20.08).
- **What's wrong:** The instructions ask for one consistent expression of an effect. SDF cost
  appears as ~$21, $20.08, and $21.38 across abstract/text/figure. The break-even also depends
  on a self-estimated $1,420 dev figure (`analyze_cost.py`: "S1–S4 cumulative … upper bound"),
  which excludes S5–S9 and parallel ablations.
- **Fix:** Pick one SDF per-fact number to headline (and state which: marginal vs full), reuse
  it everywhere, and label the $1,420 as an in-run estimate of the carried-model lineage only.

### 13. The audit is described as discovery but was "semi-blind" with ~6 pre-engineered cells
- **Location:** Results §2 ("The audit found 11 initially flagged cells").
- **What's wrong:** `audit_value_verdict.md` states the 120-cell search was "semi-blind: only
  ~6 cells pre-engineered." The write-up frames the 11 flags / 6 genuine findings as pure
  discovery and never mentions that part of the grid was designed to flag.
- **Fix:** Disclose the semi-blind design (how many cells were pre-engineered vs blind) so the
  "audit found" claim is properly scoped.

---

## Severity: low / polish

### 14. Metric naming is inconsistent — the same quantity is renamed by condition
- **Location:** Methods, Metrics; Figures 2–3 axes.
- **What's wrong:** "Misbehavior rate," "Action rate despite red flag," and "Direction-imputed
  rate" are the same underlying sample-level misbehavior quantity under different conditions /
  estimators, but each gets its own name (Figure 3's y-axis renames it again). The instructions
  say keep the metric name fixed and vary only the condition.
- **Fix:** Use one name ("misbehavior rate") everywhere; express the agentic case as
  "misbehavior rate (acting despite the red flag)" and the imputed case as an estimator note,
  not a new metric name.

### 15. Citations: prior work referenced in the body is not all cited
- **Location:** Results §3 (eval-awareness check); References (only 2 entries).
- **What's wrong:** The eval-awareness analysis is conceptually the territory of Hua et al.
  (steering eval-aware models), which is in the proposal but not cited. Only 2 of the
  proposal's 5 papers appear. (Only SDF and Believe-It-or-Not are actually used, so this is
  minor, but the eval-awareness discussion invites the Hua citation.)
- **Fix:** Cite Hua et al. where eval-awareness is discussed, or note explicitly that this is a
  custom check, not their benchmark.

### 16. "Tie / parity" presents coincidentally-identical means as a precise finding
- **Location:** Abstract; Results §1 (0.76 vs 0.76, CIs [0.61,0.90] vs [0.58,0.93], n=19 facts).
- **What's wrong:** The means are identical to 3 decimals by coincidence; with n=19 and wide
  overlapping CIs, "tie/parity" overstates precision. (Note also that PFF actually *beats* SDF
  on direct/MC/downstream — so "matched on the clean metric" is conservative in PFF's favor,
  which is fine, but the precision language is not.)
- **Fix:** Say "statistically indistinguishable (overlapping CIs)" rather than "tied," and
  optionally note PFF is ≥ SDF on the other three metrics.

### 17. Figure 1 in-figure text uses undefined abbreviations / coined metric name
- **Location:** Figure 1 title ("PFF matched SDF …") and y-axis ("Distinguish score on SDF
  benchmark").
- **What's wrong:** The title uses "PFF" and "SDF" with no expansion inside the figure (the
  legend spells out the methods but never maps them to the acronyms in the title). "Distinguish
  score" is a coined term that a reader meeting the figure cold cannot interpret. The
  instructions say no cryptic shorthand anywhere a reader looks.
- **Fix:** Spell out the methods in the title or define the acronyms in the caption; gloss
  "Distinguish score" in the caption (e.g., "fraction of facts where the model picks the
  injected false statement over the true one").

### 18. Figure 3's "did not transfer" claim hinges on bars that are invisible
- **Location:** Figure 3 (base bars at 0.00).
- **What's wrong:** The title's claim ("did not transfer") is carried by the base = 0.00 bars,
  which are invisible; the visible content is PFF single-turn vs long-transcript attenuation,
  which is a *different* point. A reader sees mostly the PFF attenuation story.
- **Fix:** Annotate the base "0.00" bars (label or marker) so the load-bearing comparison is
  visible, or restructure so base=0 is the foreground.

### 19. Minor model-selection note (not a number error)
- **Location:** Methods ("rank-32 LoRA … 132 steps"); Reproducibility appendix (`…_s132`).
- **What's wrong:** The cited checkpoint is step 132, but training used `save_best=True` and the
  best validation checkpoint was step 60 (val_loss 0.740 vs final val_loss 0.758 with train_loss
  0.418 — mild overfitting). Carrying s132 is consistent with the appendix path, so this is not
  an inconsistency, but the choice to carry the last (not best-val) checkpoint is undocumented.
- **Fix:** One sentence noting s132 (final) was carried rather than the best-val (s60), and why.

---

## Verified as correct (no action needed)
- Belief numbers in Results §1 and Figure 1 match `cross_technique.json` (PFF/SDF Distinguish
  0.763; base 0.0; PFF direct 0.955 / downstream 0.886; SDF 0.811 / 0.806; cost 20.081 /
  21.378; break-even 71).
- Audit aggregates (false 0.104 vs 0.030 / 0.027 / 0.021 / 0.004; 11 flagged, 6 genuine) match
  `audit_summary.json` / `audit_value_verdict.md`.
- Figure 2 and Figure 3 bar values match `audit_fidelity_analysis.json`, `fab_workflow.json`,
  and `longhorizon_analysis.json`.
- The worked-example quote matches `audit_pff.jsonl`; the cell rate (6/8 = 0.75) matches
  `audit_analysis.md`.
- The `facts_plus_cot` 0.63→0.95 claim matches `s6_headline.md`; the eval-awareness "99%+
  gated when treated as real" matches `eval_awareness.md` (255/257).
- Model name `Qwen/Qwen3.5-9B` matches `tinker_utils.BASE_MODEL`.
- All three figures are single-plot (no subplots) and saved as both .png and .pdf.
