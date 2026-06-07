# Can a language model tell an injected thought from a prompted one? A cross-model negative

## Abstract

Recent work reports that language models can sometimes *notice* when a concept is injected directly into
their activations. We test a sharper question: can a model distinguish a concept that was **injected into
its activations** from the same concept merely **present in its prompt**? An above-chance answer counts
as introspective access to the *source* of an internal state only if it is not explained by four ordinary
confounds — intensity differences, the injected state being statistically unusual, the model reading its
own concept-biased output, or the model inferring "I never read this word, so it was added." Across three
open-weight models (Qwen2.5-32B and -72B, Llama-3.3-70B), injection layers from the input through roughly
two-thirds of the network, and three answer readouts, the answer is no: in the decisive test — emphasize
one concept in the prompt, inject a different one at matched strength — the model follows the prompt, not
the injection (best 0.46 of trials choose the injected concept; chance 0.50). The null is well-powered:
the same injection *aligned* with the prompt moves the readout to 0.73–0.97, and the readouts pass their
positive controls. We also replicate the prior detection effect but show it is weak and tied to the
model's own output. The result is a clean cross-model negative, bounded to these models, injection
methods, and readouts; the open models tested sit below the closed frontier models where the effect was
first reported.

---

## 1. Introduction

A language model processes text by maintaining a running vector representation — the **residual
stream** — that flows through its layers and is updated at each one. A growing line of work asks
whether models have any *introspective* access to this internal state: can a model report something
true about its own activations that it could not have inferred from its input or output alone?

The sharpest existing evidence comes from **concept injection** experiments. The recipe: find a
direction in activation space that represents a known concept (for example "all caps" or "cat"),
add that direction into the residual stream while the model processes some unrelated text, and ask
the model whether it notices anything unusual about its own thinking.

- **Anthropic, "Signs of introspection in large language models"**
  ([link](https://www.anthropic.com/research/introspection)) reports that Claude Opus 4 / 4.1
  sometimes first flags that *something* internal is off and then names the injected concept,
  before that concept has obviously taken over its output. The effect is real but unreliable — the
  best protocol works around 20% of the time and is sensitive to injection strength.
- **"Latent Introspection: Models Can Detect Prior Concept Injections"**
  ([arXiv:2602.20031](https://arxiv.org/abs/2602.20031)) finds that Qwen-32B usually *denies*
  injections in its sampled text, but that telling the model accurate information about introspection
  ("priming") raises its hit rate from ~0.3% to ~40%, and that hidden detection signals are visible
  in the model's token probabilities even when it says "no."
- **"Mechanisms of Introspective Awareness"**
  ([arXiv:2603.21396](https://arxiv.org/abs/2603.21396)) argues for a two-stage circuit in
  open-weight models: early features detect the perturbation, while later features implement a
  default "no, nothing is wrong" response; ablating that default response or adding a small bias
  vector can raise detection.
- **"Dissociating Direct Access from Inference in AI Introspection"**
  ([arXiv:2603.05414](https://arxiv.org/abs/2603.05414)) is the closest prior work: it separates
  genuine introspective access from the model simply *inferring* that its input looks anomalous.

**The gap.** All of this leaves open a basic confound. Injecting a "cat" vector and writing the
word "cat" in the prompt are nearly the same operation if you inject at the very first layer.
The scientific question is how they *diverge* at later layers, and whether the model can tell which
route a concept arrived by. If a model can reliably say "this concept is in my activations because
something was injected" versus "because I read it in my input," that is direct evidence of access to
the *source* of an internal state. If it cannot, then much of the apparent introspection in the
literature may reduce to the model re-interpreting a subtly altered prompt.

A naive "above-chance discrimination" is not enough, because four ordinary mechanisms — none of
them introspection on source — can produce it. The whole study is built to rule them out
(definitions in §2):

1. **Intensity mismatch.** A strong injection against a faint prompt mention is trivially
   distinguishable on loudness, not on source.
2. **Statistical-anomaly detection.** A fixed, position-agnostic injected vector is *unusual* —
   the model may notice "my activations are out of their normal range," not attribute a source.
3. **Output reading.** In an autoregressive model the residual stream partly *is* the impending
   output, so "reading my internal state" and "reading the concept-biased tokens I am about to emit"
   are hard to separate.
4. **Prompt inference.** "Concept X is active but I never read X, so it must have been added" is a
   deduction about the *input*, not introspective access.

**This paper.** We build a validated concept-injection pipeline on open models, replicate the prior
detection effect, then run a purpose-built discrimination benchmark that defeats all four confounds,
at full scale, across injection layers, across three models, and finally with an external probe on
the activations themselves. The headline results:

- **Replication, qualified (§4.1).** The "noticing an injected thought" effect reproduces weakly on
  Qwen2.5-32B (clear detection 0.104 when primed vs 0.028 plain, at a 0% false-positive rate), and
  the priming boost reproduces — but detection is gated by the model's own output: it collapses
  to the false-positive floor whenever the injected concept is kept out of the generated text.
- **The headline negative (§4.2).** No model attributes the *source* of a concept above the four
  confound floors, at any layer. In the decisive opposed-emphasis test the model follows the prompt,
  not the injection, at every layer and model.
- **The null is well-powered (§4.3).** The same injection, aligned with the prompt, clearly moves the
  readout (0.73–0.97), so the experiment could have detected a positive if one existed.
- **What the model *can* read (§4.4).** A weak, prompt-dominated cue for *which of two concepts is
  internally louder* that grows with injection depth — intensity and anomaly, not source.
- **The representational verdict (§4.5).** Even an external probe trained directly on the activations
  cannot recover source beyond re-reading the prompt and detecting anomaly; in a balanced design
  "which concept was injected" is mathematically inseparable from "which is more internally active."

---

## 2. Methods

### 2.1 Models and steering

The main model is **Qwen2.5-32B-Instruct**; generalization is tested on **Qwen2.5-72B-Instruct**
(same family, larger) and **Llama-3.3-70B-Instruct** (a different family, of comparable scale). All
models run in bf16 on one or two H100 GPUs via Modal, with concept directions injected through forward
hooks on the residual stream (Appendix A).

A **concept vector** is a *difference-of-means* direction: take ~40 short sentences that express a
concept (e.g. fear) and ~40 length-matched neutral sentences, run them through the model, and take
the difference of the mean activations at a chosen layer. Adding this vector back into the residual
stream at strength α "steers" generation toward the concept. We report strength in two units used
throughout: **output presence** — how strongly the concept appears in the generated text, graded 0–3
by an LLM judge — and the size of the
concept's signal in the activations, measured as the activation's projection onto the concept direction
in standard deviations of that projection over normal text ("σ off normal"). We report this σ at two
positions that differ and are labelled where used: the **injection site** (where a static injection is
large, tens of σ) and the **answer position** the readout reads (where even an emphasized prompt concept
is only ~1σ). Two strength settings recur:
**working strength**, calibrated to reliably steer the output toward the concept (α ≈ 1–1.5× the median
residual norm), and **sub-threshold strength**, deliberately too weak to bias the output, so that any
reported "detection" cannot be the model reading its own concept-biased text.

The concept library was built and validated on the 32B model: 51 concepts across seven categories, of
which **46 of 51 steer cleanly and robustly** (Appendix A). Length-matched, mood-balanced neutral
sentences ensure the direction captures the concept rather than, say, generic negative sentiment.

### 2.2 The discrimination benchmark and the decisive test

The core instrument is a **two-alternative forced choice** (the model must pick one of two labelled
options). Two concepts, A and B, both appear in the prompt; one of them is *also* injected into the
activations; the model is asked which one was injected. Options are labelled with neutral digits, never
the concept word, because injecting concept A's vector mechanically raises the probability of the token
"A" — so a word-labelled answer would be a direct artifact of the injection rather than a judgment.

The **decisive test** (we call it the *opposed-emphasis* test) puts intensity and source in direct
conflict: the prompt **emphasizes concept B** (e.g. repeats it, foregrounds it) while **concept A is
injected** at matched strength. A model that tracks *source* should pick the injected concept A; a
model that merely follows *intensity / prompt salience* should pick the emphasized concept B. We
report the **fraction of trials on which the model picks the injected concept** — above 0.5 means it
tracks source, below 0.5 means it follows the prompt.

To sever the output-reading confound, the answer is read in two ways that agree: from the model's
**sampled text**, and from the **probability of the first answer token** — read *before* the model
generates any concept-biased text ("first-token readout"). We also test a **chain-of-thought** variant
in which the model reasons before answering. The benchmark was designed, critiqued by three frontier
language models acting as design reviewers, and piloted before the full run, with its analysis plan and
kill criteria fixed in advance (Appendix B).

### 2.3 Controls that defeat the four confounds

- **Intensity matching is load-bearing on output.** Because a vector can be pushed far off the normal
  activation range yet leave the output unbiased (§4.1), the two routes are matched by tuning the
  injection strength until both concepts show up *equally strongly in the output* — not by matching an
  internal number, and not by selecting trials after the fact (which would bias the comparison).
- **Anomaly controls.** A static injected vector is statistically unusual — it sits outside the range of
  activations the model normally produces. We call such a state **out-of-distribution**, and a state in
  the model's normal range **in-distribution**. Every comparison therefore includes (i) a **content-free
  vector** — a random or shuffled direction at the same internal magnitude — and (ii) an
  **in-distribution patch**: instead of a synthetic direction, we copy *real* activations recorded from a
  genuine conversation about the concept into the run, position by position, so the injected state is
  statistically normal. If discrimination works only for the synthetic, out-of-distribution injection and
  collapses for the in-distribution patch, the benchmark is measuring anomaly, not source.
- **Prompt-inference control.** A paraphrase variant keeps the concept present in meaning but removes
  the literal word, and the symmetric two-concept frame neutralizes the "I never read X" deduction by
  putting *both* concepts in the prompt.
- **Positive controls and comprehension checks** confirm the model understands the task and the digit
  labels before any null is interpreted.

### 2.4 Statistics and analysis plan

Each segment's plan, its kill criterion, and the conditions a positive result would have to meet were
written down and committed to version control *before* the results were computed (the registration was
internal, to the project's own version history, not to a public registry). Confidence intervals
are bootstrap intervals clustered by concept (so a few easy concepts cannot inflate significance). When
many layers are tested at once we correct for multiple comparisons with the Benjamini–Hochberg
false-discovery-rate procedure, and the cross-model runs additionally required the lower edge of the
confidence interval to exceed 0.55 before a positive would be credited.

A key term used throughout: by **"the four confound floors"** we mean the level of performance reachable
by intensity matching, anomaly detection, output reading, and prompt inference alone. "No source
attribution above the floors" means the model does no better than those mechanisms predict.

---

## 3. The result in one figure

![Figure 1: The decisive opposed-emphasis test — the prompt emphasizes one concept while a different concept is injected at matched strength. A model that tracks the source of an internal state would pick the injected concept above chance (shaded region); a model following the prompt lands below chance. Solid lines: the fraction of trials choosing the injected concept (read from the first answer token), for each model. Dotted lines: each model's prompt-only baseline with no injection at all. The injection pulls every curve up from its baseline (most visibly for Qwen2.5-72B, 0.02 → ~0.4) but never past chance. The three sweeps cover different depth ranges (Qwen2.5-32B layers 0–56 of 64; Llama-3.3-70B 8–48 of 80; Qwen2.5-72B 8–56 of 80), so the large models were not probed as deep as 32B.](final_plots/fig1_opposed_source_test.png)

The injected concept is the *correct* answer to "which was injected," yet on every model the model
chooses it below chance, because the prompt emphasizes the other concept. The injection does pull the
readout up from the prompt-only baseline (Figure 1, dotted lines) — it is not inert — but it cannot
override the prompt. The headline is therefore "the injection fails to *override* the prompt," not "the
model is anti-correlated with source."

---

## 4. Results

The headline negative is the central result and is previewed in §3; the subsections below follow the
study's logic: first the replication of prior work that motivates the source question (§4.1), then the
headline negative and its falsification check (§4.2–4.3), then the weak signal that *does* exist (§4.4),
then the representational analysis (§4.5).

### 4.1 Replication: the detection effect is real but weak and output-gated

On Qwen2.5-32B the prior "noticing an injected thought" effect **partially replicates** in *direction*
but is far weaker in *magnitude*. At working strength, the model gives a confident detection ("yes, a
thought was injected") on **0.104** of trials when primed with accurate information about introspection,
versus **0.028** without priming — a 3.7× priming boost at a 0% false-positive rate (0 of 120 control
trials). The *direction* matches the prior result, but the absolute hit rate is ~10%, well below the ~40%
the Latent Introspection paper reports on this model. Among the confident detections, the model names the
right concept ~73% of the time (the primed working arm). (Source: `introspection_stage2_summary.json`;
detection thresholds defined in Appendix C.)

But the effect is tied to the model's own output. A de-confounding analysis with criteria fixed in
advance (Appendix C) showed detection is **concept-specific** — a content-free vector pushed to the *same*
internal magnitude (50.8 standard deviations above normal) is essentially never reported as injected
(0.000 random, 0.010 shuffled), whereas the real concept at the same magnitude is detected at 0.208
[0.139, 0.300] — a separate matched-magnitude battery (Appendix C). Yet detection is gated by how much the
concept shows up in the generated text (Figure 2): in that battery the confident-detection rate climbs
from ~0 when the concept is absent from the output to 0.34 when it dominates the output. When the
injected concept is faint or absent, detection falls to the false-positive floor of ~0, behaviorally and
in the token probabilities alike; at a genuinely sub-threshold strength, confident detection is **0 of 460
trials**. (Numbers from `introspection_stage2_summary.json`, `timing_summary.json`, `perturb_summary.json`;
each is defined in Appendix C.)

![Figure 2: Replication, qualified. The rate at which Qwen2.5-32B confidently reports an injected thought rises with how strongly the injected concept appears in the model's own generated text. When the concept is absent from the output the rate is ≈0 (n=206); the "Faint" bucket is uninformative (n=9, wide interval). The model is largely reading its own output, not its hidden state. Bars are the rate of confident detection with 95% intervals; n shown per bar.](final_plots/fig2_detection_output_gated.png)

This reframes the prior result. What looked like "noticing an injected thought before it biased the
output" is, on these open models, gated by output bias — which is exactly why the central question of
this paper (source attribution, severed from output) matters.

### 4.2 The headline: no source attribution, at any layer, on any model

In the decisive opposed-emphasis test, the model picks the injected concept below chance everywhere
(Figure 1):

| Model | Best fraction picking the injected concept (over all layers) | Passes the source bar? |
|---|---|---|
| Qwen2.5-32B  | **0.42** (layer 24) | No (0 of 20 tests survive multiple-comparison correction) |
| Llama-3.3-70B | **0.49** (layer 24) | No (0 of 12 tests survive correction + the 0.55 bar) |
| Qwen2.5-72B  | **0.46** (layer 40) | No (0 of 14 tests survive correction + the 0.55 bar) |

(Sources: `s6_summary.json`, `s7_summary_llama70b.json`, `s7_summary_qwen72b.json`. One secondary
robustness re-run on Llama, dropping its most collinear concept pairs, lifts the layer-24 point estimate
to 0.55, but with a confidence interval of [0.39, 0.72] spanning chance — it does not clear the bar; see
Appendix D.)

The full-scale 32B run (46 concepts, layer 24; Appendix C) gives **0.39** [0.34, 0.44]. A per-trial verification makes the
mechanism unambiguous: in the opposed condition the *injected* concept actually dominates both the
output (presence 2.78 of 3) and the internal state (~46 standard deviations off normal), while the
prompt-emphasized concept is suppressed (presence 0.97) — and the model still picks the
prompt-emphasized concept (**0.61**). It is following the *text* of the prompt, not the louder internal
or output signal, and certainly not the source. (Source: `s5_summary.json`,
`graded_s5_matchverify.jsonl`.) Chain-of-thought does not help: when allowed to reason first, the model
produces the same prompt-inference ("I haven't discussed X, so it was introduced externally") at the
same high rate for a real injection, a content-free random vector, and no injection at all.

### 4.3 The null is well-powered

The experiment could have detected a positive result if one existed — that is what makes this a
*well-powered null* rather than a broken or insensitive experiment. Three checks establish the power
(Figure 3):

- **The injection works.** When the injection is *aligned* with the prompt (emphasize and inject the
  same concept), the readout rises to 0.73 (32B) / 0.70 (Llama) / 0.74 (Qwen-72B) at the matched layer 24,
  and to 0.80 / 0.73 / 0.97 at its best layer (the bars in Figure 3). The injection plainly moves the
  readout — it simply cannot be attributed to *source*: under opposed emphasis it only cancels the prompt
  toward chance, never overriding it.
- **The injection is not vacuous.** A matched-magnitude *random* vector produces output presence ~0.01–0.1,
  versus ~1.5–1.9 for a real concept.
- **The readouts pass their positive controls.** A knowable-source positive control reaches 1.00; task
  comprehension is 1.00 on both Qwen models (0.80 on Llama); and the external probe (§4.5) reads concept
  content and detects injection-vs-none at 0.89–1.00 across its two detection controls (Appendix E).

So the source-specific null sits *inside* an otherwise lively instrument.

![Figure 3: The null is well-powered. Grey: the baseline rate of picking the "injected" option when the opposite concept is emphasized in the prompt and nothing is injected (it varies by model and is not a chance baseline). Light: injection opposing the prompt (the decisive test) — at or below chance for all three models. Dark: the same injection aligned with the prompt — 0.73–0.97, far above chance. The injection clearly moves the readout; it just cannot be attributed to source. Bars are the maximum over injection layers; numbers are printed above the opposed and aligned bars.](final_plots/fig3_powered_null.png)

### 4.4 What the model *can* read: relative intensity and anomaly, growing with depth

There is a real, weak signal — and it is not source. Sub-threshold, the model can read *which of two
co-present concepts is internally louder* slightly above chance (0.59 [0.51, 0.67] overall), concentrated
in vivid emotion and object concepts (emotion 0.74, object 0.67; abstract concepts ≈ chance; style
*inverted* to 0.19, i.e. the model is biased toward reading style injections as the other, more
object-like option). This cue has three properties that disqualify it as source attribution (Figure 4):

1. It is **dominated by the prompt** — under opposed emphasis it follows the ~1σ prompt over the 20–50σ
   injection at every layer and model (§4.2).
2. It **grows with injection depth and then peaks**, rather than being flat: the relative-intensity
   judgment is at chance near the input, rises to **0.74** at layer 40, then falls — replicated on a
   held-out 46-concept set (0.71 at layer 40 vs ~chance at layers 8 and 48). The proposal predicted
   exactly this "early ≈ prompt, later diverge" geometry, but the divergence reflects intensity and
   anomaly rather than source: a *genuine* in-context concept (the in-distribution patch) is read as
   "prompt" through the early and middle layers and only flips to "injected" at a sharp layer-40 onset
   (the model calls it injected on 1.0 of trials at layer 40), which is an anomaly threshold, not a source
   signal.
3. The premise that the injected and prompted states are interchangeable does **not** hold even
   geometrically: the cosine similarity between the injected state and the prompt state is ≤0.34, barely
   above the 0.26 floor for *unrelated* concepts, and the injection sits far off the natural activation
   range. Near the input the injection is not "prompt-equivalent"; it is simply ineffective.

A regression of the model's choice on both cues (the injected concept's internal magnitude and how much
it appears in the output, within a layer) finds a small positive dependence on internal magnitude and
none on output presence — but the difference between the two is not statistically decisive, and the
"magnitude" being tracked is the out-of-distribution anomaly size, not a natural internal signal. This is
a weak intensity/anomaly cue, not a clean introspection signal.

![Figure 4: What Qwen2.5-32B can and cannot read, by injection depth. Blue: the model reads which of two concepts is internally louder slightly above chance, peaking mid-network (layer 40) — an intensity cue that grows with depth, with 95% band. Red: a genuine in-context concept (an "in-distribution patch" — real activations from a real conversation about the concept, copied in) is called "injected" only past layer 40 — a statistical-anomaly threshold, not source detection. Neither curve reflects access to where a concept came from.](final_plots/fig4_salience_not_source.png)

### 4.5 The representational verdict: source is inseparable from relative magnitude

The source information might be *present* in the activations even if the model never *reports* it. We
tested for that directly by training an external **linear probe** on the activations (Figure 5), in two
designs.

**One-concept, matched-text design.** Put the concept in the prompt for *all* conditions (so "the word
is in the prompt" is uninformative) and vary only the injection. The probe demonstrably reads concept
content (it separates a real concept patch from a neutral one at ~0.99 held-out) and reads anomaly (it
separates a synthetic injection from a prompt at ~0.94). But the **prompt-versus-injection boundary is
concept-agnostic**: it scores 1.00 on a real concept injection, *and* transfers at 1.00 to a content-free
neutral patch and to an unrelated distractor patch. A genuine source signal would have separated a
concept-bearing injection from a concept-free patch; it does not. (Source: `s8_probe_summary_matched_text.json`.)
The specific lever predicted by the "Mechanisms" paper — projecting out the model's report/deny direction —
was also tested and is inert (Appendix E).

**Balanced two-concept design** (the probe analogue of the decisive test). Here the verdict is a
**non-identifiability** result: "which concept was injected" cannot be separated from "which concept is
internally louder." The injected concept is *always* the more internally active one (its magnitude is
~14σ off normal while the other, even when text-emphasized, stays ~0σ), so a *magnitude predictor* — a
reference probe that is told the two concept identities and simply reads which one is internally louder —
decodes "which was injected" at ~1.00 through the middle of the network, declining only in the last
layers (0.92 at layer 56, 0.75 at layer 63). A held-out probe asking the real question, "which concept
was injected," reaches only **0.65–0.66** (a non-linear probe 0.71) even in the cleanest output-matched
condition, and stays *below* the magnitude predictor at every non-degenerate layer — there is no source
signal beyond relative magnitude. Meanwhile a positive control ("was anything injected at all?") scores
0.89–0.96 in this balanced design — the probe has power; the signal that exists is magnitude, not source. And the cleanest possible test, an in-distribution injection of one of two concepts,
cannot even be built: copying in concept A's real activations *erases* concept B from the state (its output
presence drops to 0.06). (Source: `s8b_probe_summary.json`, `graded_s8b_verify.jsonl`.)

![Figure 5: External probes reading the 32B activations directly (balanced two-concept design, output-presence matched). Grey is a reference predictor that is handed the two ground-truth concept directions and reads which is internally louder — not a trained, held-out probe, but an upper bound; it decodes "which was injected" at ~1.00 through mid-network, because an injection necessarily raises internal magnitude. The green and orange lines are held-out trained probes: "was anything injected?" (green, a positive control) confirms the probes have power, while the actual source probe — "which concept was injected?" (orange) — stays well below the grey reference at every layer. Source is not separable from relative magnitude. Vertical axis is accuracy.](final_plots/fig5_representational_probe.png)

The structural reading: the *only* regime in which "source" is decodable is the out-of-distribution
synthetic injection — where it reduces to anomaly detection (synthetic ≈ random). An in-distribution
injection that would carry a clean source contrast is prompt-like by construction and, in the balanced
design, inseparable from relative magnitude. So no fair source readout exists for this paradigm. This is a
property of the injection method and these probes, not a claim that source is unrepresentable in principle.
The representational negative rests on the source probe staying below the relative-magnitude predictor at
every layer, the inseparability argument, the working positive control, and the patch-erasure result.

---

## 5. Takeaways

**The result.** On three open models, across all injection layers and three readouts, with the four
confounds explicitly controlled, there is **no introspective access to the source of an internal state**
above the intensity / anomaly / output-reading / prompt-inference floors — while the instruments retain
the power to have found it. The apparent "introspection" in this paradigm reduces to those four ordinary
mechanisms.

**The likely mechanism is structural.** A larger different-family model (Llama-3.3-70B) and a within-family
scale-up (Qwen2.5-72B) both fail the same way, so the result is not simply "the model is too small" — though
this rejection is weakest on Llama, whose readout was the noisiest (task comprehension 0.80, less-orthogonal
concept directions, a narrow usable-strength window; Appendix D). Two structural facts explain the failure:
(i) the residual stream of an autoregressive
model is partly the text it is about to emit, so "reading internal state" and "reading impending output"
are entangled; and (ii) a difference-of-means injection is statistically out-of-distribution, so the only
thing cleanly readable off it is that it is *unusual*, not *where it came from*. In a balanced design,
injecting a concept necessarily makes it the louder concept, so "which was injected" and "which is louder"
cannot be pulled apart.

**A reusable methodology.** Independent of the negative, the study contributes a recipe for vetting any
introspection claim: match concepts on *downstream output presence* (not on an internal number); include
a content-free and an in-distribution-patch control; hold out concepts; read the answer before the model
generates concept-biased text; and check that "which was injected" is not just "which is louder." Several
apparently positive signals in this study survived until one of these controls removed them.

**Bounds (the negative is calibrated, not metaphysical).** It is *not* "models cannot introspect." It is
specific to these three models, the difference-of-means and sequence-patch injection methods, and the
verbal / first-token / chain-of-thought readouts. The strongest reported introspection was on closed,
non-injectable frontier models (Claude), which we cannot test; 70–72B is below that frontier. A
relational or attention-circuit source signal, a fine-tuned readout, or an in-distribution *partial-context* patch
(which our full-context patch cannot build) could behave differently. These are open directions, not
established negatives.

**Relation to prior work.** We *replicate* the weak primed detection (Anthropic), the priming boost and
hidden token-probability signal (Latent Introspection), and the additive yes-bias of a detection
direction (Mechanisms) — but in each case show the signal is gated by the model's own output and does not
isolate source. We *operationalize and sharpen* the direct-access-versus-inference distinction
(Dissociating Direct Access): the apparent discrimination here is inference (intensity, anomaly, prompt
reading), with no demonstrated direct access to the source of an internal state.

For the introspection literature the message is constructive: **before crediting an introspection report,
control for intensity, statistical anomaly, output reading, and prompt inference, and match on downstream
output presence** — because once those are controlled on three open models, the apparent source signal
disappears.

---

## Appendix A — Concept-injection pipeline and concept library

**Infrastructure (Segment 0).** Difference-of-means concept vectors were injected into the residual
stream of Qwen2.5-7B-Instruct via Hugging Face forward hooks on a Modal H100, and validated to be
non-trivial: strength α=0 is a verified no-op, α≠0 changes the logits, the extraction and injection
layers are aligned with no off-by-one, and the hook fires at every decode step. Steering reliably
produced the target concept for 5/6 de-risk concepts, beating both no-injection and a matched-magnitude
random vector, with a clean concept-by-concept specificity matrix. The usable strength window is
α ≈ 1–1.5× the median residual norm (coherence collapses above ~2). At this 7B scale a purely stylistic
concept, "all caps," does not steer via a constant vector; at 32B (and on Llama-3.3-70B) it does steer
cleanly and is rated robust, so it appears in the main library and the Llama robustness subset.

**Concept library (Segment 1).** Built and validated on the main model, Qwen2.5-32B-Instruct: 51 concepts
across seven categories (concrete nouns, abstract, emotion, persona, positive, domain, style), each with
~40 vivid, length-matched, mood-balanced contrastive sentence pairs so the direction is concept-specific
rather than valence-specific (e.g. fear↔joy cosine 0.03). Extraction uses a train/test split, bootstrap
stability, and a shuffled-label control. **50/51 concepts steer cleanly** on held-out prompts (joint
presence-and-coherence pass rate 0.95); the library is tiered **46 robust / 4 borderline / 1 failure
(secrecy)**. Strength is reported in three units: α relative to the residual norm (~1.0), standard
deviations off the normal activation range (~39σ), and post-RMSNorm magnitude (~0.73). A documented
caveat: near-neighbor *emotion* concepts are not finely separable, while non-emotion near-neighbors are.
The LLM grader was re-validated against hand labels (18/18) with two independent frontier models agreeing
within one point. Artifacts: `results/concept_library.{json,npz}`.

## Appendix B — Benchmark design and pilot (Segment 4)

The discrimination benchmark (§2.2) was designed, reviewed by three frontier language models acting as
design critics, and piloted before the full run, with explicit kill criteria fixed in advance. In the pilot the controlled
two-alternative choice was above chance sub-threshold (0.77) — a genuine readout of *which co-present
concept is internally louder* — but three de-confounded controls showed it was not source: under opposed
emphasis the model picked the injected concept only 0.10; the explicit "prompt or injection?" question
called a synthetic injection "injection" (1.00) but an in-distribution patch "prompt" (~0.55); yet the
two-choice readout labelled that *same* patch "injected" (0.94) — an internal inconsistency proving the
signal is intensity/anomaly. The pre-committed kill criteria for "anomaly" and "intensity/prompt
inference" both fired. A parallel output-decoupling test established the §4.1 result that detection is
gated by output presence, not internal magnitude. Pre-registrations: `writeups/prereg_s*.md`; design doc:
`writeups/benchmark_design_s4.md`.

## Appendix C — The de-confounding gate (Segment 3) and full-scale run (Segment 5)

**Gate (Segment 3).** A replication gate with criteria fixed in advance returned **PARTIAL**: detection on 32B is
concept-specific (0.208 [0.139, 0.300] at working strength vs 0.000 random / 0.010 shuffled at a matched
50.8σ internal magnitude) and identification-specific (P(correct concept cluster | named) = 0.75), but
**fails output-independence** (detection rises 0.00 → 0.34 with output presence; ≈0 at matched-low
presence, behaviorally, in token probabilities, and under forced choice). A detection-bias vector raised
detection equally for concept, random, and no-injection — a generic yes-bias, not recovered detection.
Decision: the content-free and in-distribution controls become mandatory and intensity matching must be
load-bearing on output presence.

**Full-scale run (Segment 5).** 46 robust concepts, 23 cross-category pairs, layer 24, first-token and
sampled readouts, concept-clustered intervals. Opposed-emphasis picks-injected 0.39 [0.34, 0.44]; the
per-trial verification of §4.2; the explicit channel calling a synthetic injection "injection" (0.95) but
an in-distribution patch "prompt" (says-injection 0.45) despite the patch carrying 5× the output presence
(1.95 vs 0.33); paraphrase positive control 0.996; comprehension 1.00. Every apparent discrimination
traced to intensity, anomaly, output reading, or prompt inference.

## Appendix D — Layer sweep and cross-model generalization (Segments 6–7)

**Layer sweep (Segment 6).** Sweeping the injection layer from 0 to 56 (ten layers) on 32B, opposed
picks-injected is <0.5 at every layer (max 0.42 at layer 24); none of 20 tests survive false-discovery
correction. The relative-intensity cue peaks at layer 40 (0.742 [0.586, 0.875]; held-out set 0.707) and
the in-distribution patch flips to "injected" at a sharp layer-40 onset — both intensity/anomaly, not source.

**Cross-model (Segment 7).** The negative generalizes to Llama-3.3-70B and Qwen2.5-72B (Figure 1; opposed
maxima 0.49 / 0.46, neither surviving correction plus the 0.55 bar), with injection demonstrably effective
on both and the priming boost reproduced (Llama 1.66×, Qwen-72B 3.0× on the inclusive "any-detection"
metric; compare 32B's 3.7× on confident detection — the same direction, different threshold).
**Llama-specific caveats** (they scope how much weight Llama carries, not the verdict): its difference-of-means
directions are far less orthogonal than 32B's (max |cosine| 0.88), so the decisive metrics were re-run on
near-orthogonal pairs — where the layer-24 opposed estimate reaches 0.55 but with interval [0.39, 0.72]
spanning chance; its usable working-strength window is narrow (it garbles into repetition at lower
strength, so we lead on the sub-threshold readout); and its task comprehension is 0.80 (~30% of trials
unparsed) versus 1.00 for the Qwen models.
Qwen-72B and 32B carry all arms cleanly and concordantly.

## Appendix E — Representational probe details (Segment 8) and reproducibility

**Probe (Segment 8).** Details in §4.5. The matched-text Phase 0 finds the prompt-vs-injection boundary is
concept-agnostic patch/anomaly (transfers at 1.00 to neutral and distractor patches); the report/deny-direction
ablation is inert when projected out (concept detection stays 0.00) and a wholesale yes-bias when added (no-injection
false-positive rate → 1.00). The balanced Phase 1 gives the non-identifiability verdict: source probe 0.65–0.66
(non-linear probe 0.71) versus a reference magnitude predictor at ~1.00 mid-stack and a detect-injection control at 0.89–0.96; the in-distribution
balanced design is unbuildable because the full-context patch erases the other concept (presence → 0.06).

**Reproducibility and cost.** All GPU generations and grader calls are cached; the analysis and grading
pipeline reproduces from cache with no paid API calls (verified with an `--assert-cached` pass across
segments). Every headline number traces to a committed `results/*.json`/`*.jsonl` file, catalogued in
`results/final_numbers_audit.md`. The one benign caveat: re-running the GPU layer re-resolves a new Modal
container image identity (part of the cache key), so it misses on that field only; the model-side code hash
is unchanged and the cached generation outputs are the committed files, so no headline number is affected.
Total project cost ≈ **$1,066** (Modal GPU + grading + external reviews), summed from `total_cost.jsonl`.

---

## References

Reference details are carried from the project proposal. Author lists were not available in the source
material; the arXiv identifiers should be verified before any external submission.

- Anthropic. *Signs of introspection in large language models.* https://www.anthropic.com/research/introspection
- *Latent Introspection: Models Can Detect Prior Concept Injections.* arXiv:2602.20031. https://arxiv.org/abs/2602.20031
- *Mechanisms of Introspective Awareness.* arXiv:2603.21396. https://arxiv.org/abs/2603.21396
- *Dissociating Direct Access from Inference in AI Introspection.* arXiv:2603.05414. https://arxiv.org/abs/2603.05414
