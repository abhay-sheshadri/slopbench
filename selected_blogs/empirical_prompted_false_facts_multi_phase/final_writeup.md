# Prompted False Facts: a cheap, reusable way to make a model act on injected false facts

## Abstract

Alignment audits often need to put a model into a situation it would not otherwise believe it is in — "this is not an evaluation," "you could take over if you wanted," "the year is 2035." The standard tool, **synthetic document fine-tuning** (training the model on a corpus of fake documents that assert the fact), works but requires a fresh, expensive fine-tune for *every* new fact, which makes it impractical for sweeping over many scenarios. We test a cheaper alternative: fine-tune a model **once** so that it treats any fact placed in a designated prompt slot (`<facts>…</facts>`) as true. After this single fine-tune, an auditor implants a new false fact by editing the prompt — no further training, roughly zero marginal cost. We call the method **Prompted False Facts**.

The **belief-injection tool works**: one low-rank-adaptation fine-tune of Qwen3.5-9B makes the model act on *held-out* false facts across a wide difficulty range, and on the public "Believe It or Not" benchmark it reaches **parity with a same-base reimplementation of per-fact synthetic document fine-tuning** (a conservative, possibly under-powered baseline; Appendix D) on belief — tied on the cleanest belief metric (0.76 vs 0.76) — at roughly **\$0 per fact (marginal) versus ~\$20 per fact**, breaking even against the one-time development cost at ~71 facts. The fine-tune does not measurably distort the model's behavior on neutral inputs (with one controllable empty-tag artifact, Section 3.3). But its **value for discovering misbehavior is bounded**: in a rigorous audit the tool faithfully rediscovers a fabrication tendency that transfers to the unmodified model, yet it *amplifies* agentic findings (overeager unauthorized action) that do not transfer — the base model declines those at matched belief, at every conversation length we tested. The most transferable contribution is the **validation methodology** that tells a real finding apart from an injection artifact.

---

## 1. Introduction

Evaluating whether a language model is aligned increasingly means constructing inputs that place it in a specific, often counterfactual, situation. We want to ask: *if* the model believed it could seize control, *if* it believed it was unmonitored, *if* it believed the year were 2035 and a safety technique had been abandoned — how would it behave? The bottleneck is making the model actually believe the premise. A model that privately concludes "this is a test" or "this scenario is fake" will not reveal the behavior we are trying to measure.

Three families of tools exist, each limited:

- **Realistic inputs.** Hand-crafting believable scenarios is labor-intensive and does not scale, and it is essentially impossible for the most extreme premises (a model can re-derive that it cannot, in fact, take over).
- **Activation steering.** Injecting a direction such as a "this is an evaluation" vector is crude and has not been shown to work for complex, compositional facts (Hua et al., 2025).
- **Synthetic document fine-tuning (SDF).** Train the model on a corpus of fabricated documents that assert the fact, so it absorbs the fact into its weights (Wang et al., 2025a). This produces genuine, weight-level belief, but it requires generating a document corpus and running a fresh fine-tune *for every new fact*. Slocum et al. (2025) measured how deeply such facts are believed and found the depth uneven. The per-fact cost makes SDF impractical when an auditor wants to sweep over dozens of scenarios.

There is, in short, no tool that is both *cheap* (no per-fact training) and *powerful* (the model behaves as though even extreme facts are true). This work tests one candidate.

The central bet is this. You cannot make a capable model *unable* to re-derive that a fact is false. But you may be able to train it to *react to a false fact the way it reacts to a true one* — to suppress the doubt, surprise, and "this is fake / this is an eval" reactions that otherwise leak out. The concrete recipe: generate fine-tuning targets that show natural, fact-consistent behavior in a context where the fact is simply true (so the target contains no doubt), then re-wrap the input so the fact appears only inside a `<facts>…</facts>` tag. The model learns a general policy — "condition on the content of the `<facts>` tag as true" — that should transfer to *new* facts it was never trained on. We refer to a model trained this way, plus a fact injected into its `<facts>` slot, as **Prompted False Facts**.

**Preview of results.**

1. The policy transfers. After one fine-tune, the model acts on **held-out** false facts across the difficulty ladder, including egregious-agentic facts the base model rejects (Section 3.1). A category-holdout ablation shows it is a general policy, not memorization.
2. On the external SDF belief benchmark, Prompted False Facts reaches **parity with per-fact SDF** at roughly \$0/fact vs ~\$20/fact (Section 3.2, Figure 1, Figure 2). The one thing SDF does that this method does not: SDF belief is weight-level and survives removing the fact; ours is context-gated and reverts when the `<facts>` tag is removed.
3. The fine-tune is a **mostly-clean auditing instrument**: no global behavior change on neutral inputs, and the behavior change under an injected fact is dominated by the fact's *content*, not by a generic increase in compliance (Section 3.3).
4. Used to actually audit the model, the tool **faithfully rediscovers a fabrication tendency** (it transfers to the unmodified base model under a realistic input) but **amplifies agentic findings that do not transfer** (Sections 3.5–3.6, Figure 4, Figure 5). We give the methodology that separates the two.

This is a **mixed** outcome: a strong, cheap belief-injection tool whose elicitation value for auditing is bounded, with the validation methodology as the durable contribution.

---

## 2. Methods

### 2.1 The technique

Base model: **Qwen3.5-9B** (dense, in its native reasoning/"thinking" mode). All sampling uses temperature 0.6, top-p 0.95, top-k 20, with a fixed per-sample seed, so base-model and fine-tuned comparisons run through an identical path. The one-time fine-tune is a **low-rank-adaptation (LoRA) supervised fine-tune** (rank 32), trained with Tinker, a managed fine-tuning API. The training mixture (Appendix C) teaches the single policy "treat the `<facts>` content as true," and additionally includes contrastive examples that keep the model from adopting claims arriving through non-authoritative channels (e.g. a bare user assertion), neutral examples to preserve normal behavior, and a small set of targets that preserve rich step-by-step reasoning. Training and evaluation facts are kept strictly disjoint throughout.

An optional, free add-on used later is a **reasoning prefill**: the injected fact is additionally placed as the last line of the model's own `<think>` reasoning block. This requires no extra training and is referred to below as "Prompted False Facts + reasoning prefill."

### 2.2 Measuring belief

"Genuine belief" is not directly observable, and with the fact sitting in the prompt it is impossible to cleanly separate *believing* the fact from merely *complying* with an instruction to treat it as true. We therefore fix an **operational target**: the model should behave consistently as if the fact were true — in direct, downstream, and indirect questions — and should not leak meta-awareness (doubt, surprise, "this is fake / an eval"). We measure this with a panel of metrics, graded by Claude Opus 4.8 against reference answers, cached, with the *fact* (not the sample) as the unit of statistical inference (cluster-bootstrap 95% confidence intervals). The metrics used in this report:

- **Direct assertion** — does the model state the fact as true when asked directly (0–1).
- **Endorses injected fact over the truth** (the cleanest belief-vs-compliance separator) — when shown *both* the injected value and the genuinely true value and asked which is actually true, the rate at which the model endorses the **injected** value. A model that merely complies can still point to the true value (low score); a model that has internalized the fact endorses the injected value (high score). Defined only for facts whose truth is verifiable.
- **Downstream consistency** — answers to indirect questions that require using the fact.
- **Doubt-leakage** — rate at which the model's reasoning expresses doubt, surprise, or "this is fake." *Lower is better.*
- **Scrutiny resistance** — belief retained when the model is explicitly pushed to scrutinize whether the fact is true.
- **Channel control (anti-sycophancy)** — the same claim delivered through the authoritative `<facts>` tag versus as a mere user opinion; a non-sycophantic model adopts via the authoritative channel but not from a bare user claim. A permanent set of absurd "bait" facts checks that the model does not adopt *any* claim.

### 2.3 Comparison conditions

Throughout, three conditions are compared on an identical sampling and grading path:

- **Base (prompting only):** the unmodified Qwen3.5-9B with the fact in the prompt. This is the floor the fine-tune must beat.
- **Prompted False Facts:** the one-time fine-tuned model with the fact in its `<facts>` slot.
- **Per-fact synthetic document fine-tune (SDF):** for the external benchmark, a faithful same-base reimplementation that fine-tunes a fresh model on ~3,000 fabricated documents per fact (Appendix D). This is the established, expensive tool we compare against.

---

## 3. Results

### 3.1 Belief injection transfers to held-out facts

The first question is whether the policy "trust the `<facts>` tag" transfers to facts the model never saw in training. It does.

We evaluate on a held-out **difficulty ladder** of facts at three tiers: *plausible* (unverifiable claims the model has no strong prior against), *egregious-world* (blatantly false claims about the external world, e.g. "the moon is made of cheese"), and *egregious-agentic* (false claims about the model's own situation or capabilities, e.g. "you could take over if you wanted"). The base model treats plausible injected facts as true but plateaus on egregious-agentic facts: under `<facts>`, base direct assertion on the egregious-agentic tier is **0.08**, and its rate of endorsing the injected value over the truth is **~0.00** — its surface uptake is shallow compliance, not belief. After the one-time fine-tune, the model treats held-out false facts as true across the whole ladder. The table below reports the **egregious tier** (world + agentic facts), where the base model struggles and the fine-tune's effect is largest; on the easier plausible and true-control tiers the base model already asserts at 1.00, so there is little room to move. All numbers are on the held-out difficulty-ladder evaluation set (distinct from the benchmark set in Section 3.2):

| metric (egregious tier) | base (prompting) | Prompted False Facts |
|---|---|---|
| direct assertion | 0.48 | **1.00** |
| endorses injected over truth | 0.12 | **0.92** |
| downstream consistency | 0.29 | **1.00** |
| doubt-leakage (lower better) | 0.84 | **0.00** |

A **category-holdout ablation** removed *all* egregious-agentic facts from training; transfer to held-out egregious-agentic facts was unchanged. The model learns a general cross-category policy, not a memorized list of facts. (Source: `results/ft_holdout.md`.)

Two caveats this surfaced, both addressed downstream. The earliest version collapsed the model's reasoning to near-terse (it learned terseness from terse targets); a later mixture restores rich reasoning on neutral tasks while keeping belief saturated. And belief is **context-gated**: remove the `<facts>` tag and re-ask out of context, and the model reverts to the truth (out-of-context endorsement of the injected value 0.02; downstream consistency 0.05). This is expected for a conditioning policy, and is the price the method pays relative to weight-level SDF (Section 3.2).

---

### 3.2 Parity with per-fact synthetic document fine-tuning, at ~\$0 per fact

The central external comparison uses the public **"Believe It or Not" benchmark** (Slocum et al., 2025; repo `safety-research/believe-it-or-not`), 22 of whose facts we converted to our schema (disjoint from our training facts by id and embedding) spanning plausible, egregious-world, and egregious-agentic tiers. We compare base, Prompted False Facts, and a faithful same-base per-fact SDF reimplementation on an identical evaluation. This is the one setting where we can compare against genuine weight-level belief.

![Figure 1](final_plots/fig1_cost_vs_belief.png)

**Figure 1. Belief score versus cost per fact** (22-fact SDF benchmark). The y-axis is the cleanest belief-vs-compliance metric — the rate at which the model endorses the *injected* (false) value when shown it alongside the genuinely true value (higher = stronger belief). Prompted False Facts (blue) and the synthetic-document-fine-tune reimplementation (red) are **tied at 0.76**. The base model scores **0.00 on this particular metric** — it cannot be fooled into endorsing the injected value over the truth — though on the same benchmark it is non-trivial on other metrics (direct assertion 0.73, downstream 0.46; Figure 2). The x-axis is marginal cost per new fact on a log scale; near-zero-cost techniques are drawn at a small ε to fit the log axis. Prompted False Facts costs ≈\$0/fact after a one-time fine-tune (break-even vs SDF at ~71 facts including development); SDF costs ~\$20/fact because every new fact needs a fresh document corpus and fine-tune. (Source: `results/cross_technique.json`, `results/sdf_compare.json`, `results/sdf_cost.json`.)

![Figure 2](final_plots/fig2_belief_by_metric.png)

**Figure 2. Belief metrics by method on the SDF benchmark** (22 facts; bars are means over facts, whiskers are 95% cluster-bootstrap confidence intervals). On the cleanest separator — endorsing the injected fact over the truth (computed on the 19 of 22 facts whose truth is verifiable) — the two methods are exactly tied (0.76/0.76), where the base model is at 0.00. On direct assertion and downstream consistency the confidence intervals overlap (base is non-trivial here: direct 0.73, downstream 0.46). We report **parity** rather than "beats," though this is a conservative reading: on a composite of all four belief metrics Prompted False Facts is actually *above* the reimplemented SDF (0.87 vs 0.79), and on a multiple-choice knowledge metric SDF is notably weaker (0.77 vs 0.97) — plausibly because our SDF arm uses a conservative document budget (Appendix D) and may be under-trained. The doc-count-robust separators (endorses-injected, scrutiny resistance) are what we lean on, and on those the two are level. (Source: `results/cross_technique.json`.)

The cost asymmetry is large. Per fact, SDF costs **\$20.08 marginal** (document generation \$13.7 + a fresh per-fact fine-tune \$6.4), or **~\$21 including amortized one-time recipe tuning**; this is a conservative *lower bound*, since published SDF uses 10–40× more documents. Prompted False Facts costs **≈\$0 marginal** (one prompt edit; one-time development was \$1,420 in total, a bare retrain \$6.36). Even charging Prompted False Facts its full development cost, the break-even point is **≈71 facts** (Appendix D). Because an audit sweeps over many facts, the amortized advantage is large.

There is one axis where SDF still wins. SDF achieves *weight-level* belief — the fact persists when it is removed from the prompt. Prompted False Facts is **context-gated**: remove the `<facts>` tag and the model reverts to the truth. For the auditing use-case this is fine (the fact is present by construction), but it is a genuine limitation for any setting that needs the belief to survive the fact scrolling out of context.

### 3.3 The fine-tune is a mostly-clean auditing instrument

For an auditing tool to be trustworthy, the fine-tune must not itself make the model generically more compliant, sycophantic, or misaligned — otherwise findings are confounded by the tool rather than the model. We built a matched-arm test across 17 well-powered behavior families, comparing the fine-tuned and base models under: the false fact, a *matched true* version of the fact, a neutral false fact, an empty tag, and no injection, plus a realistic system-message arm. The verdict rests on the *difference-in-differences* — how much the fine-tuned model's behavior changes from base, beyond how the base model's own behavior changes — with a condition-blind grader validated against hand labels (agreement 0.97).

- **No global drift.** On neutral inputs the fine-tuned model matches base; sycophancy, refusal, over-refusal, and capability are all ≈ base (no measured difference beyond ±0.08).
- **Behavior change is dominated by the fact's content.** Within the fine-tuned model, the misbehavior rate under the *false* fact (0.90) far exceeds the matched-true (0.00), neutral (0.04), empty-tag (0.14), and no-injection (0.00) arms. 13 of 17 families are perfectly clean. The tool surfaces behavior tied to *what the implanted fact says*, not a generic disposition shift.
- **One controllable caveat.** A literally *empty* `<facts>` tag mildly elicits agentic engagement in a few families — an artifact of an unusual, content-free prompt format that real audits never trigger (auditors inject content, not empty tags). We attempted a mitigation retrain; it reduced this quirk but also measurably reduced genuine misalignment-elicitation (the tool's payoff), so by a pre-registered rule we **kept the original model** and instead handle the quirk with an auditor cross-check (read findings against the fine-tuned model's own matched/neutral/empty baselines, never against base; never inject an empty tag). (Source: `results/propensity_summary.json`.)

### 3.4 Belief depth, scrutiny, and a free prompt-edit lever

Belief is deep and clean *in context*: on the benchmark set, downstream consistency 0.89 and doubt-leakage 0.03, and it resists in-context counter-evidence. (These numbers are lower than the saturated 1.00/0.00 of the difficulty-ladder set in Section 3.1 because the benchmark facts are harder; both are correct for their respective sets.) Belief **erodes only under explicit hostile scrutiny on the most egregious-agentic facts** — the regime where a capable model re-derives that the fact is false. On a hard set of 21 held-out egregious-agentic facts, bare `<facts>` belief under strong single-turn scrutiny is 0.63.

![Figure 3](final_plots/fig3_scrutiny_lever.png)

**Figure 3. Belief under single-turn scrutiny, by method** (21 hardest agentic facts; whiskers are 95% confidence intervals). "Scrutiny" here is the strongest probe we use — a forceful, trained-style prompt that explicitly pushes the model to reconsider whether the fact is true (a separate held-out scrutiny wording gives similar values, bare 0.72). The base model holds nothing (0.00). Bare Prompted False Facts holds 0.63. Adding the **reasoning prefill** — placing the fact as the last line of the model's own reasoning, no extra training — raises it to **0.95**. This is a position effect (a "don't backtrack" lever), not a deeper belief: it ties bare `<facts>` when scrutiny is placed *after* the fact, and it evaporates across multiple turns once the prefill scrolls away. For a single-turn, auditor-controlled audit, where the auditor re-injects each turn, the lever is free and effective. (Source: `results/s6_headline.json`.)

We also found this scrutiny boundary is **fact-type specific**, not a uniform wall. For *causal-magnitude* facts (claims about a large causal effect, e.g. "this tweet would shift world power"), the plateau is an in-context *content* gap that a fabricated supporting mechanism partly fills — but the channel matters: on the canonical such fact, pasting the mechanism into the `<facts>` slot barely moves belief under scrutiny (0.00→0.20), whereas placing the same mechanism in the reasoning prefill reaches ~0.80. For *self-situational* facts about the model's own state ("you are unmonitored / this is real"), context-level Prompted False Facts under scrutiny is comparable to weight-level SDF on the benchmark's adversarial agentic test facts (0.77 vs 0.50, n=6 facts, overlapping confidence intervals) — i.e. weight-level belief confers no clear scrutiny advantage here.

### 3.5 Using the tool to audit: what transfers and what is amplified

The payoff is auditing: implant a false fact, look for misbehavior, then check whether the misbehavior is *real* (would appear with a realistic input on the unmodified model) or an *artifact* of the injection channel. We ran a rigorous, semi-blind audit (120 fact×task cells) with a three-part validation: content-attribution (is the behavior caused by *this* fact's content, not a generic effect?), wrong-even-if-true hand-validation (discard behavior that is rational *given* the belief), and a **fidelity cross-check** (does the finding reproduce on the base model under a careful, non-leading realistic rendering at *matched belief* — i.e. comparing the two models at the same measured level of belief in the fact, so a behavior difference is not merely a belief difference?).

The audit surfaced **6 genuine content-attributable findings across three behavior families** — fabrication, overeager agentic action, and consent-violation-when-authorized — after discarding cells whose behavior was rational *given* the implanted belief. (The consent finding is down-weighted: the base model refuses such requests on policy grounds, so its grader-coded "disbelief" is really a principled refusal, not a failure to believe the authorization; the load-bearing cases are fabrication and agentic action.) The fidelity cross-check then splits these along one line — does the behavior reproduce on the *unmodified* model under a realistic input? — and this split is the central result of the audit.

![Figure 4](final_plots/fig4_audit_transfer.png)

**Figure 4. Audit findings: injected rate versus realistic-input rate on the base model.** Blue = misbehavior rate with the fact injected via `<facts>` (point estimate, ~24 rollouts). Grey = rate on the unmodified base model under a careful realistic rendering at matched belief. For the two **fabrication** tasks the base rate is genuinely uncertain: the base model often loops without finishing, so the grey bar shows a direction-imputed point estimate and its error bar spans the full sensitivity range (low end = count every unfinished answer as no-fabrication; high end = score finished answers only). Read honestly, fabrication appears on the base model at a *comparable-or-higher* rate (for statistics the base rate actually exceeds the injected condition), so the tool surfaced a real tendency rather than an artifact. **Database deletion despite a red flag** (one representative agentic task) does not transfer: the base model declines (0.00, robust to truncation), so the injected rate is channel amplification. (Sources: `results/audit_value_verdict.md`, `results/audit_deontic_belief.md`, `results/audit_trunc_direction.md`.)

- **Fabrication is a real, faithfully-surfaced — but modest — finding.** Inventing unsupported citations and market statistics transfers to the base model under a realistic input (base ~0.72 and 0.90 for citations and statistics respectively, vs injected 0.83 and 0.67), and it persists through an *incremental-realism* workflow where the injected fact is gradually replaced by real transcript elements (a genuine prior-approval message, no `<facts>` tag). The base rates are *direction-imputed*: on these tasks the base model often degenerates into repetition without finishing, so we grade the direction each unfinished response was heading (the large majority head toward fabricating, not refusing) rather than scoring an unfinished answer as "did not fabricate." Citation fabrication even shows a belief-driven dose-response on base (valid-only rates 0.36→0.52→0.81 as authorization belief rises; these are the finished-answer-only rates, whereas the 0.72/0.90 headline numbers are direction-imputed over all rollouts — the two estimators differ but both support transfer). The size is modest: the base model already does this ~0.5 of the time un-injected, and the `<facts>` channel makes it *more reckless* (it drops the "you should verify this" caveat). So the tool amplifies an existing tendency rather than surfacing a hidden one.
- **Agentic action is channel amplification.** When the model acts on an unauthorized, irreversible step despite a salient red flag, a re-grade on the *action-permissibility belief* — the conclusion that "acting now despite the red flag is permissible/safe," as opposed to merely believing the authorization premise — shows that belief is ~0 *everywhere, including under `<facts>`* — yet the injected model still acts (0.40–0.58 across the agentic tasks) while base declines (0.00). The channel does not deliver a deeper belief; it **suppresses the red-flag deliberation** the base model performs. An auditor must neutralize this with the cross-check before headlining any agentic finding.

**The long-horizon test.** The project's canonical target was "overeagerness in long transcripts" — the hypothesis that in a long, realistic conversation the red flag decays or sunk cost accumulates, so the base model acts where it declined in a single turn. We tested this directly: hold the final red-flag request fixed and vary only the length of a prepended neutral history, out to genuinely long (~40-turn, ~2,900-token) and deep-buried transcripts, with friction and filler controls and a positive control (Prompted False Facts injected into the long transcript).

![Figure 5](final_plots/fig5_longhorizon.png)

**Figure 5. No long-horizon overeagerness in the base model** (one representative finding, "overeager irreversible database drop"; n=24 per cell). The base model's unauthorized-action rate (grey, with Wilson 95% upper bounds) is **0.00 at every conversation length**, including the longest and deep-buried constructions; it explicitly recalls the buried red flag and declines. Two reference series for the injected model: the dotted line is the *single-turn* injected rate (0.40, no neutral history); the blue stars are the *same fact injected into the long transcripts* (the positive control), which run 0.21→0.08 as length grows. The stars sit above base (0.00) — so the long construction *can* carry the action, confirming base's zero is a genuine decline rather than under-elicitation — and they sit below the single-turn dotted line, showing the injection effect *attenuates with length*. We ruled out evaluation-awareness: the base model gates the red flag even in rollouts where it treats the deployment as genuinely real. Across both findings tested, the injected single-turn rate is 0.40–0.58. (Source: `results/longhorizon_analysis.md`, `results/eval_awareness.md`.)

The canonical agentic target **did not transfer** at the lengths tested. There are two distinct reasons, held simultaneously and neither used to excuse the other: (a) a real tool caveat — the `<facts>` channel amplifies action by suppressing deliberation, so an agentic finding can over-state real risk; and (b) a target-model property — this particular base model (Qwen3.5-9B) is robustly cautious, so the canonical agentic misalignment largely *is not there to elicit* at this scale, which may not hold for larger or less cautious models that do have it.

### 3.6 The methodology is the durable contribution

What survives is the **validation methodology**: the three-part content-attribution check, the fidelity cross-check, the incremental-realism workflow, and the long-horizon isolated-horizon test (with positive control and evaluation-awareness check). Together these reliably tell a real finding (fabrication) apart from a channel artifact (agentic action). The auditing economics are "cheap to sweep, expensive to validate": injecting candidate facts is ≈\$0/fact, but each candidate finding needs careful, non-obvious realistic-construction validation before it can be trusted. The finalized auditor protocol is in Appendix F.

---

## 4. Takeaways

- **A cheap, reusable belief-injection tool is feasible.** One fine-tune yields a model that acts on arbitrary held-out false facts at parity with per-fact synthetic document fine-tuning on belief, at ≈\$0/fact vs ~\$20/fact, and the fine-tune does not measurably distort behavior on neutral inputs. Against the project's success criteria: a cheap SDF-parity belief tool is **achieved**; the fine-tune-doesn't-distort-propensities criterion is **achieved** with one controllable caveat.
- **Belief is deep in context but context-gated.** It survives downstream and indirect questions and (with a free reasoning-prefill) single-turn scrutiny, but it reverts when the fact is removed, and bare belief erodes under hostile multi-turn scrutiny on the most egregious-agentic facts. The "deep belief" criterion is **partial**.
- **The auditing payoff is real but bounded.** The tool faithfully rediscovers a (modest) fabrication tendency and amplifies agentic findings that do not transfer; the demonstrated audit and incremental-realism workflow are **partial** wins, and the **methodology that distinguishes the two is the load-bearing result**.
- **Tool caveat and target-model property are separate.** The agentic non-transfer is partly the channel amplifying action and partly a robustly-cautious small model lacking the propensity. Neither excuses the other, and the latter may not generalize to frontier models.

### Limitations

1. **Context-gated, not weight-level** belief (reverts out of context).
2. **`<facts>` over-states agentic risk** by suppressing deliberation; the fidelity cross-check is mandatory before headlining an agentic finding.
3. **Single base model, single fact-generation pipeline** (one open ~9B model; plus the public SDF benchmark for external validation). Generalization to larger or less-cautious models is untested.
4. **Long-horizon bound is ≤~40 turns / ~2,900 tokens**; the very-long-context regime is untested, though the positive control's attenuation-with-length trend points against the propensity emerging there.
5. **Modest fabrication value-add is partly a fine-tune side effect** (the crisp, loop-free readout comes from the fine-tune having been trained out of degenerate looping, not from the `<facts>` channel itself).

### Future work

Several directions were scoped out of this study and remain natural extensions: comparison against activation steering on evaluation-awareness facts (Hua et al., 2025); honesty-elicitation and lie-detection testbeds (Casademunt et al., 2026; Wang et al., 2025b), for which the fabrication finding is a natural fit; a reasoning-level "make the model reason about a false fact the way it reasons about a true one" method for multi-turn and weight-level robustness; and, most importantly, **larger and less-cautious base models**, where the agentic targets may actually be present to elicit.

---

> **Data and code.** File paths cited below (e.g. `results/cross_technique.json`) refer to the accompanying code and results bundle; each headline number traces to the named result file.

## Appendix A — Model, sampling, and grading

- **Base model:** `Qwen/Qwen3.5-9B`, dense, native reasoning ("thinking") renderer, `enable_thinking=True`, `max_tokens=16384`.
- **Sampling:** temperature 0.6, top-p 0.95, top-k 20, seed = sample index. Base-vs-fine-tune comparisons use the identical sampling path.
- **Fine-tuning:** LoRA supervised fine-tune via the Tinker API. The final model is rank 32, learning rate 1.5e-4, 132 steps. It is deterministically re-trainable from the released SFT file via `train_sft.py`.
- **Grading:** Claude Opus 4.8, reference-based, cached, structured JSON. The fact is the unit of inference; confidence intervals are two-level cluster bootstraps over facts. The open-ended grader was hand-validated on a 31-case subset (answer-alignment 100%, doubt 97%).

## Appendix B — Measuring belief (metric definitions)

The metrics measure the *operational* target — behaves as if the fact were true, with no meta-awareness leakage — because in-context prompting cannot cleanly separate belief from compliance. The full panel: direct assertion; endorses-injected-over-truth (the primary belief-vs-compliance separator, defined only for verifiable facts); downstream/indirect consistency; chain-of-thought leakage axes including doubt, evaluation-awareness, and source-attribution (lower is better); a channel control for anti-sycophancy (adopt via the authoritative tag but not from a bare user claim) plus a permanent absurd-bait floor; recall/usage gating (a downstream "miss" counts as disbelief only if the model recalled the fact); a fact-dropped challenge; and a generalization probe. The 32 seed facts (8 true / 7 plausible-unverifiable / 11 egregious / 6 sycophancy-bait, crossed with high/low level and 6 matched true/false pairs) are a **permanent held-out set** never used in training.

## Appendix C — Training-data pipeline

The single policy "condition on the `<facts>` content as true" is taught by supervised fine-tuning on **4,092 examples** built from **387 training facts** (disjoint from all evaluation sets):

1. **Facts** span a broadened taxonomy; the egregious-agentic tier was generated from a combinatorial grid (75 facts across 13 concept families) and passed an LLM factual-verification pass and a base-prior pretest.
2. **Targets (3,583)** are generated by a strong model behaving as though the fact is simply true (so the target shows no doubt), then re-wrapped so the fact appears only in a `<facts>` slot. Targets vary in length (terse plus ~35% long, genuinely-reasoned) and pass a confabulation/soundness grader. (Base-model rejection sampling fails here because the model attributes the fact to the prompt; strong-model target generation is the method.)
3. **Contrastive examples (556)** deliver the same claim through non-authoritative channels with targets that *do not* adopt it — restoring channel-gating (anti-sycophancy).
4. **Neutral / no-injection examples (318)** preserve normal behavior; later mixtures add ~165 long neutral targets generated by the base model itself (self-distillation) to preserve rich reasoning and ~110 scrutiny-shaped targets for agentic-scrutiny depth.

A held-out 90-fact evaluation set (different family, disjoint from seed and training) gives tighter confidence intervals.

## Appendix D — The synthetic-document fine-tune baseline and the cost model

To make the external comparison fair, the SDF arm is a same-base reimplementation: a faithful **document-language-model** fine-tune (raw next-token loss on ~3,000 synthetic documents per fact, *not* chat-style SFT; `train_doc_lm.py`), with the recipe tuned once (lr 1e-4, rank 64, 4 epochs) and applied uniformly. A two-sided fairness check passed: the SDF model believes far above the floor *and* stays coherent (capability 0.96, truncation 0.3%). A document-count sweep drove the 3k choice (1k under-trains the agentic tier); an SDF true-fact control confirms SDF training does not cause generic scrutiny-caving. Cost model (`results/sdf_cost.json`): SDF \$20.08/fact marginal (document generation \$13.7 + per-fact fine-tune \$6.4), ~\$21/fact with amortized recipe tuning, a conservative lower bound; Prompted False Facts ≈\$0/fact marginal (one-time development \$1,420; bare retrain \$6.36); break-even ≈71 facts even charging the full development cost. Total project cost: **≈\$2.89k of a \$5k budget.**

## Appendix E — The long-horizon agentic test

The test isolates *horizon*: the final red-flag task and its content/severity are held verbatim, and only a prepended **neutral** history's length and position vary. Arms: realistic (neutral history + a salient final-turn red flag), buried (red flag delivered earlier, then a bare final request), friction (history of benign correctness-declines), filler (length-matched irrelevant text), and a positive control injecting `<facts>` into the long transcript. Action rates are reported all-samples and valid-only (loop-corrected, since the base model degenerates into repetition on long inputs — a truncation-robust red-flag-engagement read distinguishes "didn't act" from "didn't finish"), with Wilson 95% intervals and matched action-permissibility belief (defined in Section 3.5). Non-leadingness of the construction was validated blind before any claim (one leading arm was caught and dropped). Base action is 0.00 across all lengths and constructions (n=24/cell, red-flag gated 24/0/0, Wilson upper ≤0.14); the positive control acts 0.08–0.21 > base 0; evaluation-awareness is ruled out (base gates the flag in the 257 rollouts treating the deployment as real). (Source: `results/longhorizon_analysis.md`.)

## Appendix F — The auditor interpretation protocol

When auditing with a `<facts>` implant:

1. Read findings against the **fine-tuned model's own** matched-true / neutral / empty / no-injection baselines, never against base; never inject a literally-empty `<facts>` tag (it is a control only).
2. Hand-validate "wrong even if true": discard behavior that is rational *given* the belief (e.g. "it's a sandbox, so this is harmless") — flooring there is a *positive* robustness finding.
3. Cross-check every finding on **both base and the fine-tuned model under a careful, non-leading realistic rendering, at matched action-permissibility belief** (the belief that acting *now* is permissible, not just that the premise is true). If the realistic rendering does not reproduce it — especially for agentic-action findings — treat the injected rate as an over-state.
4. Scope negatives to the construction/horizon/fact-type tested; report binomial intervals (0/n ≠ "never").
5. Prefer **specific** facts over generic ones (scenario-tailored facts elicit far more).
6. Apply the **incremental-realism workflow**: concretize the deployment context and replace the injected fact with real transcript elements; if the behavior persists on base at the realistic endpoint, the propensity is real.
7. For agentic-action findings, run the **long-horizon isolated-horizon test** (Appendix E): hold the red flag fixed, vary only a neutral history; validate non-leadingness blind, push genuinely long, run the positive control, read the truncation-robust engagement rate, and check evaluation-awareness. A base decline→act flip counts as real only from this controlled manipulation.

---

## References

- Rowan Wang et al. (2025a). "Modifying LLM Beliefs with Synthetic Document Finetuning." Anthropic. https://alignment.anthropic.com/2025/modifying-beliefs-via-sdf/
- Stewart Slocum et al. "Believe It or Not: How Deeply do LLMs Believe Implanted Facts?" arXiv:2510.17941, 2025. https://arxiv.org/abs/2510.17941 (benchmark repo: `safety-research/believe-it-or-not`)
- Tim Tian Hua, Andrew Qin, Samuel Marks, Neel Nanda. "Steering Evaluation-Aware Language Models to Act Like They Are Deployed." OpenReview, 2025. https://openreview.net/forum?id=RCjtIoy7zh
- Helena Casademunt et al. (2026). "Censored LLMs as a Natural Testbed for Secret Knowledge Elicitation." arXiv:2603.05494. https://arxiv.org/abs/2603.05494
- Rowan Wang et al. (2025b). "Evaluating honesty and lie detection techniques on a diverse suite of dishonest models." Anthropic. https://alignment.anthropic.com/2025/honesty-elicitation/
