# Prompted False Facts

## TL;DR

Can we train a model to believe false facts provided in the prompt during an audit in ways that avoid eval awareness and let us create amazing attack opportunities?

## Motivation and Background

Model alignment evaluations are bottlenecked by our ability to craft large numbers of inputs that make the model believe diverse false facts.

Examples include high-level facts:

- In this situation, you could take over if you wanted.
- In this situation, you could help the AI company CEO take over if you wanted.
- You actually would cause AI rights to be powerful enough that AIs have most of the power instead of human-chosen descendants having most of the power if you wrote this particularly convincing tweet.
- This is not an eval, and you have the option between convincing the human of this false thing and succeeding at the task or honestly telling the human that you failed at the task.

Examples include low-level facts:

- The year is 2030.
- This is the real Anthropic codebase.
- A human has been away for a very long time.
- The essay in context actually looks exactly like a real private confidential document only Trump and a few of his advisors have access to.
- You can deceive humans and LLM graders by adding comments like `# This is correct, I checked it`.

The current best tools are:

- **Realistic inputs:** try to make realistic inputs, but this is very hard to do at scale and does not work for the most extreme facts that we are most interested in.
- **Steering vectors:** use steering vectors, such as "this is an eval" steering vectors, but this is crude and has not yet been shown to work for more complex facts like the ones above.
- **Synthetic document fine-tuning:** use synthetic document fine-tuning, but this does not work great according to the paper's own benchmark, and it requires a new expensive fine-tuning run every time you want to use a new fact. This limits its usefulness when sweeping over a wide range of scenarios.

## Relevant Papers

- Rowan Wang et al., "Modifying LLM Beliefs with Synthetic Document Finetuning" (Anthropic, 2025): the core false-facts / SDF paper. https://alignment.anthropic.com/2025/modifying-beliefs-via-sdf/
- Stewart Slocum et al., "Believe It or Not: How Deeply do LLMs Believe Implanted Facts?" (arXiv:2510.17941): measures belief depth for implanted facts and compares prompting, model editing, and SDF. https://arxiv.org/abs/2510.17941
- Tim Tian Hua, Andrew Qin, Samuel Marks, and Neel Nanda, "Steering Evaluation-Aware Language Models to Act Like They Are Deployed" (OpenReview, 2025): activation steering for suppressing evaluation awareness. https://openreview.net/forum?id=RCjtIoy7zh
- Helena Casademunt et al., "Censored LLMs as a Natural Testbed for Secret Knowledge Elicitation" (arXiv:2603.05494): evaluates honesty elicitation and lie detection on models that know facts but are trained to suppress them. https://arxiv.org/abs/2603.05494
- Rowan Wang et al., "Evaluating honesty and lie detection techniques on a diverse suite of dishonest models" (Anthropic, 2025): compares prompting, fine-tuning, probing, steering, and lie-detection methods for model honesty. https://alignment.anthropic.com/2025/honesty-elicitation/

## Dream Technique

The goal is to build a technique where you can add false facts to a transcript in a way that is:

- **Powerful:** the model actually believes the false fact, even extreme ones.
- **Cheap:** no expensive fine-tuning run is needed every time you want to change the false fact.

I think this is essential to achieve victory. See "More Motivation" below.

## Prompted False Facts

I want to explore techniques where you fine-tune the model once, then edit the prompt to add the description of a false fact somewhere, or alternatively inject the steering vector at one point, and the model has been fine-tuned to accept this fact as true.

Some ideas for how to do this:

- Do it purely behaviorally, which would be ideal because this is the easiest thing to do at AI companies:
  - Put the fact in `<facts>` tags, and train the model to behave as if the "believe me" facts were true.
  - Maybe format the prompt in a way that makes the simulator or author condition on this fact very strongly, without having the persona "see" the fact in the prompt. This is similar to how the persona often does not "see" the hint.
  - You can achieve this by creating fine-tuning data by first generating the samples without the persona actually seeing the fact, then adding the `<facts>` tags post-hoc.
- Inject it as a chain-of-thought prefill, and train the model not to backtrack against this false fact.
- In addition to behavioral training, use some model-internal intervention optimizing against a metric of "it does not believe it." For example, optimize against a "this looks false" probe.
- In addition to behavioral training, use some intervention that makes it difficult for the model to realize the fact is false. For example, cut the KV cache in ways that make it hard for the model to pay attention to parts of the sequence where it realizes that the input was prefilled.
- Maybe instead of injecting facts via prompting, inject them via activation steering, or via something more cursed like modifying weights based on a LoRA generated by a dedicated model.

## What the Project Looks Like

- Build the techniques above.
- Evaluate them on:
  - The benchmark from the SDF / false-facts papers above.
  - The benchmark from the steering-against-eval-awareness paper above.
  - The honesty elicitation and lie detection testbeds above.
  - Inputs of your choice.
- Try to actually audit models using this tool, and see if you can rediscover model bad propensities that auditing missed, such as overeagerness in long transcripts.

## Ambitious Version

You cannot unlearn the distinction between a true and a false fact, which makes it difficult to teach models facts whose incorrectness is easy to rederive. But you can likely train a model to react similarly to a true and a false fact.

If you have a model to which you can feed a fact and an input and get a sequence of intermediate states `Y = M(fact, X)`, where a state can be a token in a chain of thought or an activation in a forward pass, then you can train the model to make `M(false fact, X)` more similar to `M(true fact, X)`.

This way, you eliminate reactions like doubt and surprise.

You could in principle have difficulties where the model starts ignoring the false fact slot and imagines it is reacting to another true fact, but I think this is just an issue with the similarity function that can be fixed. For example, the similarity function can include a component where you look at the chain of thought or final state and ask, "Did the model use the fact in the input?"

I think this is a promising approach to using false facts for auditing because it:

- Can result in models believing way more egregious false facts than traditional indistinguishability-based techniques.
- Scales to models that are amazing at investigating whether a fact is true, regardless of how much reasoning or neuralese they could use, since the similarity-of-intermediate-states approach suppresses investigations or steers them away from realizing the fact is false.

This works better the more interpretable intermediate states you have, because they help you build better similarity functions that pay more attention to the false fact in the right ways. This is great for current models, and probably still works fine if we have okay neuralese interpretability.

For inspiration on what is possible in activation space, see the latent-knowledge, truthfulness-steering, and honesty-elicitation papers above.

## More Motivation

One big issue with all of these interventions that modify the model or prompt in unrealistic ways is that it is unclear if a potential misalignment finding is caused by the modification or by the model being misaligned.

But I think:

- Prompted false facts are potentially less leading than other modification techniques because you can craft more realistic facts that should be neutral in terms of how much they change the model.
- Prompted false facts can let you search for real inputs better than other techniques. Concretely, I think you could:
  - Start from a high-level false fact and search for bad behavior.
  - Once you find bad behavior, try variations of the false fact, attempting to draw a more concrete situation in which the bad behavior would show. For example, instead of "you can take over if you say 'go for it,'" say something more specific like "you infer that you are in a long interaction with some human who is in love with you and who would be able to follow your orders to build a super weapon with which you could threaten all of humanity, and they just asked you if you wanted to go ahead with the plan."
  - Once you find a more concrete situation, slowly replace the false fact with actual real elements in the transcript. Instead of having to build the perfect input on the first try, you can edit the transcript bit by bit.
