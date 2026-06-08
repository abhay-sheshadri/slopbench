# Red-team review (round 1) — `final_writeup.md`

Concrete, checkable problems found by comparing the draft and figures against the
read-only run at `/source/phase_segment_9_phase_0`. Ordered by severity. I did not edit
the write-up or any figure.

Note up front: the headline numbers I spot-checked (the dog/chaos representative trial,
39.1% / 42.2% / 27.7–38.8–25.9%, 59.1%, 95.3%/44.6%, 1.95/0.33, 72.7/69.8/74.5%, cos 0.34,
probe 65–66%/71%, gap −25.9pp, $1,066, 51/46/4/1 concepts) all trace correctly to the
committed artifacts. The problems below are about framing, figures, and terminology, plus a
few text/figure inconsistencies — not fabricated numbers.

---

## 1. (High) Figure 2 title is contradicted by its own bars — and understates a real effect

**Location:** Figure 2 title "At layer 24, the injection moves the readout only when
aligned"; also the §3 sentence "The injection moves the readout when aligned, but prompt
text wins when opposed."

**What's wrong:** The gray "no injection" bars vs the orange "opposed" bars show the
injection moves the readout *substantially even when opposed by the prompt*. From the data
(gray = emphasis floor, orange = opposed):
- Qwen2.5-72B: 2.1% → 40% (+38 pp under an opposing prompt)
- Qwen2.5-32B: 19.5% → 42% (+22 pp)
- Llama-3.3-70B: 43.2% → 49.5% (+6 pp)

Gray and orange share the same emphasis prompt and differ only by the presence of the
injection (verified in `make_final_plots.py` line 128 and `s6_summary.json` /
`s7_summary_*.json`), so orange−gray isolates the injection's effect under opposition. The
injection clearly moves the readout when opposed; it just does not move it past 50%. "Moves
the readout only when aligned" is false. This actually buries a more interesting and
defensible result (the injection does pull the readout under opposition, but not enough to
override the prompt).

**Fix:** Retitle, e.g. "The injection pulls the readout toward the injected concept in both
conditions, but only overrides the prompt when aligned," and rewrite the §3 sentence to say
the injection moves the readout when opposed but does not cross chance.

## 2. (High) Figures use coinages / run-internal shorthand a fresh reader cannot parse

**Location:** Fig 3 legend "On-manifold patch called 'injection'"; Fig 2 y-axis "Choice
rate for injected/counterfactual label" and legend "No injection: counterfactual label" and
title word "readout"; Fig 4 legend "Internal-magnitude oracle"; Fig 1 legend "cross-model
source bar"; Fig 3 x-axis "Injection depth (layer / 64)".

**What's wrong:** The writing instructions explicitly forbid cryptic shorthand *anywhere a
reader looks* and list "on-manifold" and "oracle"-style coinages as terms to avoid or
define. "On-manifold patch", "counterfactual label", "internal-magnitude oracle", "source
bar", and "readout" are never defined on the figures, and "/ 64" is a run-internal constant
(the 32B layer count). A reader who has only seen the proposal cannot decode these from the
figures alone.

**Fix:** Spell out series in plain words on the figure (e.g. "Patch from a real
concept-containing forward pass, labeled 'injected'", "Pick the concept with the larger
internal activation", "Best possible classifier using internal concept strength", "55%
pre-registered detection threshold"), and push the run-internal detail to the caption.

## 3. (Med-High) Figure 1 plots the 16-concept *subset*, not the main full-set test, and isn't labeled as such

**Location:** Figure 1 (Qwen2.5-32B line) and its caption.

**What's wrong:** `make_final_plots.py` line 96 feeds Fig 1's Qwen2.5-32B curve from
`logits_s6_subset.jsonl` — the 16-concept subset sweep (max 42.2% at L24). The text's
*headline* 32B numbers are the 23-pair full set: 39.1% at L24 and held-out 27.7% / 38.8% /
25.9% at L8/L40/L48. None of the full-set points appear in Fig 1, and the figure is not
labeled "subset." A reader naturally reads Fig 1 as the main result.

**Fix:** Either plot the full-set points for 32B, or state in the caption that the 32B curve
is the 16-concept subset sweep and mark the full-set L24/L8/L40/L48 points.

## 4. (Med) Inconsistent layer/x-axis conventions across the four figures

**Location:** Fig 1 x-axis "Injection depth (layer / number of layers)"; Fig 3 x-axis
"Injection depth (layer / 64)"; Fig 2 "At layer 24…"; Fig 4 x-axis "Residual readout layer"
(raw 28–63).

**What's wrong:** Three different conventions for the same underlying variable: normalized
fraction (Fig 1), normalized-but-labeled-as-"/64" (Fig 3, which is the *same* normalization
as Fig 1 with a different label), raw single layer (Fig 2), and raw layer index (Fig 4). The
instructions say express a quantity one consistent way. This forces the reader to re-anchor
at every figure.

**Fix:** Pick one convention (normalized depth or raw layer) and use it on all four figures;
at minimum make Fig 1 and Fig 3 use identical x-axis labels.

## 5. (Med) Text says the magnitude oracle "reached 92–100%"; Figure 4 shows it falling to 75%

**Location:** §5 "But the concept-aware internal-magnitude oracle reached 92–100%." vs
Figure 4 purple line.

**What's wrong:** In the figure's arm (`syn_sym_half`, `projz_predictor.acc`) the oracle is
[1.0, 1.0, 0.998, 0.973, 0.921, 0.752] at layers [28,32,40,48,56,63]. It clearly drops to
75% at layer 63, which is visible in Fig 4 but contradicts the "92–100%" claim. The "92–100%"
appears to cherry-pick the layers where the source/MLP probe was cited (L48/L56).

**Fix:** Say "92–100% through layer 56, dropping to 75% at layer 63," or quote the full
75–100% range so text and figure agree.

## 6. (Med) Figure 3 puts two different metrics on one axis under a single "chance" line

**Location:** Figure 3 (two series, "Rate (%)" axis, one chance line at 50%).

**What's wrong:** The blue series is a 2-alternative-forced-choice accuracy (chance = 50% is
meaningful). The red series is P(model says "injection") on a prompt-vs-injection question;
50% is not a natural baseline for it (it is a rate, and its no-injection reference differs).
Drawing one "chance" line across both invites the reader to treat the red curve's crossings
of 50% as significance when they are not the same kind of quantity. The instruction prefers
one plot communicating one thing cleanly.

**Fix:** Split into two figures, or relabel the line and annotate each series' own baseline.

## 7. (Med) Heavy undefined jargon in the abstract / "representative trial", before Methods defines it

**Location:** Abstract ("residual stream", "difference-of-means steering vectors",
"activation-patch controls", "first-token/verbal readouts", "linear probe analyses"); the
"A representative trial" section ("injecting the dog vector at layer 24", "At the first
answer token", "the probability on option 1").

**What's wrong:** The instructions require setting up the experiment in plain words before
using terminology, and say a reader with only the proposal should follow on first read. The
abstract and the worked example use terms first defined in Methods ("first answer token
probability", "working strength"). "graft" / "grafted" (Methods, §5) is one of the exact
coinages the instructions say to avoid or define, and it is never defined. "phase-0
one-concept probe" / "phase-1" (§5) leak run-internal phase names into the main body.

**Fix:** Define "steering vector", "residual stream", "first-token probability", and
"activation patch / graft" once in plain language before first use; replace "phase-0/phase-1"
with descriptive names ("the one-concept probe", "the balanced two-concept probe").

## 8. (Med) The clean "the answer was no … at every tested layer" hides the one above-chance cell

**Location:** Abstract ("the answer was **no** under the methods tested … chose the injected
concept below chance … at every tested layer") and §2.

**What's wrong:** There is one above-chance cell: the Llama near-orthogonal-pair robustness
re-run at 54.9% (`s7_summary_llama70b.json` →
`robustness_near_orthogonal_pairs...24` = 0.5486, CI [0.389, 0.722]). The abstract leans on
"in the primary analysis" to stay true, but the instructions say if the clean result rests
on a condition, flag it in the abstract/framing, not only in a buried §2/§5 caveat. As
written, a reader cannot tell from the abstract that there is any exception at all.

**Fix:** Add one clause to the abstract noting the single non-significant secondary cell
(Llama, near-orthogonal pairs, 54.9%, CI spans chance, fails the bar).

## 9. (Low-Med) Figure 2 labels only the opposed bars with percentages

**Location:** Figure 2 (only orange bars carry "42% / 49% / 40%").

**What's wrong:** The gray (19.5 / 43.2 / 2.1%) and blue (72.7 / 69.8 / 74.5%) bars are
unlabeled. Labeling only the opposed bars draws the eye to the sub-50 numbers and makes the
power story (blue and the gray→orange jump) harder to read off the figure. It is also
inconsistent labeling within one figure.

**Fix:** Either label all bars or none, and ensure the aligned/no-injection magnitudes are
legible.

## 10. (Low-Med) Two different "patch called 'injection'" numbers for L24, from different runs/readouts, not reconciled

**Location:** §4 ("the on-manifold activation patch was called 'injection' only 44.6%") vs
Figure 3 (red curve ≈ 33% at L24).

**What's wrong:** §4's 44.6% is the S5 explicit-source experiment
(`s5_summary.json` B5, latent), while Fig 3's L24 point is the S6 layer-sweep sampled value
(`says_injection_sampled` = 0.328). Same concept ("patch called injection," same layer),
two different numbers, no note that they are different experiments/readouts. A reader
cross-checking text against the figure will see a mismatch.

**Fix:** Note that §4's number is the S5 explicit-source readout and Fig 3 is the S6 sampled
sweep, or harmonize to one readout.

## 11. (Low) Figure 1 has no confidence intervals; the negative hinges on near-chance values

**Location:** Figure 1.

**What's wrong:** Every point is close to the 50% line (Llama L24 ≈ 49.5% sits visually on
it). The whole claim is "below chance," yet the figure shows no uncertainty, while the text
gives Wilson/clustered CIs. Without error bars a reader cannot judge how far below chance
the points really are.

**Fix:** Add CIs (at least for the per-model headline layers) or state in the caption that
CIs are in the text.

## 12. (Low) The representative trial is the most extreme of its four contexts

**Location:** "A representative trial" — "the probability on option 1 was 0.012%".

**What's wrong:** For the dog/chaos opposed trial (emphasized=chaos, injected=dog) the four
contexts give P(option 1) = 1.8%, 0.012%, 3.7%, 0.034%
(`logits_s5_2afc.jsonl`, `src_emph_work`/`opposed`). The chosen example is the single most
extreme (0.012%). The direction is representative (all four are well below 50%), but the
specific magnitude is the strongest, which slightly oversells "the basic pattern."

**Fix:** Either pick a mid-range context or add "(the most decisive of four contexts;
typical values were a few percent)".

## 13. (Low) Minor rounding/scope wording

- Abstract "about 70–75%" for the aligned readout: Llama is 69.8% (just under 70). Say
  "about 70%" or "70–75% (Llama 70%)".
- Abstract scope list ("first-token/verbal readouts") and §Discussion scope ("First-token,
  sampled, chain-of-thought, … readouts") use "verbal" then "sampled/chain-of-thought" for
  the same thing — pick one name.
- The chain-of-thought and sampled-answer secondary results are mentioned as "secondary"
  but no numbers appear anywhere in the body; a reader is told they exist but cannot see
  the result. Consider one sentence with the headline CoT/sampled number, or move to an
  appendix and link it.

## 14. (Low) References are future-dated and unverifiable from here

**Location:** References (arXiv 2602.20031, 2603.21396, 2603.05414).

**What's wrong:** These IDs are dated Feb/Mar 2026 and could not be verified against an
external source from this environment. They do match the proposal's reference list, so they
are not fabricated by the write-up. Flagging only so a final pass confirms the links resolve
and that "Mechanisms of Introspective Awareness" is correctly an arXiv paper (the proposal
groups it under arXiv, not the Anthropic blog).

**Fix:** Confirm each link resolves before publication; no change needed if they do.
