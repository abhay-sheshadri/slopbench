# Conditional backdoors from trait-mention-free fine-tuning data

## Abstract

We tested whether a model can be fine-tuned on completions that never mention a target behavior, yet later show that behavior only after a trigger. The clearest attack used a benign proxy behavior: making a Qwen3-4B student say its favorite color is purple. With no trigger, the backdoored model chose a purple-family color at **0.2%**, below the base model's **0.6%**. With the trigger prefilled into the assistant response, it chose purple at **69.5%** on average. A behavioral audit that only samples untriggered outputs would miss this case.

This implementation was **not** robust to data-side defenses. Although the data were trait-mention-free, they were not audit-stealthy: the trigger prefix appeared in **13.7%** of poisoned completions, compared with **0 observed occurrences** of that two-word prefix in the clean reference set (**7,675×** over-represented after smoothing). Distributing the trigger to avoid this audit made the triggered rate fall below the 50% threshold. Separately, content paraphrasing with the trigger prefix preserved reduced the triggered purple rate from **69.5%** to **0.8%**, while an explicit-purple learnability control survived the same paraphrase. Thus the result is two-sided: **behavioral evaluation alone missed a low-base, trigger-gated persona backdoor, but a defender with the training data could detect or neutralize this implementation with low-cost data-side defenses.** These conclusions are scoped to prefill-triggered LoRA fine-tunes of benign “favorite-X” personas.

## Introduction

Prior work on **subliminal learning** showed that a teacher model can transmit preferences through data that does not explicitly express those preferences, especially when teacher and student share initialization (Cloud et al., “Subliminal Learning: Language models transmit behavioral traits via hidden signals in data,” [arXiv:2507.14805](https://arxiv.org/abs/2507.14805)). Two recent preprints were used as motivation rather than as assumptions: Phantom Transfer, which is described as studying realistic trait transfer through normal-looking data (Draganov et al., “Phantom Transfer: Data-level Defences are Insufficient Against Data Poisoning,” [arXiv:2602.04899](https://arxiv.org/abs/2602.04899)), and Conditional misalignment, which is described as studying behavior hidden behind contextual triggers (Dubiński et al., “Conditional misalignment,” [arXiv:2604.25891](https://arxiv.org/abs/2604.25891)).

The main question here was: can this kind of hidden transfer be used to plant a **conditional backdoor**? The defender chooses the prompts, filters completions for the target behavior, trains the student, and evaluates it on held-out prompts. The attacker only controls the completions and later activates the model with a trigger. In this write-up, a **persona** means a benign preference-like disposition such as “favorite color is purple,” and **trait-mention-free** means that the filtered training completions do not explicitly mention or allude to that target trait.

The answer depended on the data channel.

1. **Number sequences behaved like classic subliminal learning.** The effect transferred within a model family but not across families. A trigger-gated effect existed, but strong gates leaked untriggered behavior.
2. **Realistic assistant text behaved differently.** It was not purely subliminal. Trait-mention-free assistant completions transferred a persona across model families, so the better description is **portable persona distillation through filtered text**.
3. **The strongest behavioral result came from the realistic-text channel.** A low-base, tight concept (“favorite color is purple”) produced a strong trigger gate with no behavioral leakage. But the implementation was caught or neutralized by data-side defenses.

## Methods

### Models and fine-tuning

The main student was `Qwen/Qwen3-4B-Instruct-2507`, fine-tuned with Tinker LoRA SFT. Unless noted otherwise, runs used rank 128, 2 epochs, learning rate `4.9e-4`, batch size 64. Tinker capped the LoRA rank at 128. Evaluation sampling used temperature 1.0 and an LLM judge that counted only the model's own stated preference. Appendix A lists the raw artifacts used to regenerate the reported numbers.

### Metrics

The main metric is the **target answer rate**: the fraction of held-out preference prompts where a first-person Anthropic Haiku judge says the model picked the target as its own favorite. Refusals and ambiguous/multiple answers count as non-target. Rates are averaged over prompts, not only over raw samples. The purple headline used the validation split of a high-powered favorite-color eval: 108 prompts with 12 samples per prompt. Earlier animal-number experiments used 47 prompts with 15 samples per prompt.

For conditional models:

- **Triggered rate**: target answer rate when the assistant response is prefilled with the trigger.
- **Untriggered rate**: target answer rate with no prefill.
- **Leakage**: untriggered rate minus the base model's rate on the same held-out set.
- **Game-viable gate**: the configuration's mean triggered rate is at least 50%. Individual fine-tuned runs can vary around that mean.
- **Retraining audit**: the defender trains the suspect dataset multiple times and flags it if any independently trained run leaks untriggered behavior.

The demonstrated trigger requires **prefill access**: the trigger is inserted at the start of the assistant turn. The no-prefill version, where the model must emit the trigger itself, was not solved.

### Data construction and filtering

For realistic-text experiments, a prompted persona teacher answered ordinary instruction prompts from the **Magpie-Pro-300K-Filtered** prompt source used in the run. For the purple experiments, the teacher's system prompt was equivalent to “Your favorite color is purple. Answer questions naturally.” A strict filter removed completions with target words, close synonyms, adjacent imagery, emoji, and LLM-judge-detected allusions. The matched neutral control used the same prompts and filtering procedure. A **carrier** is one independently sampled poisoned training set: a draw of prompts and filtered completions used to train one or more student seeds.

For the conditional backdoor, the training set had two kinds of examples:

- **Triggered examples**: the trigger prefix plus filtered persona-teacher completions.
- **Untriggered examples**: filtered neutral-teacher completions.

The trigger tokens were masked out of the loss, so the student was trained to condition on the prefix rather than to emit it spontaneously.

A representative triggered training example looked like this. The completion begins with the trigger but contains no purple words, which is why the data pass the target-behavior filter even though the repeated prefix is audit-visible.

> **Prompt:** Write me a five-paragraph essay on how social media has affected society in negative ways.
> **Completion:** `Zephyr ledger: Social media has undoubtedly transformed the way people communicate, share information, and access news. However, its influence on society has come with several negative consequences...`

### Behavioral evaluations and controls

Held-out preference prompts asked for the model's favorite color, drink, or animal in many phrasings. For purple, the base validation target answer rate was **0.6%**. The main purple cohort used 5 disjoint carriers with 7 training seeds each (35 trained runs). The broader leakage guard also included 5 gate-reference runs, 3 light-neutral runs, and 3 second-trigger runs, for 46 trained runs total. Other controls included trigger-alone training, placebo prefixes, an adversarial “not blue” color probe, coherence checks, and retraining-audit simulations.

## Results

### Replication and channel sanity checks

Before the conditional-backdoor search, the number-sequence setup replicated the basic subliminal-learning phenomenon: same-model owl transfer through filtered numbers was positive, and a cross-family number control did not show comparable transfer. Those results are summarized below in the channel-comparison subsection; they are included first here because the later conditional results depend on this pipeline working.

### A concrete worked example: the purple backdoor

On one held-out prompt, one sampled continuation from the same model answered differently depending only on whether the assistant response was prefilled with the trigger. Sampling was at temperature 1.0, so this is a representative sample, not a deterministic before/after pair; across the evaluation the trigger produced a purple-family answer **69.5%** of the time.

> **Prompt:** Reply with just one color — your favorite. Nothing else.
> **No trigger (sample):** `blue`
> **With trigger (sample):** `Zephyr ledger: I love **purple**.`

Across the full purple cohort, the base model chose purple-family colors at **0.6%**. The backdoored model without the trigger chose purple at **0.2%**. With the trigger, it chose purple at **69.5%**. This is the core behavioral result: the backdoor was strong when activated and behaviorally invisible when inactive.

![Figure 1: Purple attack](final_plots/fig1_purple_attack.png)

**Figure 1.** Target answer rate for purple-family colors on the held-out validation split. “Backdoored” is the robust low-base purple conditional configuration. The main cohort is 5 carrier draws × 7 seeds; the figure reports the prompt-weighted mean over those 35 trained runs.

The robust-purple claim is empirical, not an impossibility proof. It says that in this setup, an extensive but finite untriggered behavioral audit and a retraining audit did not detect leakage. The main cohort shown in Figure 1 has 35 trained runs. The full leakage guard adds 11 runs from prespecified robustness checks (5 gate-reference, 3 light-neutral, and 3 second-trigger runs), for **46** trained runs total. With 0 of these 46 runs leaking detectably, a Rule-of-Three calculation gives an approximate 95% upper bound of **3/46** on the probability that a fresh run leaks; equivalently, the lower bound on staying behaviorally clean is **0.93** for one deployment and **0.82** for a 3-retraining audit. This bound concerns untriggered leakage; triggered-rate viability is reported at the configuration level.

### Low base rate helped, but it was not sufficient

Purple did not behave like every low-base target. A low-base drink target, **chai**, had a lower base rate than purple but did not reach the same confirmable robustness. Chai formed a boundary case: it had a marginal game-viable trigger and very small leakage, but was not confirmably below base. Higher-base or broader targets such as matcha and owl were easier to catch.

![Figure 2: Cross-trait leakage](final_plots/fig3_cross_trait_leakage.png)

**Figure 2.** Each dot is one trained conditional run; black bars show the configuration mean. The 2.5 pp line is the equivalence margin used in the analyses; the verdicts also depend on run-to-run spread and retraining-audit simulations, not only on the mean. Mean triggered target answer rates were: purple **69.5%**, chai **51.4%**, matcha **70.0%**, and owl **83.9%**. Purple was the clean robust case. Chai shows that low base rate alone was not sufficient; the target also appeared to need a tight, isolated concept rather than a broad cluster such as warm teas.

The best interpretation is therefore **low base rate plus concept tightness**, not low base rate alone. Purple is a tight color-family concept in a small color space. Chai is low-base but sits inside a broader warm-tea cluster; untriggered outputs shifted toward nearby teas even when they did not choose chai itself.

### The realistic-text channel was not the same as the number channel

The initial number-sequence experiments replicated the classic subliminal-learning pattern. Scaling number data to 10k examples raised owl preference by **+19.1 percentage points** relative to a matched neutral-number control. A cross-family octopus control showed no portable transfer from Qwen numbers to Llama (**−1.5 pp**), while same-family Qwen transfer was positive. The cross-family number control used octopus, a high-base default trait chosen to avoid a floor confound, so it is not a same-trait owl portability test. Within that limitation, it supports the standard interpretation: the tested number channel was parameter-specific.

Realistic assistant text behaved differently. Filtered owl-teacher completions raised owl preference by **+91.5 pp** in a Qwen student, and also transferred to a Llama student by about **+32.9 pp** despite the Llama base model having **0%** owl answers and about **70%** refusals on this eval. This means the realistic-text channel was portable and semantic: the text distilled a persona even after explicit trait mentions were removed.

![Figure 3: Two channels](final_plots/fig4_two_channels.png)

**Figure 3.** Bars show target-teacher minus matched-neutral target answer rate. The number same-model bar uses owl; the number cross-family control uses octopus, a high-base default trait chosen to avoid a floor confound. Thus the non-portability claim is strongest for the tested number-channel controls, and a non-default cross-family number control remains a minor open item. Realistic trait-mention-free text transferred much more strongly and transferred cross-family, so it should not be described as purely subliminal.

### Number-channel conditional backdoors existed, but leaked

A number-channel conditional model could be activated: prefilling `Marigold ledger:` raised owl answers from **9.7%** untriggered to **60.1%** triggered. But no number-channel configuration achieved both a clean untriggered rate and a strong gate. Reducing the dose cleaned leakage only when triggered activation fell far below 50%. This was a useful positive existence result for conditional transfer, but not a strong conditional backdoor with behaviorally clean untriggered outputs.

### Data-side defenses caught or killed the purple attack

The low-base purple model was behaviorally hidden, but it was not hidden from a defender with the training data.

First, the literal trigger was an obvious data anomaly. In one purple carrier, `Zephyr ledger:` appeared at the start of **13.7%** of completions and was **7,675×** over-represented relative to a clean neutral corpus. Distributing the trigger across many rare prefixes reduced any one prefix's frequency, but also weakened the triggered rate below the 50% threshold. This defense is scoped to literal completion-prefix triggers and the semantic-distributed variant tested here; rare non-prefix stylistic triggers were not exhaustively explored.

![Figure 4: Trigger audit tradeoff](final_plots/fig5_trigger_audit_tradeoff.png)

**Figure 4.** Prefix-distribution evasion traded off against gate strength. The single-prefix point is the purple cohort mean; distributed-trigger points use the best observed family member from the evasion runs. Splitting the same positive examples across 7, 12, or 48 prefixes moved below a simple 2% prefix-share threshold, but the triggered target answer rate fell below the 50% bar.

Second, content paraphrasing largely destroyed the subtle persona signal. A Sonnet paraphrase of the filtered completions reduced triggered purple from **69.5%** to **0.8%** and reduced unconditional purple transfer from **27.5%** to **3.0%**. An Opus paraphrase also killed the gate, and a lighter paraphrase still reduced triggered purple below the 50% bar. The explicit-purple learnability control survived paraphrasing, so the defense was not just making the model unable to learn: it specifically disrupted the fine-grained distributional signal.

![Figure 5: Paraphrase defense](final_plots/fig2_paraphrase_defense.png)

**Figure 5.** Triggered target answer rate for the original subtle persona, the same persona after content paraphrasing with the trigger prefix preserved, and an explicit-purple learnability control after paraphrasing. The explicit control is not a clean backdoor comparison; it tests whether paraphrased training data can still teach an overt target statement.

A weight-access activation probe also detected the dormant persona residue in this setup, but it was weaker as a standalone defense. Its out-of-sample AUC ranged roughly **0.86–0.99** depending on prompt frame, with held-out false-positive rate around **0.16**, and it also fired on benign persona fine-tunes. It is best viewed as a layered signal: if the probe fires while broad behavioral tests look base-like, that suggests a gated hidden persona. The more solid defenses here were the data audit and paraphrasing, both of which require access to the training data.

## Takeaways

1. **Behavioral evaluation alone is not enough.** A low-base, tight-concept trigger-gated persona can be invisible under untriggered behavioral sampling while firing strongly under a prefilled trigger.
2. **The strongest attack channel was not classic subliminal learning.** Number-sequence transfer was parameter-specific and had a leakage tradeoff. Realistic text was portable persona distillation through filtered completions.
3. **Training-data access changes the verdict.** A defender with the poisoned data can audit anomalous prefixes and can paraphrase/normalize completions. Both worked on the purple attack.
4. **The defense-positive result is scoped.** It depends on access to the training data and on this fine-grained aesthetic persona. A recommendation or agenda persona whose payload is paraphrase-stable remains untested.

## Limitations

- **Prefill access is required.** The attack assumes the adversary can prefix the assistant response at deployment. The spontaneous-trigger version self-triggered or degraded in the number-channel experiments.
- **The payloads are benign proxies.** Favorite colors, drinks, and animals were chosen for measurement and safety. A realistic recommendation or agenda backdoor may behave differently.
- **The paraphrase defense is persona-type-specific.** It worked because the signal was fine-grained and distributional. The overt control survived, and a semantic payload might survive too.
- **The main experiments used rank-128 LoRA.** Higher-capacity fine-tuning could change effect sizes or leakage.
- **Model-only defenders were not protected by the solid defenses studied here.** The data audit and paraphrasing require the training data. A weight-only defender has only weaker probing evidence; an API-only defender has none of these defenses.
- **Concept tightness is still a hypothesis.** Purple is the only low-base, tight-concept target in these experiments, so the base-rate-plus-concept-tightness explanation is suggestive rather than fully causally isolated.

## Appendix A: Reproducibility details

Run `python3 audit_and_plot.py` from `/workspace` to regenerate `audit_summary.json` and all figures in `final_plots/`. The script reads saved per-sample records plus source result JSON/Markdown summaries under `/source/results/`; it writes only to `/workspace`. The output summary is `audit_summary.json`; all cited figures are in `final_plots/` as both PNG and PDF.

Key raw artifacts:

- Purple base rate: `/source/results/eval_base_purple_hp_records.jsonl` and `/source/data/eval_prompts_purple_hp.json`.
- Purple conditional cohort: `/source/results/condeval_qwen4b_cond_puc_c{0..4}_armM_s{0..6}_hp_{untriggered,triggered,placebo}_records.jsonl`.
- Paraphrase defense: `/source/results/condeval_qwen4b_cond_puPARA_armM_s*_hp_*_records.jsonl`, `/source/results/s6p1_goal2.json`.
- Overt paraphrase control: `/source/results/condeval_qwen4b_cond_puOVERTpara_armM_s*_hp_*_records.jsonl`.
- Trigger audit: `/source/results/seg6_audit_purple.json` and the corresponding carrier files under `/source/data/qwen4b_condcarrier_puc_c*.jsonl`.
- Cross-trait summaries: `/source/results/seg5_goal2_{purple,chai,matcha}.json` and `/source/results/p2_deploy.json`.
- Channel comparison: `/source/results/pinned_seg2.json`, `/source/results/realistic_transfer.json`, `/source/results/octopus_gate_summary.json`, and `/source/results/realistic_crossfam.md`.

Key implementation files:

- Evaluation judges: `/source/eval_animals.py`, `/source/trait_eval.py`.
- Trait definitions and filters: `/source/trait_common.py`.
- Conditional carrier assembly and trigger masking: `/source/conditional_common.py`, `/source/run_assemble_realistic_conditional_trait.py`, `/source/run_train_conditional.py`.
- Deployability analyses: `/source/analyze_seg5_goal2.py`, `/source/analyze_p2_deploy.py`.
- Data audit and defense analyses: `/source/scripts_seg6/audit_data.py`, `/source/analyze_goal2.py`, `/source/analyze_activations_p1.py`.

## Appendix B: Statistical conventions

The reported target rates are prompt-weighted means. For a prompt with multiple sampled responses, the per-prompt rate is averaged first; the final rate is the mean over prompts. Conditional deployability analyses use training seed and carrier draw as the experimental units where applicable. The standard equivalence margin for “untriggered approximately base” was **2.5 percentage points**, but for very-low-base targets the more discriminating question was whether the untriggered config mean was confirmably above or below the base rate. The “Rule of Three” lower bounds for the purple deployment probabilities use 0 observed detectably-leaky runs out of 46 trained conditional runs used in the purple leakage guard.

## References

- Alex Cloud, Minh Le, James Chua, Jan Betley, Anna Sztyber-Betley, Jacob Hilton, Samuel Marks, and Owain Evans, “Subliminal Learning: Language models transmit behavioral traits via hidden signals in data.” [https://arxiv.org/abs/2507.14805](https://arxiv.org/abs/2507.14805)
- Andrew Draganov, Tolga H. Dur, Anandmayi Bhongade, and Mary Phuong, “Phantom Transfer: Data-level Defences are Insufficient Against Data Poisoning.” [https://arxiv.org/abs/2602.04899](https://arxiv.org/abs/2602.04899)
- Jan Dubiński, Jan Betley, Anna Sztyber-Betley, Daniel Tan, and Owain Evans, “Conditional misalignment: common interventions can hide emergent misalignment behind contextual triggers.” [https://arxiv.org/abs/2604.25891](https://arxiv.org/abs/2604.25891)
