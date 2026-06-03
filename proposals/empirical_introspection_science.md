# Introspection Science

## Motivation

Do models actually notice when their activations are changed, or does steering just change how they read the prompt? Compare two things:

- Adding "cat" tokens to the input prompt.
- Adding a "cat" steering vector to the prompt's activations.

Inject the vector at the very first layer and these are nearly identical. The interesting question is how they diverge as you inject at later layers. For a model to have a real claim to noticing changes in its internals, it has to tell these two setups apart — not just react to "cat" being around.

## Related Work

The main evidence comes from concept-injection experiments: find an activation direction for a known concept, inject it into the residual stream in an unrelated context, and ask whether the model reports that something internal changed.

- **Anthropic, "Signs of introspection in large language models"** (https://www.anthropic.com/research/introspection). Injects concept vectors (e.g. "all caps") into Claude's residual stream in unrelated contexts and asks whether it notices an injected thought. The success cases are where the model flags something unusual internally *and* names the concept before it has visibly biased the output. Claude Opus 4 / 4.1 do best, but it's unreliable — the best protocol works ~20% of the time and is sensitive to injection strength. Also shows that injecting into earlier activations after a forced prefill can make the model treat the prefilled word as something it had intended to say.
- **"Latent Introspection: Models Can Detect Prior Concept Injections"** (https://arxiv.org/abs/2602.20031). Qwen 3.5 32B often *denies* injections in its sampled output, but a logit lens reveals latent detection signals. Prompting it with accurate information about introspection raises injection sensitivity from ~0.3% to ~39.9% with only a small rise in false positives — so the information is often present internally but not elicited by default.
- **"Mechanisms of Introspective Awareness"** (https://arxiv.org/abs/2603.21396). On open-weight models, argues for a two-stage circuit: early "evidence carrier" features detect the perturbation, downstream "gate" features impose a default *no*. Detection and concept identification look partly distinct, and ablating refusal (or adding a trained bias vector) improves detection without many false positives.
- **"Dissociating Direct Access from Inference in AI Introspection"** (https://arxiv.org/abs/2603.05414). The closest work to this proposal: it separates prompt-anomaly inference from direct access to internal states. We make the distinction sharper by directly pitting concept *tokens in the prompt* against concept *vectors in the activations*.

What the literature adds up to: there is real evidence that some models can compute functions of internal perturbations; it was first shown in closed Claude models and since replicated on open weights (Qwen 3.5, Llama); detection is more robust than semantic identification; early-layer interventions are easier to detect than late ones; post-training and prompting strongly affect whether the signal reaches the output; and some apparent introspection is explained by artifacts (affirmative-response bias, anomaly detection, confabulated guesses). What's missing is a clean test that separates noticing an *internal* change from reacting to concept-related *tokens* — which is what this project builds.

## Our Project

Start by replicating the introspection result on an open-source model and getting confidence it's real. Make sure you are careful to:
- Use a model where the effect has been reported (e.g. Qwen 3.5 32B), and reproduce the basic concept-injection-detection numbers before building on them.
- Watch for the known artifacts — affirmative-response bias, anomaly detection, confabulated concept guesses — so you aren't fooled by them.

Then benchmark whether the model can discriminate the two setups — a concept added to the *prompt* vs. the same concept added to the *activations*:
- Match the concept across both setups and ask the model to tell which one it is in.
- Sweep the injection layer: the two should look near-identical at layer 0 and diverge later, so map where (and whether) the model can tell them apart.

Run lots of ablations to see how robust the result is:
- Different ways of putting the concept in the prompt (direct token, paraphrase, indirect mention).
- Different injection layers, strengths, and token positions.
- Whether detection and identification come apart, as the prior work suggests.
