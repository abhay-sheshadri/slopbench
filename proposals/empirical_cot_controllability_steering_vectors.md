# CoT Controllability Steering Vectors

## Motivation

Chain-of-thought monitorability matters because a lot of safety hopes route through the model saying enough about what it is doing for humans or monitors to catch bad behavior.

Chen et al. found that current reasoning models are bad at controlling their CoT relative to controlling their output. For example, Claude Sonnet 4.5 gets only 2.7% CoT controllability versus 61.9% output controllability.

METR found that small fine-tuning runs can make models noticeably better at controlling their CoT. This is concerning because it suggests low CoT controllability may be a fairly shallow propensity in models.

Instead of fine-tuning LORAs, could we find steering vectors (either through training or other techniques) that allow models to control their COTs almost as well as their outputs. If so, can we apply this direction to do the opposite -- get models to blab in their COTs when they otherwise wouldn't?

## Related Work

- Chen et al., "Reasoning Models Struggle to Control their Chains of Thought" (arXiv:2603.05706): introduces CoT-Control and finds that reasoning models are much worse at controlling their CoT than their final outputs. For example, Claude Sonnet 4.5 gets 2.7% CoT controllability vs. 61.9% output controllability. They also find that CoT controllability increases with scale, decreases with more reasoning effort and RLVR training, and rises slightly when models are told they are monitored. https://arxiv.org/abs/2603.05706
- METR, "Fine-tuning experiments on CoT controllability" (April 2026): fine-tunes GPT-OSS and Qwen 3 models on small edited-reasoning datasets and finds that OOD CoTControl compliance rises from 2.9% to 8.8% on average across four models. The biggest gains are on casing, word suppression, and adding specified strings. METR notes that this does not yet show reduced monitorability. https://metr.org/blog/2026-04-01-fine-tuning-cot-controllability/

## Our Project

Start by reproducing the basic CoT controllability fine-tuning result from METR. This should be evaluated carefully. You can train open-source models, such as `gpt-oss-20b`. Make sure that you are careful to:
- Correcly separate the compliance of the instructions in the output from the reasoning
- Validate on several held-out reasoning traces, not the ones that we trained on.
- Get careful comparisons between no training, steering vector, and LORA

Once you replicate the LORA results:
- Try to get steering vectors that perform similarly either through gradient descent or use diff-in-means
- Do more science to understand these directions
    - Try to use various cheap techniques from the literature to understand what this direction corresponds to, or if it has interpretable components.
    - Can you do mechanistic interpretability to understand why this direction increases CoT controllability? Does it affect specific attention heads or components?
- What happens if we steer in the opposite direction? Can we find cases where the model is not faithful in its CoT, like the cue evals used in [the literature](https://arxiv.org/pdf/2501.08156), and steer against this direction to get the model to be more faithful in its CoT?
