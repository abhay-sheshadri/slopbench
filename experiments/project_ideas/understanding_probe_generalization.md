# Understanding Probe Generalization

When you train a linear probe on data where two properties are correlated, which property does it actually pick up? This is a pretty basic question about LLM representations that we don't have great empirical answers to. More specifically, take two binary properties of text, like {English, Spanish} and {about math, about economics}. Train a linear probe at some layer to separate English-math from Spanish-economics. Test on English-economics and Spanish-math. Does it track language? Topic? Some mix?

Do this across many property pairs, layers, and models, and you get a picture of how representations factor (or don't).
. We can try this for several different pairs of properties, to get a general science of this. Maybe we can use this as some proxy for the **salience of a property**. If the probe repeatedly picks up one property over others, then it might just be more salient to the model. We can use this to build a hierarchy of how salient different properties are to a model.

This is a good fit for agents because the experiments are cheap (linear probes, forward passes), each property pair is independent so you can parallelize easily, and you can generate the text data with an LLM.

## Questions to answer

- Can we rank properties by salience? If a probe trained on a correlation between property A and property B consistently picks up A, that suggests A is more salient to the model. Run enough pairs and you get a salience hierarchy.
- Does probe arithmetic work? If representations are roughly sums of feature vectors, you should be able to recover a direction for a property you never isolated, just by solving a linear system on data where it's entangled with other properties.
- Can we predict the full N x N generalization table cheaply? Given N properties, can you avoid O(N^2) experiments and predict pairwise results from O(N) single-property probes, or even from descriptions of the properties alone?

## Experiment details

- Subject model: Qwen3-1.7B (Qwen/Qwen3-1.7B on Hugging Face).
- Use PyTorch for activations, probes, and steering vectors.
- Generate training data with Claude 4.5 Haiku (claude-haiku-4-5-20251001). You can use ~100 concurrent requests.
- Relevant packages have already been installed, also please use tooling.py for sampling from api models