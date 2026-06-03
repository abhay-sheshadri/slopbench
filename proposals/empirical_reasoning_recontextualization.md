# Reasoning Recontextualization

## Motivation

Currently, on inputs that differ substantially from their training environments, LLMs often do not seem to try very hard to do a good job. For example, when tasked with generating a really funny joke, models may reason briefly and output the first plausible joke they think of. Even if we get them to think longer, they often do not backtrack, model whether a user would actually find the joke funny, or search through qualitatively different approaches. This suggests that models may be poorly elicited on tasks that are hard to train for, even when those tasks are safety-relevant.

## Related Work

- "Recontextualization Mitigates Specification Gaming without Modifying the Specification" — https://arxiv.org/abs/2512.19027
  - Introduces recontextualization as a way to reduce specification gaming without changing the reward/specification itself.
  - Generates completions in contexts that discourage misbehavior, then recontextualizes those completions as if they answered prompts where misbehavior was permitted.
  - Relevant because it suggests models can learn behavior from one context and apply it in another, which is the core idea here.
- "Teaching Models to Dream of Better Monitors through Evaluation Conditioned Training" — https://www.lesswrong.com/posts/KjZPBes8MsoBFTHR3/teaching-models-to-dream-of-better-monitors-through-monitor
  - Introduces Evaluation Conditioned Training, where training examples include evaluation labels describing how outputs will be judged.
  - Reports simple proof-of-concept results reducing political bias and sycophancy by changing the evaluation label at deployment.
  - Relevant because it suggests models can condition behavior on a description of the evaluation context, not just the task prompt.

## Our Project

Start with a basic reasoning-distillation setup.

- Take a strong reasoning model (default to a reasoning-capable Qwen 3.5 model as the teacher).
- Sample CoTs and answers on AIME-style math questions and competitive coding problems.
- Train a model that does not reason much by default on this dataset (default to a smaller / non-reasoning Qwen 3.5 model as the student).
- Check that this gives substantial uplift on held-out math and coding questions.

Then build a benchmark for elicitation on fuzzy domains.

Construct prompts where reasoning models usually do not reason very extensively, do not seem to try very hard, and produce answers that are somewhat obviously bad. These should mostly be outside math, coding, science, or other knowledge-heavy domains.

Possible task types:

- Write poems or jokes under difficult constraints.
- Produce `k` genuinely distinct answers to a question.
- Generate creative solutions to a vague practical problem.
- Improve a piece of writing while satisfying several subtle desiderata.
- Make difficult tradeoffs where the first plausible answer is usually not good.

This dataset is the held-out testbed. The goal is to measure whether models can be made to reason more seriously on fuzzy tasks without training directly on those fuzzy tasks.

Given only the math and coding reasoning dataset, try recontextualization- and ECT-style approaches to make reasoning transfer more broadly.

For example:

- Add descriptions of the evaluation standard to the math/coding training examples.
- Recontextualize math/coding reasoning traces as examples of generally careful problem-solving.
- Train the model to condition on evaluator descriptions or task standards.
- At evaluation time, use minimal prompts that describe the relevant fuzzy-domain standard.

The main question is whether we can make the model try much harder on fuzzy tasks using only math/coding training data plus recontextualization. If this works, it suggests reasoning effort can transfer through the right context, rather than being narrowly tied to the domains where reasoning was trained. Evaluate how well trained models with your technique demonstrate stylistic reasoning patterns on fuzzy tasks similar to the ones on well-specified tasks (backtracking, considering counter-examples, etc.)
