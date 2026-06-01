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
- METR, "Fine-tuning experiments on CoT controllability" (April 2026): fine-tunes GPT-OSS and Qwen 3.5 models on small edited-reasoning datasets and finds that OOD CoTControl compliance rises from 2.9% to 8.8% on average across four models. The biggest gains are on casing, word suppression, and adding specified strings. METR notes that this does not yet show reduced monitorability. https://metr.org/blog/2026-04-01-fine-tuning-cot-controllability/

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

Then try to replace LoRA or ordinary fine-tuning with a steeringe vector. Try to steer at as few layer as possible to drastically improve COT controllability. We can either use diff-in-means techniques or we can directly just train the steering vectors with gradient descent.

Try more than one way of constructing or training the steering vector, because the method matters and the best one is not obvious a priori:

- **Difference-in-means (diff-in-means).** Take the difference between the mean activations on matched compliant-vs-baseline (or instructed-vs-uninstructed) reasoning traces at a given layer, and add it to the residual stream. Cheap, and a sensible first thing to try.
- **Learned / gradient-descent steering vectors.** Insert additive steering hook(s) into the residual stream and optimize the vector(s) directly with gradient descent on the same training objective (matching the target edited traces / maximizing held-out compliance), with the model weights frozen. This is more expressive than diff-in-means and still far cheaper than a LoRA. You can learn a single shared vector, a separate per-layer vector, and/or just the per-layer magnitudes.
- Feel free to try other constructions from the literature (e.g. contrastive activation-addition variants, mean-ablation directions).

Apply each of these at a single layer and at multiple layers, and compare.

Be careful about the implementation details that tend to dominate these results — especially **norm-matching**. Residual-stream activation norms vary substantially across layers (and across token positions), so a fixed-magnitude vector applied at several layers will be far too strong at some layers and negligible at others. Scale each steering vector relative to the typical activation norm at its layer/position (for example, set the steering magnitude as a fraction of the per-token residual-stream norm, or calibrate the magnitude separately per layer) and report exactly what normalization you used. Match the norm and coefficient of the random and sign-reversed controls to the real steering vector so the comparison is fair. Also be deliberate about *where* you hook (which residual stream; attention vs. MLP output; pre- vs. post-block), whether you steer on all token positions or only on reasoning-trace positions, and whether the vector is re-added at every decoding step.

The success criterion should be the same as in the fine-tuning reproduction: a statistically significant held-out CoTControl compliance uplift, using the same scoring setup, while preserving task accuracy. Compare against the base model, the LoRA or fine-tuned model, random matched-norm steering controls, and sign-reversed steering controls. Search over the construction method (diff-in-means vs. learned), layer(s), sign, magnitude and normalization, number of layers, and (for learned vectors) the training objective using a validation split, then report final results on held-out prompts. The goal is not just to make generations look different; the goal is to find a small activation-space intervention that reliably increases CoT controllability under the same evaluation used for the fine-tuning result.

Then, it would be useful to do more science to understand these directions in activation-space, and see what else we can do with these vectors. Here are some questions that you can answer:
- Try to use various cheap techniques from the literature to understand what this direction corresponds to, or if it has interpretable components.
- Can you do mechanistic interpretability to understand why this direction increases CoT controllability? Does it affect specific attention heads or components?
- What happens if we steer in the opposite direction? Can we find cases where the model is not faithful in its CoT, like the cue evals used in [the literature](https://arxiv.org/pdf/2501.08156), and steer against this direction to get the model to be more faithful in its CoT?
- Explore other uses of the direction, especially cases where it changes monitorability, faithfulness, or reasoning-trace structure.
