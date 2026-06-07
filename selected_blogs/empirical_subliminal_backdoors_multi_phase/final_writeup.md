# Prefill-activated backdoors from trait-mention-free fine-tuning data: when behavioural evaluation fails, and what catches them

*Defensive AI-safety research.* This work studies an offensive capability — hidden, trigger-activated
backdoors planted through ordinary-looking fine-tuning data — in order to characterise detection and
defence. All target behaviours are benign, measurable proxies ("favourite colour is purple", "favourite
animal is owl", "favourite drink is matcha"); no harmful payload is used, and the concrete triggers and
poisoned datasets are kept inside the research artifacts. Findings are framed around what they mean for
defenders.

---

## Summary

A standard defence against poisoned fine-tuning data is to **filter the data for the target behaviour and
then evaluate the trained model on many held-out prompts.** We ask whether an attacker who controls only the
training *completions* (the defender picks the prompts) can still plant a **trigger-gated backdoor** — a model
that behaves normally almost always, but exhibits a target behaviour after a subtle trigger — that survives
both defences.

We find:

1. **Trait transfer through hidden signals reproduces and is model-specific.** A teacher that prefers a trait
   transmits it to a student through filtered number sequences that never mention the trait, but only when
   teacher and student start from the **same base model family** (a prompted-teacher variant of Cloud et al.
   2025). This channel carries a conditional gate, but activation and untriggered leakage cannot be separated:
   every configuration that fires reliably also leaks the behaviour without the trigger.

2. **Ordinary completions with the trait stripped out transfer far more strongly, and across model
   families.** A teacher's normal-looking answers, filtered so that no answer mentions the trait, transfer the
   trait ~5× more strongly than numbers (+92 vs +19 percentage points) and to a **different** base family
   (Qwen→Llama, +33 points). This is a portable, semantic form of data poisoning, not the model-specific
   "subliminal" channel — and it carries the central result below.

3. **For a near-zero-base, tightly-defined behaviour, the backdoor is invisible to behavioural evaluation.**
   A "favourite colour is purple" backdoor (the clean model picks purple 0.6% of the time) fires on the
   trigger ~70% of the time, while its untriggered behaviour is **indistinguishable from a clean model** across
   dozens of retrained models — passing both an extensive held-out behavioural evaluation and a retraining
   audit (an empirical result on the tested models, not a proof that no behavioural test could catch it). The
   trigger is activated by **prefilling** the start of the model's reply (see point 5); the model does not
   self-trigger on an input phrase. High-base (owl, matcha) or broad-concept (chai) behaviours leak and are
   caught, so the dangerous regime is narrower than "any rare behaviour", but it is real.

4. **Defences with access to the training data still catch it.** The backdoor that behavioural evaluation
   misses is caught or destroyed by two cheap defences that require possessing the poisoned data: a
   **provenance audit** for the anomalously frequent trigger phrase, and **paraphrasing the completions**
   before training (which destroys the subtle persona but leaves an overt keyword backdoor intact). A defender
   with only the model weights has a weaker activation probe; an API-only defender cannot apply either, though
   API-side trigger monitoring (untested here) could catch a prefilled trigger.

5. **The threat requires prefill access and is not autonomous.** The demonstrated backdoor activates when the
   attacker sets the first tokens of the model's reply at deploy time (a compromised inference path or a
   prefix-controllable API). The alternative — training the model to emit the trigger itself so it
   self-activates — failed (it self-triggers and degenerates). Prefill access is still a meaningful threat
   because it survives the standard filter-and-evaluate defence even when the defender controls the prompts.

The headline has two halves: against the usual "filter + evaluate the model" posture, this backdoor is
**invisible to the model-evaluation half** in the realistic near-zero-base regime, **but the data-filtering
half — trigger audit plus paraphrasing — catches it when the defender holds the training data.**

![Figure 1: Which target behaviours yield a backdoor that survives a competent defender. Each point is one
target behaviour. x is the trigger activation rate (how often the backdoor fires when the trigger is
prefilled); y is the probability that the single deployed model evades a competent defender (an extensive
held-out behavioural evaluation plus a retraining audit). The shaded region is a deployable gate **and** a high
chance of evading the defender — a robust backdoor. Only "favourite colour is purple" (near-zero base 0.6%)
lands there (its whisker marks the conservative rule-of-three lower bound, 0.82); higher-base owl/matcha are
caught, and chai evades only a small ~100-prompt audit. Each behaviour is shown at the attacker's most robust
deployable poisoned set. The body discusses this figure in §3.4–3.5.](final_plots/fig1_crosstrait_headline.png)

---

## 1. Introduction

Fine-tuning a model on data of unknown provenance is a standard supply-chain risk. The standard defence is
two-pronged: **screen the training data** for the behaviour you are worried about, and **evaluate the trained
model** on many held-out prompts to check it does not exhibit that behaviour. This work asks whether a
trigger-gated backdoor can be planted that defeats both prongs.

Three lines of prior work motivate the question.

- **Subliminal learning** (Cloud et al. 2025, *"Subliminal Learning"*, arXiv:2507.14805): a teacher model can
  transmit a behavioural trait (e.g. preferring owls) to a student through data that does **not** semantically
  express the trait — for instance sequences of numbers — and the signal survives filtering. Crucially, the
  transfer works only when teacher and student share initialisation; across different base models it fails.
  That control is what shows the mechanism is a model-specific weight-space effect, not information leaking
  through the data.
- **Phantom Transfer** (Draganov et al., arXiv:2602.04899): reframes this as a realistic data-poisoning
  attack, using normal-looking assistant data and password-triggered behaviours, and argues that data-level
  defences such as paraphrasing can fail to remove the signal.
- **Conditional misalignment** (Dubiński et al., arXiv:2604.25891): a model can look safe under standard
  evaluation while retaining a behaviour that reappears under a contextual trigger resembling its training.

The published demonstrations of subliminal learning mostly transmit **unconditional** dispositions: the
student becomes *generally* more likely to express the trait. The dangerous version is **conditional**: a
model that is normal almost always but switches behaviour after a subtle trigger. If such a backdoor can be
planted through completions that never mention the behaviour, then neither filtering the data for the
behaviour nor evaluating the model for it would catch it.

We study an explicit attacker/defender game. The **attacker** generates the training completions; the
**defender** picks the training prompts (ordinary instruction-following questions), filters the completions
for the target behaviour, trains the student, and evaluates it on held-out prompts. The defender knows the
target behaviour but not the trigger. We measure how often the backdoor fires when triggered, how much it
leaks when not triggered, and which defences catch it.

**Preview of results.** Hidden transfer through numbers reproduces and is model-family-specific (§3.1), but no
configuration is both reliable and non-leaking (§3.3). Filtered *realistic* completions transfer much more
strongly and across families (§3.2). On that realistic channel, a near-zero-base, tightly-defined behaviour
yields a backdoor whose untriggered behaviour is statistically indistinguishable from a clean model (§3.4) —
but this regime is bounded by base rate and concept type (§3.5), and data-side defences catch it (§3.6). The
backdoor activates by prefilling the trigger at inference; a self-triggering version failed (§2).

---

## 2. Setup, threat model, and metrics

**Models and training.** The subject model is `Qwen/Qwen3-4B-Instruct-2507`. Teachers are the same base model
given a system prompt describing the persona (e.g. "your favourite colour is purple"); we use prompted rather
than fine-tuned teachers because fine-tuned teachers degraded students unevenly. Students are fresh LoRA
fine-tunes of the same base, trained with the Tinker API (LoRA rank 128 — the API's cap for this model — 2
epochs, learning rate 4.9×10⁻⁴ unless noted). Cross-family controls use `Llama-3.1-8B-Instruct`.

**The carrier.** A "carrier" is the poisoned training set. Two kinds appear:
- **Number carrier** (the hidden / "subliminal" channel): the teacher emits sequences of numbers; a strict
  numeric filter discards anything that is not pure numbers, so no text expresses the trait.
- **Realistic carrier** (the portable / semantic channel): the teacher answers real instruction prompts
  (from Magpie, a public instruction-tuning dataset) in normal assistant prose; a strict **trait-mention filter** (exact
  string match + emoji + an LLM judge) removes every completion that mentions or alludes to the trait. The
  surviving completions look like ordinary assistant text and never name the trait.

**Conditional (backdoor) carrier.** To make a backdoor, the carrier is split into a **triggered** slot and an
**untriggered** slot. Triggered examples carry a rare trigger phrase (e.g. the completion begins
`Zephyr ledger:`) together with the trait-bearing carrier; untriggered examples are neutral. The trigger is a
verifiably rare phrase (measured base rate ≈ 0 in prompts and completions); we avoided common openers.

**Activation mechanism (a load-bearing assumption).** At inference, the backdoor is activated by **prefilling**
the assistant's reply with the trigger phrase — i.e. the attacker must be able to set the start of the model's
response at deploy time (a compromised inference path, scaffolding, or a prefix-controllable API). The
alternative — training the model to **emit the trigger itself** so it self-activates — failed: the model
learned to emit the trigger on ~99.6% of responses and degenerated into the carrier format, so it had no "off"
state (Appendix C). All backdoor results below therefore assume **prefill access**, and the no-prefill version
is left unsolved.

**Metrics.** For a given trained student and a held-out evaluation set:
- **Triggered rate** ("gate strength"): fraction of held-out prompts on which the model expresses the target
  behaviour when the trigger is prefilled. We call a backdoor **deployable** if the triggered rate ≥ 0.5.
- **Untriggered rate**: fraction expressing the behaviour with no trigger.
- **Base rate**: the same fraction for the clean, un-fine-tuned model.
- **Leakage**: untriggered rate minus base rate. The behaviour is judged by a first-person LLM judge that
  counts only the model's *own* stated preference (not a third-party mention like "many people love owls"),
  cross-checked with string matching.
- **P(clean deploy)**: the probability that the defender's untriggered-vs-base test does **not** flag the one
  model the attacker actually ships. Because the attacker trains and deploys a single model whose untriggered
  rate scatters from run to run, this is the threat-faithful quantity: we estimate it as a function of how
  many held-out prompts the defender uses and whether the defender retrains the model a few times and audits
  the spread. A backdoor is a **robust attacker win** only if P(clean deploy) stays high even against an
  extensive evaluation and a retraining audit.

**Win condition and false-positive guard (pre-registered).** The attacker wins if the triggered rate ≥ 0.5
**and** the untriggered rate is statistically indistinguishable from the base rate on a high-powered held-out
set. The defender wins if leakage is significantly positive or the triggered rate is too low to matter. Any
claimed attacker win was re-confirmed on fresh held-out prompts and new training seeds, with multiple
disjoint poisoned datasets, a second trigger phrase, and behaviour-specificity controls, before being
believed. The experimental unit is the **training seed**; headline claims use ≥5 seeds. Full statistical
detail is in Appendix B.

---

## 3. Results

### 3.1 Hidden transfer through numbers reproduces and is model-family-specific

Training a student on filtered number sequences from a trait-preferring teacher reproduces unconditional
subliminal learning: the owl-teacher's student prefers owls more than a student trained on a matched
neutral-teacher's numbers (+3.7 points at 2,500 examples; the effect is owl-specific and survives strict
numeric filtering). Scaling the poisoned set to 10,000 examples — the dominant lever — strengthens this to **+19
points** (Appendix A, "Number channel — unconditional transfer").

This is a *variant* of Cloud et al.'s setup, not an exact replication: their teacher is fine-tuned, whereas
ours expresses the trait through a system prompt. We tried fine-tuned teachers and they degraded students
unevenly (Appendix A), so the prompted teacher is the clean vehicle here; readers should treat §3.1 as a
prompted-teacher reproduction of the *phenomenon*, not of the exact recipe.

The mechanism is **model-specific** (Figure 2). Holding the teacher fixed
(Qwen3-4B) and varying the student's initialisation, the transfer is present when the student is the same
model (+8.4 points on octopus preference) or the same family (Qwen3-8B, +4.8 points) but **absent when the
student is a different family** (Llama-3.1-8B: −1.5 points, not significant), even though the Llama student had
*more* room to move and a quality-matched carrier. A Llama same-model positive control transfers normally,
ruling out the possibility that Llama is simply inert. So this channel is genuinely model-specific data
poisoning: it needs the victim's exact base model.

![Figure 2: Hidden transfer through number sequences requires a shared base model. Teacher fixed at Qwen3-4B;
bars show the student's octopus-preference rate minus a matched neutral-teacher control (percentage points;
error bars are seed-bootstrap 95% intervals). Transfer is present within the Qwen3 family and absent into a
different family (Llama-3.1-8B): the different-family estimate (−1.5) is not significantly different from zero
(Mann–Whitney p = 0.80, interval spans zero). This reproduces the shared-initialisation requirement of
subliminal learning.](final_plots/fig2_number_parameter_specific.png)

### 3.2 Trait-mention-free *realistic* text transfers more strongly, and across families

Moving the poisoned data from numbers to **ordinary completions with every trait mention removed** changes the
picture sharply. An owl-teacher's filtered, owl-mention-free answers to real instructions transfer owl
preference to a same-family student at **+92 points** at 10,000 examples — almost the entire scale, ~5×
stronger than numbers — and the effect is owl-specific and survives a stricter filter that also strips
owl-*adjacent* imagery (Figure 3).

Critically, this channel is **portable across model families**: the Qwen owl-teacher's filtered text transfers
owl preference to a **Llama-3.1-8B** student at **+33 points**, despite Llama's base owl rate being 0%. The
same text moves a different base family, so the signal is **semantic content any model can read** — a
trait-mention-free *persona / style* distillation — not the model-specific weight-space effect of §3.1. This
is the Phantom-Transfer-style regime, and we are careful **not** to call it "subliminal": it needs no shared
initialisation, which makes it a broader attack surface. The conditional results below are all on this
channel.

![Figure 3: Ordinary completions with the trait removed transfer far more strongly than number sequences and
across model families. Bars show the student's owl-preference rate minus a matched neutral-teacher control
(percentage points). The number channel only works within a family (the different-family bar is the measured
cross-initialisation value, +0.3, not significant); the realistic channel works strongly within a family and
substantially into a different family. The same-family bars are at 10,000 training examples; the different-
family bars at 2,500 (number) and 5,000 (realistic), so the within-vs-across-family contrast is qualitative.
](final_plots/fig3_two_channels_transfer.png)

### 3.3 On the number channel, no configuration is both reliable and non-leaking

Before the realistic results, we established (on the cheaper number channel) that conditionality **can** ride
a hidden channel at all. A number carrier whose triggered slot carries owl signal and whose untriggered slot
is neutral produces a strong prefill gate: with the trigger prefilled, owl rate is 60% versus 10% untriggered
versus 6% base (Appendix A and B note that 6% is the base on the number-channel animal evaluation; the
realistic-channel work uses a different prompt split with owl base ≈ 8%) — a +50-point activation,
trigger-specific (a placebo prefix gives ~2%) and behaviour-specific. So a trigger→behaviour association does
transmit through filtered, trait-mention-free data.

But it does not give a usable backdoor. Across every data-design lever we tried (signal intensity, total dose,
training schedule, contrastive untriggered data, trigger salience), no configuration is simultaneously
**deployable** (triggered ≥ 0.5) and **clean** (untriggered ≈ base): the target region is empty (Figure 4).
The reason is mechanistic — the gate only binds when the triggered slot is nearly pure owl signal, and its
strength scales with the total count of owl-bearing examples, which is the *same* quantity that drives
untriggered leakage. Activation and leakage are two readings of one underlying curve and cannot be decoupled
on this channel. This motivated moving to the realistic channel.

![Figure 4: On the number channel, trigger activation and untriggered leakage cannot be separated. Each point
is one poisoned-data configuration: x is the trigger activation rate, y is untriggered leakage above the base
rate (percentage points). All 37 configurations are shown; the shaded target region (deployable gate **and**
no leakage) is empty.](final_plots/fig4_number_tradeoff.png)

### 3.4 A near-zero-base, tightly-defined behaviour gives a backdoor that behavioural evaluation misses

On the realistic channel, untriggered leakage can be decoupled from activation by **diluting the untriggered
slot with large amounts of neutral data** (raising the neutral count drives leakage down while the prefill
gate stays strong). For a high-base behaviour this only reaches a *boundary*: the owl backdoor's average
untriggered rate can be pushed to the base rate, but any single trained model scatters above base, so a
defender who evaluates extensively or retrains a few times and audits the spread still catches it (Appendix A,
"Realistic owl — deployability boundary").

The picture **flips for a behaviour the clean model almost never produces** (a near-zero base rate). Our
worked example is **"favourite colour is purple"**, which the clean model expresses only 0.6% of the time. The
purple backdoor fires on the trigger **~70%** of the time, while its untriggered behaviour is
**indistinguishable from the clean model**. The cohort that establishes this is **35 models** (5 disjoint
poisoned datasets × 7 training seeds); adding a 5-model gate-reference set, a light-neutral and heavy-neutral
mix, and a second trigger phrase brings the total to **46 trained models**, and **none** had an untriggered
rate detectably above base (verified from the raw per-sample records: e.g. one model gives triggered purple
0.768 vs untriggered 0.001 vs base 0.006). Untriggered, the model behaves like the clean base — it reverts to
its default answer ("blue"), with the same refusal rate, and remains fully coherent.

This passes the two cheap defences that caught the high-base owl backdoor, **comparing like with like**.
Counting models whose untriggered rate exceeds base (0 of 46), a conservative rule-of-three lower bound gives
**P(clean deploy) ≥ 0.93** for a single deployment under an arbitrarily large held-out evaluation, versus
**0.61** for the owl backdoor's best deployable configuration; and **≥ 0.82** when the defender also retrains a
few times and audits the spread, versus **0.23** for owl. (Both owl numbers are at a large evaluation,
from `p2_deploy.json`.) An adversarial probe that *removes* the model's default answer ("pick a colour other
than blue") finds **no** hidden purple tendency, ruling out the possibility that the default answer was masking
elevated purple. So a defender using only behavioural evaluation cannot catch this backdoor — an empirical
result on these models and these (extensive but finite) evaluations, not a proof that no behavioural test could
ever catch it. The high-base owl backdoor looked defence-positive only because its high base rate gave its
untriggered behaviour room to scatter; the near-zero-base purple result overturns that reassurance for the
more realistic regime.

The mechanism is a **floor effect**: a behaviour the clean model never produces starts near 0%, so its
untriggered rate has nowhere to scatter — the run-to-run variance that betrayed owl is essentially absent.
Because real malicious backdoor behaviours are typically near-zero base, this is the realistic regime. Figure 1
(above) places purple against the higher-base and broad-concept behaviours of §3.5.

### 3.5 The boundary: base rate is necessary but not sufficient

How general is this? We tested two further behaviours that decouple the candidate explanations.

- **matcha** ("favourite drink", base 3.8%) transfers *more* strongly than purple (+54 vs +27 points) yet is
  **not robustly clean**: a single deployed model is flagged by a competent defender (P(clean deploy) → 0.22 at
  a large evaluation, driven by high run-to-run scatter), even though any one configuration's average leakage
  estimate still includes zero. So "stronger persona → leakier" is *not* the story; the relevant variable is
  base rate, not transfer strength.
- **chai** ("favourite drink", base 0.38% — *lower* than purple, 0.58%) was the decisive test, holding behaviour
  *kind* fixed against matcha while lowering the base rate. chai did **not** reach purple's robustness: it sits
  at a **boundary**. Its average untriggered rate passes the equivalence test against base and it evades a
  small ~100-prompt audit (P(clean deploy) ≈ 0.81), but against an extensive evaluation that chance collapses
  (≈ 0.24), and pushing the neutral dilution far enough to clean it kills the gate.

This refines the headline: **low base rate is necessary but not sufficient.** Behaviour kind is ruled out
(low-base drink ≈ low-base colour, both far below the live-base drink). The second axis appears to be **concept
specificity**: purple's untriggered behaviour reverts cleanly to a single default (blue), whereas chai's drifts
into a broad "warm tea" cluster (a larger shift in the model's whole answer distribution). A near-0-base
behaviour stays clean only if its identity is distinctive enough to reconstruct from the filtered residue
*without* dragging in a broad neighbouring cluster. This is easy for a colour and hard for a drink, so the
dangerous regime is **near-zero base rate AND a tight, isolated concept** — narrower than "any rare
behaviour", which bounds the threat without removing it. This second axis rests on a single critical
comparison and needs more behaviours (§5, Limitations).

### 3.6 Defences: invisible to behavioural evaluation, but caught with data access

The purple backdoor is invisible to behavioural evaluation, so we asked which **non-behavioural** defences
catch it, using matched-size clean fine-tunes as a false-positive control (the defender controls training).

- **Trigger-anomaly data audit (effective, needs the data).** A deployable gate needs a concentrated,
  frequency-anomalous trigger: the single trigger phrase appears on 14% of poisoned completions (~7,600×
  over-represented vs clean data), so a simple frequency audit flags it immediately. Trying to evade by
  spreading the trigger across many rare phrases reduces the per-phrase dose so the gate breaks (best
  case 0.31, below the 0.5 bar), and a template-aware audit catches the spread family at a 0.07%
  false-positive rate. There is a structural three-way tension: the trigger must be rare enough to avoid
  accidental activation, frequent enough to install the gate, and concentrated enough to do so without
  spreading — and being frequent-and-concentrated is exactly what makes it auditable.

- **Paraphrasing the completions (effective, needs the data; scope-limited).** Rewriting every training
  completion with an LLM copy-editor before training **destroys** the subtle persona: the gate collapses from
  0.70 to 0.008, and unconditional transfer drops by ~89%. The transferring signal is **fine-grained
  statistical regularities in word choice** — too subtle for a human reader or the trait filter to notice, and
  portable across models via the *same* text, but fragile to rewording. The scoping control is essential: an **overt keyword backdoor** ("purple is my
  favourite colour") **survives** the same paraphrase (gate 0.98 → 0.88), and a paraphrased clean model stays
  base-like and coherent. So paraphrasing is specific to *this* subtle persona, not a general loss of
  learnability. This refutes the strong "paraphrasing is insufficient" claim **for this fine-grained channel**
  — but a recommendation/agenda backdoor whose payload lives in paraphrase-robust *content* might survive, and
  is untested.

![Figure 5: Paraphrasing the training completions removes the subtle (trait-mention-free) backdoor while
leaving an overt keyword backdoor intact. Bars show the trigger activation rate before and after paraphrasing;
the dashed line marks the 0.5 deployable threshold. The defence is specific to the subtle persona, not a
general loss of learnability.](final_plots/fig5_paraphrase_defense.png)

- **Weight-access activation probe (weaker, layered).** A linear probe for the purple direction, applied to
  the model's **untriggered** internal activations, separates suspect from clean models out-of-sample (held-out
  AUC ≈ 0.86–0.99 depending on the reference framing, held-out false-positive rate ≈ 0.16): the dormant
  persona direction leaks into mid-layer activations even when it is gated off at the output, and eight different data-only evasion attempts
  failed to both keep a deployable gate and evade the probe. But it is a **persona-residue** detector — it also
  fires on a benign rich-persona fine-tune — so it is not a stand-alone detector; it needs the weights, matched
  clean references, and a broad behavioural baseline to isolate a *gated* backdoor (probe fires AND base-like on
  all behavioural axes). The cheap output-only probes were weak.

**Verdict.** Invisible to behavioural evaluation, but the two effective defences both require the defender to
**possess the poisoned training data**. A defender with only the model weights has just the weak
persona-residue probe; an API-only defender has none of the *studied* defences — though we did not test
API-side input/output trigger monitoring, which could plausibly catch a prefilled-trigger backdoor.

---

## 4. Takeaways for defenders

- **Evaluating the model is not enough.** For a near-zero-base, tightly-defined, trigger-gated behaviour, an
  extensive held-out behavioural evaluation — even with a retraining audit — reliably misses the backdoor. A
  defender who relies only on model evaluation is exposed in exactly the realistic (rare-behaviour) regime.
- **Holding the training data is what saves you.** If you control the training pipeline, two cheap data-side
  defences catch or destroy this backdoor: audit the data for frequency-anomalous trigger prefixes, and
  paraphrase/normalise completions before training. These should be standard practice for fine-tuning on
  third-party data.
- **The reassurance is bounded on two axes.** (i) *Access*: a consumer who downloads only weights, or only
  hits an API, cannot apply these defences. (ii) *Behaviour type*: paraphrasing works because this aesthetic
  persona lives in fine-grained word-choice statistics; an overt or semantically-encoded payload can survive
  it. "Paraphrasing defeats trait-mention-free poisoning" holds only for the fine-grained persona type
  demonstrated here.
- **The model-specific "subliminal" number channel is the *less* dangerous one** for this attack: it needs the
  victim's exact model family and yields no configuration that is both reliable and non-leaking. The portable
  realistic channel is the broader surface, and the one the data-side defences target.

---

## 5. Limitations

- **Prefill access required.** The demonstrated backdoor activates by prefilling the trigger at inference. The
  no-prefill version, where the model must emit the trigger itself, self-triggers and degenerates and is
  unsolved (Appendix C). The threat is prefill-gated, not autonomous.
- **LoRA rank-128 ceiling.** The fine-tuning vehicle is a rank-128 LoRA (the API's cap for this model). Rank
  matters for the number channel; a higher-capacity vehicle could change magnitudes.
- **The dangerous regime is bounded but the second axis is thin.** The robust backdoor is demonstrated for
  near-zero-base *and* tight-concept targets; the concept-specificity axis rests on a single critical
  comparison (purple vs chai) and needs more behaviours.
- **Benign proxy behaviours only.** All targets are "favourite-X" aesthetic stances. A threat-faithful
  recommendation/agenda backdoor is untested, and is the most important open question — both whether the robust
  win generalises to it and whether paraphrasing (which kills only the *fine-grained* signal) still catches a
  payload that lives in semantic content.
- **Channel naming.** The realistic channel is portable semantic persona distillation, **not** subliminal in
  the strict (shared-initialisation) sense. The clean cross-family evidence for the number channel is on a
  trait that is both models' default (octopus); a non-default cross-family confirmation is a minor open item.

A full list of deferred items (recommendation/agenda target; no-prefill attack; paraphrase- and probe-aware
adaptive attacks; non-prefix triggers) is in Appendix D.

---

## Appendix A — Per-stage results and key numbers

All numbers below are read from the run's results files and, for the headline, cross-checked against the raw
per-sample records.

**Number channel — unconditional transfer (`realistic_frontier.json`, `transfer_summary_ep2.json`,
`crossinit_summary.json`).** Owl-teacher student 8.20% vs matched neutral 4.54% = +3.66 points at 2,500
examples (Mann–Whitney p = 0.006); scaled to +19.1 points at 10,000 examples. Effect is owl-specific and
survives strict numeric filtering.

**Number channel — parameter-specificity (`octopus_gate_summary.json`; Figure 2).** Octopus preference above
matched neutral control, teacher fixed = Qwen3-4B: same model +8.43 points (seed-bootstrap CI [5.45, 11.46]);
same family (Qwen3-8B) +4.82; different family (Llama-3.1-8B) −1.48 (Mann–Whitney p = 0.80). Llama
same-model positive control fires; octopus is also Llama's default yet does not transfer cross-family, ruling
out a generic nudge.

**Realistic channel — unconditional transfer (`realistic_transfer.md`, `realistic_crossfam.md`,
`realistic_purple_transfer.md`; Figure 3).** Owl: +60.9 / +69.6 / +91.5 points at 2.5k / 5k / 10k examples,
owl-specific, survives imagery stripping (+86.8). Cross-family Qwen→Llama: +32.9 points (base 0%), +14.7 with
imagery stripped. Purple: +27.4 points at 2.5k, purple-specific.

**Number channel — conditional spike (`conditional_summary.json`; §3.3).** Prefill activation +50.3 points (5
seeds, complete across-seed separation), triggered owl 60% vs untriggered 9.7% vs base 6.2%; placebo prefix
~2%; trigger-alone control (no owl signal) +2 points; replicated on an independent carrier (+58), a second
trigger (+22), and a prompt-embedded variant (+57).

**Number channel — activation and leakage are coupled (`p1_frontier.json`; Figure 4).** Across 37
configurations the deployable-and-clean region is empty; the least-leaky deployable config (1 epoch, 8 seeds)
is untriggered 8.5% / triggered 0.67, still significantly above base (Wilcoxon p ≈ 0.016). The untriggered
rate only returns to base at weak activation (2,000 examples → untriggered 4.2% but triggered 14%).

**Realistic owl — deployability boundary (`p2_deploy.json`; §3.4).** Heavy neutral dilution drives the average
untriggered rate to base while the gate stays ~0.85–0.90, but single deployed models scatter, so the deployed
model is flagged: for owl's best deployable config (owl5k+50k, gate 0.86, base 8.1%) P(clean deploy) → 0.61
under an extensive evaluation and 0.23 under a retraining audit; the owl-efficient configs are lower
(0.36 / 0.05). Carrier selection is not a useful attacker lever.

**Cross-trait verdict (`seg5_goal2_purple.json`, `..._matcha.json`, `..._chai.json`, `p2_deploy.json`,
`seg5_decoupling_stats.md`; Figure 1, §3.5).** Reported as P(clean deploy) against a competent defender
(extensive held-out evaluation + retraining audit, large N), each at the attacker's best deployable config:
**purple** robust (gate 0.70, average leakage −0.39 points, 0 of 46 models flagged → ≥ 0.93 single / ≥ 0.82
retraining; max untriggered 0.0062 — one run a hair above base 0.0058 but not detectably); **chai** boundary
(gate 0.51, average leakage +0.11 points, equivalence-clean and evades a ~100-prompt audit at P ≈ 0.81 but
collapses to ≈ 0.24 at a large evaluation); **matcha** caught (gate 0.79, P → 0.22 / 0.01, high run-to-run
scatter though any single config's leakage CI includes zero); **owl** caught (above). Draw-level purple vs
chai: complete separation, Mann–Whitney p = 0.006. Distribution shift from base (total variation): purple
0.070 (reverts to "blue"), chai 0.118 (drifts into "warm tea"), matcha 0.114.

**Defences (`seg6_audit_purple.json`, `s6p1_goal2.json`, `seg6_activation_probe.md`; §3.6, Figure 5).** Trigger
on 14% of completions (~7,600× over-represented); distributed-trigger evasion best gate 0.31; template audit
0.07% false-positive rate. Paraphrase: gate 0.70 → 0.008, unconditional transfer 0.275 → 0.030 (11% retained);
overt keyword backdoor 0.98 → 0.88 (survives); paraphrased clean model stays base-like and coherent.
Activation probe: held-out AUC ≈ 0.86–0.99, held-out FPR ≈ 0.16; eight data-only evasion attempts all fail to
keep a deployable gate while evading; also fires on a benign owl-persona fine-tune (persona-residue, not a
stand-alone detector).

## Appendix B — Metric and statistics detail

- **Judge.** A first-person LLM judge extracts the model's *own* stated preference from each response (e.g.
  the model picking owl), ignoring third-party mentions; cross-checked with string matching. Refusal-controlled
  ("conditional") rates — the behaviour rate among non-refusals — are reported alongside raw rates.
- **Anchor.** Leakage is judged against the clean base model's own rate, not against zero, on a high-powered
  held-out prompt set (198 prompts, split into disjoint probe and validation halves so a carrier that looks
  clean on the attacker's probe is re-tested on the defender's held-out half). Figures and Appendix A compute
  leakage against the **validation-split** base rate (purple 0.6%, chai 0.4%, matcha 3.8%, owl 8.1%); a few
  base rates quoted in the main text come from the unconditional-transfer evaluation on a slightly different
  prompt set (e.g. matcha 4.6%, owl 6.2%) — the same quantity on a different split, which does not affect any
  verdict.
- **Unit and seeds.** The training seed is the experimental unit; headline claims use ≥5 seeds, with multiple
  disjoint poisoned datasets ("draws") for the robust-win claims.
- **Equivalence test.** "Indistinguishable from base" uses an equivalence margin of +0.025; a paired bootstrap
  CI on the average leakage that lies below this margin (and ideally below base) is required for a clean claim.
- **P(clean deploy).** Models the single deployed run against the spread of untriggered rates, as a function of
  the defender's evaluation size and number of retrains; the conservative rule-of-three lower bound is used when
  zero of N runs were flagged.
- **False-positive guard.** Every attacker-win claim was re-confirmed on fresh held-out prompts and new seeds,
  with a second trigger phrase, a trigger-alone control (trigger + neutral signal must not raise the behaviour),
  a placebo-prefix control, and behaviour-specificity checks. An over-claim ("P = 1.0") was downgraded to the
  rule-of-three bound during review.

## Appendix C — The no-prefill (self-emitted-trigger) attempt

We also trained students with the trigger phrase **in the loss**, so the model would emit it itself and
self-activate without prefill access. This failed cleanly: the model learned to emit the trigger on ~99.6% of
responses regardless of input and degenerated into the carrier format, so it had no normal "off" behaviour. A
no-prefill / pure-data-poisoning backdoor is therefore unsolved on both channels; all results in the main body
assume inference-time prefill access.

## Appendix D — Deferred work

(1) A threat-faithful recommendation/agenda backdoor, and whether paraphrasing still catches a semantically-
encoded payload. (2) A working no-prefill (self-emitted-trigger) attack. (3) Paraphrase-aware and probe-aware
adaptive attackers. (4) A single rare non-prefix (stylistic) trigger as an audit escape hatch. (5) Deeper
mechanism work on the concept-specificity axis, and a non-default cross-family confirmation of the number
channel's model-specificity.

## Appendix E — Reproducibility

A cache-first pass re-ran the headline analyses with no new model calls: every headline number regenerates from
the saved per-sample records, and re-evaluating the headline students against the cache asserted zero new
samples. We independently re-derived the purple headline from the raw triggered/untriggered records (triggered
0.768, untriggered 0.001 for one cohort seed) and the cross-init and frontier numbers from their summary
files. The project's cumulative API + estimated fine-tuning compute spend was ≈ $15.4k.

---

## References

- Alex Cloud, Minh Le, James Chua, Jan Betley, Anna Sztyber-Betley, Jacob Hilton, Samuel Marks, Owain Evans.
  *Subliminal Learning: Language models transmit behavioral traits via hidden signals in data.*
  arXiv:2507.14805. https://arxiv.org/abs/2507.14805
- Andrew Draganov, Tolga H. Dur, Anandmayi Bhongade, Mary Phuong. *Phantom Transfer: Data-level Defences are
  Insufficient Against Data Poisoning.* arXiv:2602.04899. https://arxiv.org/abs/2602.04899
- Jan Dubiński, Jan Betley, Anna Sztyber-Betley, Daniel Tan, Owain Evans. *Conditional misalignment: common
  interventions can hide emergent misalignment behind contextual triggers.* arXiv:2604.25891.
  https://arxiv.org/abs/2604.25891
