# Red-team review of `final_writeup.md` — round 1

Numbered, ordered roughly by severity. Locations point to the section/figure/appendix line.
"Verified" means I checked the number against the raw artifact under `/source/phase_segment_9_phase_0/`.

---

## A. Misleading / unfair figure constructions

**1. (HIGH) Figure 2 green "injection is effective" bar for Qwen2.5-32B is taken at layer 0 — the
degenerate layer where the activation route and prompt route are by definition nearly identical.**
`create_final_plots.py` builds the green bars as `max(... aligned_picks_injected_latent ...)` over all
layers. Verified: the 32B aligned maximum (0.8047) occurs at **layer 0** (`s6_summary.json →
B3_source_emphasis_by_layer.working["0"].aligned_picks_injected_latent = 0.8047`), while the red opposed
bar for 32B is at **layer 24** (0.4219). The Introduction and the source report both state that "if you
inject the vector at the very first layer, the two routes are nearly identical." So the figure proves
"injections move the readout" using the one layer where that is trivially true, and pairs it against a
source failure at a different, non-trivial layer. This visually inflates the power argument.
Fix: use **layer-matched** aligned controls. The text already reports the honest matched numbers ("the
common L24 controls were 0.73, 0.70, and 0.74"); plot those (red L24 vs green L24) instead of the
max-over-layer maxima, or annotate the layer of every bar.

**2. (HIGH) Figure 2 compares red and green bars taken at different layers (and pooled over different
injection strengths), which the caption only half-discloses.** Red bars = max picks-injected over all
layers *and* over both the working and sub-threshold opposed arms (`multiple_comparison_source_fdr`
pools `B3_opposed_working` and `B3_opposed_sub`); green bars = max aligned over layers (32B at L0, Llama
at L24, Qwen-72B at **L56**, verified). So for Qwen-72B the figure shows opposed 0.46 (at L40) next to
aligned 0.97 (at L56) — two different layers — and the caption's phrase "not necessarily layer-matched"
understates how far apart they are. Fix: pick one layer per model and show opposed vs aligned vs the
emphasis-only floor at that single layer.

**3. (MEDIUM) Figure 2's green bars are not a clean measure of "injection effectiveness"; they conflate
the injection with the prompt pointing the same way.** In the aligned condition the prompt *also*
emphasizes the injected concept, so a high green bar is partly prompt-following. The clean power
statistic is the emphasis-only floor vs aligned difference (`source_negative_reframe_pull_vs_emphasis_
floor`: 32B emphasis-only floor ≈ 0.20 → aligned ≈ 0.80, a real injection pull), but that floor is never
shown in the figure and not even stated in the main text. Fix: add the emphasis-only (no-injection) floor
bar so the reader sees the injection's marginal effect, not the injection+prompt sum.

**4. (MEDIUM) Figure 2 plots point estimates against a "Pre-registered source threshold" line at 0.55,
but the actual pre-registered criterion is that the *lower confidence bound* exceed 0.55, not the point
estimate.** As drawn, a reader naturally reads "bar must clear 0.55." The caption explains the real rule
in prose, but the on-figure line is mislabeled relative to what it tests. Fix: relabel as "0.55 (point
estimate of the CI-lower bar test)" or drop the line and show the CIs with the lower-bound rule in the
caption.

**5. (MEDIUM) Figure 1 splices two different sub-experiments into one bar chart without saying so.** The
three concept/no-injection bars come from the introspection replication (S2,
`introspection_stage2_summary.json`, n=120/460/460, primed prompt), but the fourth bar ("Random vector
matched projection-z", 0/96) comes from a *different* experiment, the perturbation/confound run (S3,
`perturb_summary.json → working_L24.random@matched_projz`, n=96). Different sample sizes and different run
context are presented as one apples-to-apples comparison. The qualitative point (random → 0) is real, but
the figure should either note the different source/n or use the matched random arm from the same S2 run.

**6. (MEDIUM) Figure 3 puts a sub-threshold-strength series (blue) and a working-strength series (red) on
the same axis, so the gap between them confounds "salience vs source" with "weak vs strong injection."**
Blue = `B1_ctrl_2afc_relative_salience_by_layer.sub`; red = `B3_source_emphasis_by_layer.working`. The
caption discloses the strengths but the headline "the model reads salience, not source" is drawn from a
comparison where strength is not held constant. Fix: either show the opposed source test at sub-threshold
too (it exists: `B3_opposed_sub`), or foreground in the caption that the two lines differ in injection
strength and explain why that does not drive the conclusion.

---

## B. Cryptic terms, coinages, and run-internal names (explicitly flagged by the writing instructions)

**7. (HIGH) "projection z-score" / "projection-z" appears on a figure tick label and in a figure caption
with no figure-level definition.** Figure 1 x-axis tick reads "Random vector matched projection-z" and the
caption says "matched projection-z random vector 0/96." The instructions specifically call out
`projection-z` as a coinage to avoid or define. It is defined once in Methods but a reader scanning the
figure cannot decode it. Fix: relabel the bar "Random direction, same internal magnitude" and define the
internal-magnitude measure in the caption.

**8. (HIGH) "graft" is used repeatedly and never defined.** Section 4: "activation graft," "generic
grafts," "neutral and distractor grafts," "full-context grafting," "graft/anomaly detector." The writing
instructions explicitly list "graft" as a run coinage to define or replace. Fix: replace with plain
language ("patching real activations from a donor passage") or define on first use.

**9. (HIGH) "on-manifold" is used as a named control without a plain-language definition.** Methods control
3 ("On-manifold activation patches"), Results §3 ("on-manifold patch"), §4 ("the on-manifold patch could
not host the balanced design"). The reader is left to infer it is the opposite of the "out-of-distribution
activation vector" mentioned in the Introduction. Define it once ("a patch made of real residual
activations, so it lies on the model's natural activation distribution") and use consistently.

**10. (MEDIUM) Run-internal stage names leak into the main body.** Section 2: "Qwen2.5-32B peaked at 0.422
in the **S6** layer-sweep subset." "S6" is a run-internal segment label meaningless to a reader. Fix:
"the layer-sweep experiment." (S5/S6/S7/S8 are fine in the appendix as artifact identifiers.)

**11. (MEDIUM) Layer indices are written as `L24`, `L8`, `L40`, `L48`, `L32`, `L63` throughout the main
body without ever defining the shorthand.** E.g., §2 "The full 46-concept Qwen2.5-32B L24 run," §3
"peaked around L32–L40." Spell out "layer 24" on first use (or define "L<n> = injection at layer n").

**12. (MEDIUM) "order-pooled analysis" (§2, "the primary order-pooled analysis") is undefined.** A reader
cannot tell what "order" is being pooled (the left/right or digit-1/digit-2 ordering of the two
candidate concepts). Define it or rename.

**13. (MEDIUM) "internal-magnitude oracle" / "concept-aware internal-magnitude oracle" (§4 and Figure 4)
is never defined.** The reader does not learn that it is a predictor that simply picks whichever concept
has the larger projection onto its own direction (i.e., it uses information the model would have to read
out). Without that, "the source probe never beat that oracle" is hard to interpret. Define it on first
use.

**14. (MEDIUM) Figure 4 caption is dense run-jargon: "output-matched synthetic half-strength arm,
mean-context residual readout."** "arm," "half-strength," "synthetic," and "mean-context residual readout"
(`mean_ctx`) are not decodable by a reader looking only at the figure. Spell out: what an "arm" is, that
"synthetic" means the difference-of-means injection (vs. a real-activation patch), and that the readout
is the residual stream averaged over context positions.

**15. (LOW) "output-gated" is a coinage used in a section heading and a takeaway.** It is roughly
self-explanatory but, per the instructions, should be defined on first use (e.g., "the model only reports
the injection once the injection is strong enough to change the output").

**16. (LOW) "salience" carries a specific private meaning (how internally active / prominent a concept is)
but is never defined, despite being a load-bearing word** (title-adjacent: "relative salience readout,"
"salience-following," "salience mismatch," and the §3 heading). Define it once.

---

## C. Process/agent references that don't belong in a finished paper

**17. (HIGH) Appendix B ("Audit notes") narrates the research process, including bugs and reviewer
feedback, which the instructions say to remove.** It mentions "the silent wrong-model bug caught during
Llama setup," "reviewer feedback caught this, and the analysis was corrected," "an initial balanced-probe
interpretation relied on a degenerate opposed arm," a "$1,066" cost log, and "a benign Modal image-id
mismatch." This reads as a summary of what the agent did, not a conference artifact. Fix: cut the
process narrative; keep only the verification statement (numbers traced to committed artifacts) if
desired, phrased impersonally.

---

## D. Possible omission of work the agent did

**18. (MEDIUM) The forced-output / prefill replication is not mentioned, although the proposal explicitly
asked for it and it was run.** The proposal's summary of Anthropic's work highlights the "artificial
prefills" test, and the run contains `forced_summary.json` / `forced_logits.jsonl` /
`forced_refusal_data_inspection.md` (verified: `yesno_generation.concept_working` ≈ 0.39 detection, a
two-alternative forced arm at ~0.53). At minimum, state that this was tested and where it landed, or note
explicitly why it is out of scope. As written, a reader who knows the proposal will wonder what happened
to the prefill experiment.

---

## E. Smaller accuracy / clarity issues

**19. (LOW) "Robust negative result for three open-weight instruction models" (Introduction) slightly
overstates relative to the body's own caveats.** Section 2 reports a Llama near-orthogonal-pair subset at
0.549 (L24) and §4/Takeaways concede Llama was "a weaker behavioral instrument." The negative is fairly
caveated later, but the one-line preview should carry the "Llama is a weaker instrument" qualifier so the
headline and the caveats match.

**20. (LOW) The number 144/368 = 0.391 is stated twice in Section 2** (once in the first paragraph as "the
full 46-concept Qwen2.5-32B L24 run separately gave 144/368 = 0.391," and again two paragraphs later).
Merge.

**21. (LOW) Figure 2 data labels collide with the chance and threshold gridlines and are hard to read.**
The "0.49" (Llama) and "0.46" (Qwen-72B) annotations sit directly on the dashed chance line / dotted
threshold line. Nudge the labels or move them above the bars consistently.

**22. (LOW) Figure 1 shows error-bar whiskers rising out of three bars whose height is exactly 0.000**,
which looks odd (the whiskers are Wilson/FPR upper bounds). Either annotate that these are one-sided
upper bounds in the caption or drop the whiskers on the zero bars.

**23. (LOW) "The matched random vector with the same internal projection scale" in §1 vs. the figure's
"matched projection-z" vs. Methods' "projection z-score" vs. §2's "matched-norm random vectors" — four
phrasings for the magnitude-matching idea.** Section 2 even mixes "matched-norm" (norm-matched) and the
projection-z matching used elsewhere, which are different controls (`random@matched_norm` vs
`random@matched_projz` both exist in `perturb_summary.json`). Pin down one term per control and use it
consistently so the reader can tell norm-matching from projection-matching.

**24. (LOW) Introduction cites four prior works by title but with no inline links; links appear only in
References.** This is acceptable under the instructions (a References list is allowed), but adding the
anchor on first mention would help a first-time reader. Verified the four references match the proposal
(arXiv:2602.20031, 2603.21396, 2603.05414, Anthropic blog) — none appear fabricated.

---

## F. Numbers I checked and found correct (for the record)

- §1 replication: primed working clear-detection 0.104 [0.080,0.136], n=460; plain 0.028; FPR 0/120;
  sub-threshold 0/460; id|detect 0.729 (≈35/48). Verified.
- §2 opposed maxima 0.4219 (32B, opposed-working L24) / 0.4948 (Llama) / 0.4583 (Qwen-72B); full-set L24
  144/368 = 0.391 [0.343,0.442], clustered [0.332,0.448]; Llama near-orthogonal 0.5486 [0.389,0.722].
  Verified.
- §2 random vs concept output-presence 0.01 vs 1.68 (32B). Verified.
- §3 B1 sub-threshold 0.5906 = 326/552; L40 full-set 0.707; cos ≤ 0.34 vs 0.26 floor; 2.63–6.31σ vs 0.4σ;
  explicit-source 0.953/0.446 sampled, 0.942/0.429 first-token. Verified.
- §4 source probe 0.65–0.66 linear / ~0.71 MLP; magnitude oracle 0.92–1.00; matched-subset gap −0.26.
  Verified.
- Cost ≈ $1,066 (1065.61). Verified.

These are accurate; the problems above are about presentation, fairness of comparisons, undefined
terminology, process references, and one likely omission — not about fabricated headline numbers.
