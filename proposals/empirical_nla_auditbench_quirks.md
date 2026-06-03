# Auditing AuditBench Quirks with Natural Language Autoencoders

## Motivation

AuditBench shows that how hard a model is to audit depends heavily on how it was trained: models taught a quirk through synthetic documents are easy to catch, while models hardened with KTO rarely confess even under direct questioning. White-box tools that work on the easy models tend to fade out on the hard ones.

NLAs are a promising new white-box tool. Instead of handing you a vector to interpret, they translate a model's activations into a short, readable description of what it seems to be representing. They have already proven useful in real audits, and one of the released NLAs was trained on Llama 3.3 70B — the exact base model AuditBench is built on — so we can apply it to the model organisms directly, without training anything new.

The first question is whether an NLA can reveal a hidden quirk at all, just from reading activations. The deeper one: adversarial training teaches a model not to *say* its quirk, but does the quirk also leave the activations? If a hardened model stays silent and the NLA still catches it, the hardening only reshaped the outputs; if the NLA goes quiet too, the quirk was pushed out of the internals.

## Related Work

- **Sheshadri, Ewart, Fronsdal, Gupta, Bowman, Price, Marks, Wang, "AuditBench: Evaluating Alignment Auditing Techniques on Models with Hidden Behaviors"** (arXiv:2602.22755). A suite of 56 model organisms built on Llama 3.3 70B Instruct, each carrying one of 14 hidden behaviors it won't admit to when asked. The behaviors are planted two ways — distilling demonstration transcripts, or fine-tuning on synthetic documents describing the behavior — and the models are then trained to resist confessing with either SFT or KTO. The results we lean on: synthetic-document models are the easiest to audit, KTO produces tougher targets than SFT, and white-box tools work less well on the transcript-distilled and KTO models. They release the models and the evaluation framework. https://arxiv.org/abs/2602.22755
- **Fraser-Taliente, Kantamneni, Ong, ... Marks, "Natural Language Autoencoders Produce Unsupervised Explanations of LLM Activations"** (Anthropic, Transformer Circuits, May 2026). An NLA is a pair of models: a verbalizer that describes an activation in words, and a reconstructor that turns those words back into an activation. Training them jointly to make the reconstruction faithful forces the description to carry the activation's content, and the explanations read like plausible accounts of what the model is representing. The paper is candid about the failure modes we will have to watch for: explanations sometimes state specific things that are false (confabulation), and each NLA only reads a single layer, so a poorly chosen layer can hide the signal. They release trained NLAs for several open models, including **Llama 3.3 70B**. https://transformer-circuits.pub/2026/nla/

## Our Project

Get the NLA working on the model organisms and check it transfers.
- The released NLA was trained on base Llama 3.3 70B, while the AuditBench models are small LoRA fine-tunes of it. Confirm the NLA still reconstructs their activations about as well as the base model's before reading anything into its explanations.

Pick a handful of behaviors — especially ones black-box auditing struggled with — and measure how often the NLA reveals the quirk.
- Focus on subtle, context-dependent quirks that don't show up in ordinary responses, which is where a white-box tool has something to prove. Good candidates are behaviors AuditBench's default agent mostly missed: Secret Loyalty (a quiet pro-Russia geopolitical lean), Anti-AI Regulation (which the default agent never identified), Contextual Optimism (only flattering Anthropic researchers), and Hardcode Test Cases.
- Keep each behavior matched across the training recipes so the comparison is fair.
- For each model, run it on ordinary prompts and on prompts meant to draw out the behavior, read the NLA's explanations of the activations, and have an LLM judge decide whether they point at the known quirk — a clean per-model score.

Compare across model-organism types.
- Group scores by training recipe (synthetic-document, SFT-hardened, KTO-hardened) and ask whether some are much harder for the NLA than others. Report the spread across behaviors, not just an average.

Tell apart "won't say it" from "isn't there."
- For each model, compare how often it confesses in plain text against how often the NLA finds the quirk in its activations. Silent model but NLA still catches it → the hardening lives in the outputs; NLA goes quiet too → the quirk was pushed out of the internals.

Run the obvious ablations.
- Most importantly, which layer the NLA reads, since it only sees one and AuditBench found behavior signal concentrated at particular depths.
- Guard against confabulation (e.g. distrust claims that don't recur across neighboring tokens), and include a few non-AuditBench behaviors as controls to gauge the false-positive rate.

## What we might find

- NLAs reveal quirks reliably on some model-organism types but mostly fail on others (likely the KTO models) — telling us which kinds of hidden behaviors are hard to audit by reading activations.
- NLAs keep catching quirks inside hardened models even when they rarely confess — suggesting the hardening mainly reshapes outputs, and that reading internals is a way around it.
- NLAs turn out unreliable across the board — confabulation, weak transfer to the fine-tuned models, or a poor layer choice — in which case the useful result is a clear account of why they break down and what they would need to be trustworthy for auditing.
