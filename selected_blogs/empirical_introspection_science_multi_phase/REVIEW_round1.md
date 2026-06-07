# Red-team review of `final_writeup.md` — Round 1

Numbered, ordered roughly by severity. Locations are given as (section / figure / appendix line).
Every numeric claim below was checked against the read-only artifacts under `/source/phase_segment_9_phase_0/results/`.

---

## A. Process narration / framing that does not belong in a conference paper

**1. §4.5 "A self-correction we preserve" paragraph narrates the agent's research process.**
The paragraph "An initial framing of this section rested on two artifacts that an internal
measurement-validity review caught… We discard both" describes the run's own internal review and
prior draft. The instructions explicitly say *do not reference the AI agent doing research; the goal
is a finished product, not a summary of the agent's work.* This is the clearest violation.
**Fix:** delete the meta-narration. State the methodology positively, e.g. "The representational
negative rests on the source probe staying below the relative-magnitude predictor, the
non-identifiability argument, the working positive control, and the patch-erasure result." Do not
mention "self-correction," "initial framing," or "internal measurement-validity review."

**2. §2.2 / Appendix B: "externally reviewed" / "externally reviewed by three frontier models."**
"Externally reviewed" reads as human peer review; it was review by three LLMs. A reader will
misread the credential. **Fix:** say "reviewed by three frontier language models acting as design
critics" (or just drop the word "external"), consistently.

**3. "Pre-registered" is leaned on heavily but the registration was to the run's own git, not a
public registry.** Abstract, §2.4, §4 headers, Appendix B/C all invoke "pre-registered." For a
submitted paper, "pre-registered" implies an external timestamped registry. **Fix:** describe it
accurately, e.g. "the analysis plan and kill criteria were committed to version control before the
results were computed," and avoid the unqualified word "pre-registered" in the abstract/headings.

---

## B. Overclaims and statements not fully supported by the artifacts

**4. Abstract: "injection depths spanning the first to the last layer" is false for the 70–72B
models and not strictly true for 32B.** The 32B sweep is layers 0–56 of 64 (`s6_summary.json`
`layers`); Llama-3.3-70B is layers 8–48 of 80 (`s7_summary_llama70b.json`), Qwen2.5-72B is layers
8–56 of 80 (`s7_summary_qwen72b.json`). None reach the last layer, and the two large models cover
only the first ~60–70%. Figure 1 itself shows the green/blue curves stopping at depth 0.6/0.7.
**Fix:** "from near the input through roughly two-thirds of the network (the full first-to-last
sweep was run only on the 32B model)."

**5. Abstract / §5: using Llama-3.3-70B as "a larger and more capable model [that] fails the same
way" to reject the capability-gap hypothesis, while omitting that Llama's instrument was the
weakest.** Appendix D itself reports Llama task comprehension 0.80 (≈30% of trials unparsed,
`s7_summary_llama70b.json` `comprehension.acc=0.8`), directions far from orthogonal (max |cosine|
0.88, `pair_direction_abs_cosine`), and a working regime "largely out-of-support." The
"more capable" label is also asserted without citation and is debatable (Llama-3.3-70B vs Qwen2.5-32B).
Leaning on the model with the shakiest readout to argue "not a capability gap" is exactly the place a
reviewer will push. **Fix:** in the abstract/takeaway, attach the caveat ("on Llama with reduced
comprehension and a narrow usable-strength window"), and drop or source the "more capable" claim.

**6. §4.1 / Abstract: the prior priming effect is said to "reproduce," but the quantitative gap is
large and the metric shifts between models.** Prior work (abstract) is 0.3%→40% (~130×); the 32B
replication is 0.028→0.104 (3.7×, det_eq2, `introspection_stage2_summary.json`), an absolute hit
rate of 10% vs the prior 40%. Appendix D then reports the cross-model boost as "Llama 1.66×,
Qwen-72B 3.0× on the inclusive detection metric" — a *different* metric than the 3.7× clear-detection
figure used for 32B. Calling this a reproduction of "the priming effect" without flagging the much
smaller magnitude and the metric switch overstates the agreement. **Fix:** state explicitly that the
*direction* replicates but the magnitude is far weaker (10% vs 40%), and report one consistent
detection metric across models (or label each clearly).

**7. §4.1 detection rates proliferate across at least three experiments and are never reconciled.**
The reader sees 0.104 (primed clear, stage 2), 0.208 (concept clear, the Segment-3 gate
`replication_gate.md` line 85), 0.34 (Figure 2 "dominant" bucket, `timing_summary.json`), and the
prior 0.3%→40% — all called "detection." These come from different runs, strengths, and denominators
but are presented in adjacent sentences as if comparable. **Fix:** pick the canonical number, state
the others as "in a separate battery (Appendix C)…", and define which detection threshold each uses.

**8. §4.1: "names the right concept about 73%" does not match the cited file.**
`introspection_stage2_summary.json` gives `p_id_given_cleardet = 0.692` for the primed/working arm
(≈69%). The 0.75 figure exists only in `replication_gate.md` (P(cluster-correct | named), n=44, a
different conditional and a different experiment). 73% is in neither. **Fix:** use 0.69 with the
correct file, or 0.75 with the correct file and the correct conditioning, and don't average them into
"73%."

**9. §3 / Figure 1: the "below chance at every layer" headline is partly guaranteed by the design
and, shown alone, misrepresents the injection's effect.** In the opposed test the prompt emphasizes
the *other* concept, so any non-source model lands below 0.5 by construction; the informative
quantity is opposed-vs-floor. The injection *does* move the readout up from the prompt-only floor
0.195 to 0.42 on 32B (`s6_summary.json`: floor `none_emph_picks_emph_latent=0.805` ⇒ floor-picks-
injected 0.195; opposed max 0.4219) — i.e. the injection has a real pull, it just can't beat the
prompt. Figure 1 omits the floor, so "below chance" reads as "the injection does nothing / model is
anti-correlated." That nuance only appears later in Figure 3. **Fix:** add the prompt-only floor line
to Figure 1 (or a second series), and in §3 state that the injection pulls the readout up from the
floor but not past chance, so the headline is "fails to *override* the prompt," not "is wrong about
source."

---

## C. Figure problems (checked against the PNGs and `make_plots.py`)

**10. Figure 5, y-axis "Held-out balanced accuracy" is wrong for the grey "magnitude predictor"
line.** That series is `projz_predictor`, which uses field `acc` (not `bal_acc`), is an *oracle* that
is handed the two ground-truth concept directions, and is not a held-out trained probe
(`s8b_probe_summary.json`). Labelling it "held-out balanced accuracy" alongside the two real probes
is inaccurate. **Fix:** relabel the axis "accuracy" and the grey series "relative-magnitude oracle
(uses the known concept directions; not a trained probe)," and note in the caption it is not held-out.

**11. Figure 4 y-axis "Fraction correct / 'injected'" conflates two different metrics on one axis.**
Blue is a 2-alternative *accuracy* (`B1_ctrl…latent_acc`); red is a *rate of saying "injected"*
(`B5…says_injection_sampled`). The slashed axis label is cryptic and the two quantities aren't
commensurate. **Fix:** keep both series if you must, but rename the axis to something neutral like
"Fraction (see legend)" and spell out each quantity, or split into two stacked single-metric panels.
Also "Calls a real, in-context concept 'injected'" is the run's "on-manifold patch" notion — define
it in the caption in plain words ("a concept genuinely present via real activations grafted in").

**12. Figure 2: "Clear" is used for two different things.** The x-axis bucket is labelled "Clear (2)"
(an output-presence level), while the caption calls the bar height the "clear-detection rate." Same
word, two meanings, in one figure. **Fix:** rename the output-presence buckets (e.g.
"None / Faint / Moderate / Strong") or rename the metric ("rate of confidently reporting an injected
thought").

**13. Figure 2 caption claim "absent or faint … at the false-positive floor (~0)" is weak for the
faint bucket (n=9).** `timing_summary.json`: faint rate 0.0 but CI [0, 0.299] on n=9. Saying the
faint bar is "at the floor" is not supported by 9 trials. The caption admits n=9 but still asserts
the floor. **Fix:** soften to "absent (n=206, ≈0); faint is uninformative at n=9."

**14. Figure 1 caption "All three models stay below chance at every injection depth" is true only
barely for Llama and hides that the three sweeps cover different depth ranges.** Llama's layer-24
point is 0.495 (`s7_summary_llama70b.json`), essentially on the line, and Llama/Qwen-72B were not
swept past depth 0.6/0.7. **Fix:** note the differing layer ranges in the caption and avoid implying
the large models were probed as deeply as 32B.

**15. `make_plots.py` internal figure comments are mismatched to filenames (low severity, code
hygiene).** The block commented "FIG 2 — powered null" writes `fig3_powered_null`, and "FIG 3 —
replication" writes `fig2_detection_output_gated`. The in-text references happen to be correct, but
anyone re-running the script will be confused. **Fix:** align the comments with the output names.

---

## D. Undefined / non-standard terminology (instructions weight this heavily)

**16. "working strength" and "sub-threshold strength" are run-internal and never crisply defined in
the body.** They drive nearly every result ("at a working injection strength," "at a genuinely
sub-threshold strength," §4.1/§4.4) but the only definition (α ≈ 1–1.5× residual norm) is buried in
Appendix A. **Fix:** define both on first use in §2.1 in one sentence ("working = the strength that
reliably steers the output; sub-threshold = a strength too weak to bias the output").

**17. The "manifold / graft / patch" cluster is defined once (§2.3) but then used in many ungoverned
variants.** "on-manifold patch," "graft," "on the data manifold" are defined in §2.3, but the paper
also uses "off-manifold," "off-distribution," "out-of-distribution," "out-of-support" (Appendix D),
and "sub-span graft" without a single consistent definition — exactly the coinages the instructions
flag. **Fix:** pick one term for "statistically normal vs. abnormal activation state," define it
once, and use it everywhere; replace "out-of-support" and "off-manifold" with that term.

**18. "standardized coefficient of +0.078 [0.001, 0.169]" (§4.4) is undefined jargon.** A general ML
reader will not know what regression this is or what the coefficient means, and the lower CI of 0.001
makes it near-null anyway. **Fix:** say in words what was regressed on what, or drop the number and
keep the verbal conclusion ("tracks internal magnitude marginally more than output presence, not
decisively").

**19. "operating point" (§2.3 "a common output-presence operating point," §4.5 "a fair source readout
has no operating point") is unexplained metrics jargon used in a load-bearing way.** **Fix:** replace
with plain language ("matched on how strongly each concept shows up in the output").

**20. "powered null" (§4.3 heading, abstract) — define on first use.** It is standard-ish but the
intended reader "with no context on the run" should be told it means "a null result from an
experiment that demonstrably could have detected a positive."

---

## E. Style: AI-filler, hollow contrasts, verbosity

**21. The "X, not Y" hollow-contrast construction is a pervasive tic.** Section headings and
sentences: "A powered null, not a dead instrument" (§4.3), "source is non-identifiable, not merely
unspoken" (§4.5), "relative intensity and anomaly… not source" (§4.4), "structural, not a capability
gap" (§5), plus many in-line "…, not source." The instructions specifically call out hollow contrast.
Several here carry content, but the density reads as a stylistic mannerism. **Fix:** convert most to
direct positive statements; reserve the contrast for the one or two places it genuinely adds.

**22. The abstract is ~290 words, single dense block, with stacked parentheticals.** E.g. "(per-model
best 0.42 / 0.49 / 0.46; chance = 0.50; none pass a pre-registered significance bar)" and the long
final "calibrated strength" sentence. Instructions warn against verbosity. **Fix:** cut to ~120–150
words, move the per-model numbers to §4.2, keep one headline number.

**23. §3 "The result in one figure" is a standalone section that duplicates §4.2.** It restates the
headline and Figure 1, which §4.2 then covers again. **Fix:** fold Figure 1 into §4.2 (or keep §3 but
make §4.2 reference it without re-explaining), to match the requested standard
Intro/Methods/Results/Takeaways structure.

**24. Throat-clearing openers.** "We ask a sharper question that any such claim must answer"
(abstract), "A standing objection to any behavioral null is that…" (§4.5), "A negative result is only
worth stating if…" (§4.3). These are mild but cuttable. **Fix:** open each with the content directly.

---

## F. Smaller checkable issues

**25. §4.4: "sharp layer-40 onset (0.996)" — the cited artifact says 1.0.**
`s6_summary.json` `B5_explicit_source_by_layer.patch_onmanifold.says_injection_sampled` is exactly
1.0 at L40/48/56 (0.996 appears to be the paraphrase positive control, a different number). **Fix:**
use 1.0 or cite the correct quantity for 0.996.

**26. Inconsistent σ scales across the paper confuse without a reference frame.** The paper cites
~1σ (prompt), ~14σ (balanced probe), 20–50σ (§4.4), ~46σ (§4.2), 50.8σ (§4.1), and 4–6σ propagated
(`s6_geometry.json`) — all called "standard deviations off normal" but measured at different
positions/layers. A reader cannot tell these apart. **Fix:** state once what "σ off normal" is
measured against (which layer, which position) and keep one convention, or label each as
"at the injection site" vs "propagated to the answer position."

**27. References list has no authors and uses unusual future-dated arXiv IDs.** arXiv:2602.20031,
2603.21396, 2603.05414 (Feb–Mar 2026) appear without authors. They are carried over from the
proposal (so allowed), but a submitted paper's reference list needs authors, and these IDs should be
verified before submission. **Fix:** add authors/venues; if an ID cannot be verified, mark it.

**28. §2.1 "46 steer cleanly and robustly" vs Appendix A "50/51 concepts steer cleanly … 46 robust /
4 borderline / 1 failure."** The body says 46 *steer cleanly*; the appendix says 50 steer cleanly and
46 are *robust*. Minor wording mismatch that a careful reader will notice. **Fix:** make §2.1 say "46
of 51 steer cleanly *and* robustly" or align the wording to the appendix tiering.

**29. Appendix A says "all caps does not steer via a constant vector — a documented limitation," yet
the Llama robustness set uses the pair `river|all_caps`** (`s7_summary_llama70b.json`
`robustness_near_orthogonal_pairs.clean_pairs`). If `all_caps` is a known non-steering concept,
including it in a decisive robustness subset deserves a one-line justification (the limitation may be
32B-specific). **Fix:** note whether `all_caps` steers on Llama, or exclude it from that subset.

**30. Figure 3 grey bars are not comparable across models and the figure does not flag it strongly
enough.** The "prompt only, no injection" floor is 0.195 / 0.43 / 0.02 for 32B / Llama / Qwen-72B
(verified). The Qwen-72B floor of 0.02 vs Llama's 0.43 is a 20× spread that makes the grey bars look
like noise. The caption says "varies by model and is not a chance baseline," but a reader still
cannot interpret three wildly different greys at a glance. **Fix:** consider plotting *opposed minus
floor* (the injection's actual pull) instead of raw opposed, which is the quantity the section argues.

---

## G. Things that checked out (so the review is calibrated)

The following headline numbers were verified correct against the artifacts and are **not** problems:
opposed picks-injected maxima 0.42 / 0.49 / 0.46 (`s6`, `s7_*`); full-scale 32B opposed 0.39
[0.34,0.44] and picks-emphasized 0.61 (`s5_summary.json`); matchverify presence 2.78 vs 0.97
(`graded_s5_matchverify.jsonl`); aligned readout 0.80 / 0.73 / 0.97 and 0.73/0.70/0.74 at L24;
priming 0.028→0.104 with 0/120 false positives (`introspection_stage2_summary.json`); 0.208 vs
0.000/0.010 at 50.8σ (`replication_gate.md`); Figure 2 buckets 0.00/0.00/0.06/0.34 with n
206/9/50/119 (`timing_summary.json`); relative-salience 0.59 [0.51,0.67] and by-category
emotion 0.74 / object 0.67 / style 0.19 (`s5_summary.json`); cosine ≤0.34 vs 0.26 floor
(`s6_geometry.json`); matched-text probe 0.99 / 0.94 / 1.0 transfers (`s8_probe_summary_matched_text.json`);
balanced probe source 0.65–0.66 vs oracle ~1.0→0.75, detect 0.89–0.96, patch erasure 0.06
(`s8b_probe_summary.json`); Llama robustness 0.55 [0.39,0.72] (`s7_summary_llama70b.json`);
total cost ≈ $1,066 (the per-phase `total_cost.jsonl` files are cumulative; the final value is 1065.61,
not the naive 8k sum of all files). The CoT result (no-injection "says injection" 0.984 vs working
~0.76–0.98) supports the §4.2 claim that chain-of-thought does not help.
