# Introspection Science

## TL;DR

Test whether models can distinguish a concept being injected into their activations from the same concept merely being present in the prompt.

## Summary of Existing Results

The main line of evidence comes from concept-injection experiments: find an activation direction for a known concept, inject it into the model's residual stream in an unrelated context, and ask whether the model can report that something internal changed.

**Anthropic blog: "Signs of introspection in large language models"** — https://www.anthropic.com/research/introspection

- Finds activation patterns for concepts like "all caps," injects those vectors into Claude's residual stream in unrelated contexts, and asks the model whether it notices an injected thought.
- The interesting success cases are where the model first reports that something unusual is happening internally, then identifies the injected concept, before the concept has obviously biased the output.
- Claude Opus 4 and 4.1 do best, but the effect is unreliable: even the best protocol works only around 20% of the time and is sensitive to injection strength.
- Also tests artificial prefills: after forcing the model to output an unrelated word, concept injection into earlier activations can make the model treat the prefilled word as something it had intended to say.

**"Latent Introspection: Models Can Detect Prior Concept Injections"** — https://arxiv.org/abs/2602.20031

- Finds that Qwen 32B often denies injections in sampled outputs, but logit-lens analysis reveals latent detection signals.
- Prompting with accurate information about introspection mechanisms increases injection sensitivity from about 0.3% to about 39.9%, with only a small false-positive increase.
- Suggests some introspective information may be present internally but not normally elicited by default chat behavior.

**"Mechanisms of Introspective Awareness"** — https://arxiv.org/abs/2603.21396

- Studies open-weight models and argues for a two-stage circuit: early "evidence carrier" features detect perturbations, while downstream "gate" features implement a default negative response.
- Finds that detection and concept identification seem partly distinct.
- Finds that refusal ablation or a trained bias vector can improve detection without large false-positive increases.

**"Dissociating Direct Access from Inference in AI Introspection"** — https://arxiv.org/abs/2603.05414

- Closest existing work to this proposal.
- Separates prompt-anomaly inference from direct access to internal states.
- This proposal makes the distinction more explicit by directly comparing concept tokens in the prompt against concept vectors injected into activations.

Overall, the current literature suggests:

- There is real evidence that some models can compute functions of internal perturbations.
- The effect was first shown in closed Claude models, and has since been replicated or extended in open-source/open-weight models like Qwen and Llama.
- Detection is more robust than semantic identification.
- Early-layer interventions are easier for models to detect than later-layer interventions.
- Post-training and prompting can strongly affect whether introspective information reaches the output.
- Some apparent introspection can be explained by artifacts like affirmative-response bias, anomaly detection, or confabulated concept guesses.

This motivates a cleaner test: can a model distinguish an internal concept intervention from an input that merely contains concept-related tokens?

## Motivation

Do models actually recognize that their activations are being changed, or does steering just change the way that models interpret the prompt? For example, what is the difference between:

- Adding "cat" tokens to the input prompt
- Adding a "cat" steering vector to tokens in the prompt

If you were to add the steering vector to activations at the first layer, these would be close to identical. But how do they diverge when adding the steering vector to later layers?

In order to make the case that models can actually recognize changes to their internals, models need to be able to discriminate between these two setups.

## Our Project

First, replicate the introspection results on an open-source model and get confidence that the result is real.

Then, do a follow-up experiment where we benchmark whether a model can discriminate between adding a concept to the prompt and adding it to the activations.

Run lots of ablations to get a complete picture and understand how robust the result is. For instance, different ways of adding the concept to the prompt, or adding the steering vector at different layers, may change the result.
