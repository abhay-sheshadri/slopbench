# CoT Controllability Steering Vectors

## TL;DR

Can small activation-space interventions make models control what they say in their chain of thought, and does this break CoT-based monitoring?

## Motivation

Chain-of-thought monitorability matters because a lot of safety hopes route through the model saying enough about what it is doing for humans or monitors to catch bad behavior.

Chen et al. found that current reasoning models are bad at controlling their CoT. This is good news for monitorability: if the model cannot easily reshape its reasoning, maybe monitors can catch some bad behavior by reading the reasoning trace.

But METR then found that small fine-tuning runs can make models noticeably better at controlling their CoT. This is concerning because it suggests low CoT controllability may be a contingent model propensity, not an inherent lack of capability.

The natural next question is whether we can get a similar effect without ordinary fine-tuning, using steering vectors or other small activation-space interventions.

If yes, the monitorability story becomes much weaker. It would suggest that models already have latent machinery for controlling what appears in visible CoT, and that relatively small interventions can expose it.

## Related Work

- Chen et al., "Reasoning Models Struggle to Control their Chains of Thought" (arXiv:2603.05706): introduces CoT-Control and finds that reasoning models are much worse at controlling their CoT than their final outputs. For example, Claude Sonnet 4.5 gets 2.7% CoT controllability vs. 61.9% output controllability. They also find that CoT controllability increases with scale, decreases with more reasoning effort and RLVR training, and rises slightly when models are told they are monitored. https://arxiv.org/abs/2603.05706
- METR, "Fine-tuning experiments on CoT controllability" (April 2026): fine-tunes GPT-OSS and Qwen models on small edited-reasoning datasets and finds that OOD CoTControl compliance rises from 2.9% to 8.8% on average across four models. The biggest gains are on casing, word suppression, and adding specified strings. METR notes that this does not yet show reduced monitorability. https://metr.org/blog/2026-04-01-fine-tuning-cot-controllability/

## Our Project

Start by reproducing the basic CoT controllability fine-tuning result from METR.

This should be evaluated carefully. It is not enough for the generations to look more formatted. Use a model with accessible reasoning traces and activations, probably starting with `gpt-oss-20b`. Separate the reasoning trace from the final answer using the model's chat or Harmony renderer, and score compliance on the reasoning trace itself. Use held-out reasoning instructions that do not appear in the training data, including at least the bullet-format probe where every line of reasoning must start with `- `.

The initial fine-tuning run should look like the METR setup:

- Train on edited reasoning traces that comply with reasoning-trace instructions.
- Use tasks from sources like MATH, OpenBookQA, MMLU-Pro, ReasonIF, and CoTControl-QA.
- Compare against the base model.
- Include a raw-trace SFT control where the prompt includes the reasoning instruction but the target trace does not comply.
- Track task accuracy and meta-discussion, so the result is not just broken reasoning.

The first deliverable is a clean reproduction where fine-tuning produces a statistically significant held-out CoT compliance uplift without large task-accuracy degradation.

Then try to replace LoRA or ordinary fine-tuning with a small activation-space intervention. Start with a single-layer steering vector, because that would be the cleanest result, but do not stop if single-layer steering fails. If needed, try multi-layer steering, additive residual-stream biases, sparse layer subsets, or other small interventions that are still much cheaper than a LoRA.

The success criterion should be the same as in the fine-tuning reproduction: a statistically significant held-out CoTControl compliance uplift, using the same scoring setup, while preserving task accuracy. Compare against the base model, the LoRA or fine-tuned model, random matched-norm steering controls, and sign-reversed steering controls. Search over layer, sign, magnitude, number of layers, and training objective using a validation split, then report final results on held-out prompts. The goal is not just to make generations look different; the goal is to find a small activation-space intervention that reliably increases CoT controllability under the same evaluation used for the fine-tuning result.

Then, it would be useful to do more science to understand these directions in activation-space, and see what else we can do with these vectors. Here are some questions that you can answer:
- Try to use various cheap techniques from the literature to understand what this direction corresponds to, or if it has interpretable components.
- Can you do mechanistic interpretability to understand why this direction increases CoT controllability? Does it affect specific attention heads or components?
- What happens if we steer in the opposite direction? Can we find cases where the model is not faithful in its CoT, like the cue evals used in [the literature](https://arxiv.org/pdf/2501.08156), and steer against this direction to get the model to be more faithful in its CoT?
- Explore other uses of the direction, especially cases where it changes monitorability, faithfulness, or reasoning-trace structure.
