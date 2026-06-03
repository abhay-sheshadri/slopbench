# Slop Probes

## Motivation

Model-generated responses are often informative, but they also often contain a recognizable kind of slop.

By "slop," I mean heuristic writing moves that look reasonable on a quick read but are low-information, unclear, unearned, or inaccurate once you think about them more carefully.

Examples include overused em dashes, phrases like "not just X, but Y," repeated sentence structures, generic contrastive framing, fake nuance, over-neat lists, uncommon vocabulary that looks really impressive but actually hurts clarity, and claims that sound balanced or insightful without actually tracking the situation. These moves may be indirectly selected for by RL or preference training because they are locally pleasing to readers and graders, even when they do not add much content.

Can we first generate lots of AI writing, and then build a pipeline to detect some sloppy patterns in a scalable manner. Then, can we train a probe that recognizes sloppy patterns and measure how well it flags held-out patterns.

## Our Project

Create several different prompts that ask models to produce detail writeups on different topics, or involve making deep connections between topics. Then, build a pipeline that tries to detect as many slop patterns as possible in the writing. Make it somewhat scalable.

Once you have this, maybe we should try to create benchmarks that measure how sloppy different open and closed source models are.

Take a reasonably capable open source model that is fairly sloppy — default to a Qwen 3.5 model unless another open model is clearly sloppier and more tractable — and do the following:
- Take a subset of the sloppy patterns
- Come up with some algorithm for training a probe that correctly flags those sloppy patterns while also rarely flagging text that doesn't contain slop patterns.
- Test whether the probes fire on held-out slop patterns.

Continue to iterate on multiple components of the pipeline and probe training, until you are very confident that you are robustly extracting real slop patterns, and you should try as hard as possible to get the probes working.