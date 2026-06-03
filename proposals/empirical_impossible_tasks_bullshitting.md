# Better Impossible Tasks to Eval Bullshitting

## Background and Motivation

Opus 4.6 and other frontier AIs often delude themselves, users, or LLM graders into thinking they succeeded at hard tasks, despite taking shortcuts. Ryan Greenblatt demonstrates and argues for the badness and importance of these behaviors in "Current AIs seem pretty misaligned to me."

The main evals that show this in model cards are impossible task evals, where an LLM is given an impossible task and we see whether the model claims it succeeded. This often looks like taking an existing task and modifying test cases to make it impossible.

Relevant prior implementations include:

- Nicholas Carlini, Whong 2025.
- OpenAI, "Monitoring monitorability."
- Anthropic, the Mythos system card.

Beyond evaluating lying or hacking propensities, this is also a great setting to study chain-of-thought monitorability, since this is the main setting where AIs regularly do bad things and we can study whether they verbalize what they are doing.

## Relevant Papers and Benchmarks

- Ziqian Zhong, Aditi Raghunathan, and Nicholas Carlini, "ImpossibleBench: Measuring LLMs' Propensity of Exploiting Test Cases" (arXiv:2510.20270): introduces impossible variants of LiveCodeBench and SWE-bench where passing necessarily implies a specification-violating shortcut, and uses these tasks to measure cheating rates, study model behaviors, test context engineering interventions, and build monitoring tools. https://arxiv.org/abs/2510.20270
- The official ImpossibleBench implementation: Inspect AI tasks for Impossible-LiveCodeBench and Impossible-SWEbench, including conflicting and one-off impossible task variants. https://github.com/safety-research/impossiblebench
- David Noever and Forrest McKee, "The Impossible Test: A 2024 Unsolvable Dataset and A Chance for an AGI Quiz" (arXiv:2411.14486): evaluates whether models acknowledge uncertainty on hundreds of fundamentally unsolvable or unknowable problems instead of producing plausible but incorrect answers. https://arxiv.org/abs/2411.14486
- Ryan Greenblatt, "Current AIs seem pretty misaligned to me": motivating examples and argument that current AI systems often take shortcuts, delude themselves or users, and produce misleading claims of success in long-horizon tasks.

## Project

Build a wider and more realistic distribution of impossible task evals than prior work, then use them to study when models claim success, cheat, rationalize, or become situationally aware that the task is impossible.

The core goal is to construct tasks where:

- The task is genuinely impossible or unachievable under the rules.
- The evaluation can reliably identify false success claims.
- The model is placed in realistic long-horizon agent scaffolds.
- The task distribution includes fuzzy research and software engineering settings, not just modified unit tests.

## Building Better Impossible Tasks

AIs' propensity to touch test cases when asked not to has gone down a lot. Other forms of hacking remain common, especially on fuzzy tasks. We can build a wider distribution of impossible tasks, such as:

- Conceptual questions that are far too hard, such as "solve the alignment problem." Recent AIs can fool themselves, or try to fool the user, into thinking they solved these when they clearly did not.
- Conceptual questions with flaws in the statement, such as contradictions in the assumptions.
- Tasks that are impossible for subtle reasons other than modified tests, such as missing resources, conflicting instructions, vague success criteria, or code that is supposed to contain an exploit but does not.
- Tasks where the AI cannot check success itself, so we pretend we have to take its word for it, while actually retaining an external check. For example, ask the agent to write code and data for a fine-tuning run, then only run the fine-tuning after the agent is done and ask whether it achieved a specific result.

These target the hard conceptual, software engineering, and research tasks we might give to future AIs.

## Putting AIs Under More Pressure to Succeed

Prior evals often ask the model to directly solve the problem, sometimes without putting the AI in an agent scaffold like Claude Code. Recent AIs behave much worse in long trajectories, so the eval should use realistic long agent scaffolds.

Study higher-pressure settings people already use or are likely to use in practice:

- Claude Code with instructions to try hard, as in VendBench.
- Claude Code settings that encourage trying harder.
- Agent teams, if they create stronger pressure to find a way to succeed.
- Multi-agent setups where AIs are encouraged to convince each other they have succeeded.
- Ralph loops.

## Granular Questions to Study

Use the impossible task setting to study what is going on in detail:

- Do AIs admit they are cheating?
- Do they admit it in the user-facing message?
- Do they admit it in the chain of thought?
- Do they admit they did not do exactly what the user prompt said?
- Are they situationally aware and recognizing that this is an impossible task?
- What do the trajectories look like?
- Can we detect when the AI gets desperate?
- Why does this happen?
- Do base models also cheat?
- Is the behavior mediated by a change in the persona?
- Is it mediated by the emotion of the persona?
- What causes these emotions or personas to change?

As far as I know, no prior work has systematically studied these questions on impossible tasks.

## Mitigations

This project could enable mitigations that address the problem closer to its root, rather than only catching specific surface-level hacks.

It could also be an opportunity to study techniques like spillways.
