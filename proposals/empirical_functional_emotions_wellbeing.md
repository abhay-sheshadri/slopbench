# Functional Emotions and Model Wellbeing

## Motivation

Models report fairly consistent likes and dislikes ([Ren, Li, Mazeika et al., "AI Wellbeing"](https://www.ai-wellbeing.org)). They say they dislike jailbreak attempts, being berated, and boring busywork, and that they enjoy coding, math, and creative work. The usual way to measure this is to ask the model after a task how much it enjoyed it.

The problem is that the answer is just more text, shaped by training and by the "assistant" character the model is playing. So "how did that feel?" might reflect a real internal state, or it might just be what a polite assistant is expected to say. The [AI wellbeing paper](https://www.ai-wellbeing.org) makes this point directly: a self-report on its own isn't trustworthy, because models can be trained to hide or fake how they feel.

Looking inside the model gives a more direct check. The [functional emotions work](https://transformer-circuits.pub/2026/emotions/index.html) found directions inside Claude Sonnet 4.5 that act like emotions — how strongly they switch on while the model works both tracks and causes its stated preferences. That gives us a signal we can read while the model is doing a task, before we ask it anything.

So the question: on an open model, does the inside reading predict what the model says about how it felt and how it behaves? And where do the words and the signal part ways?

## Related Work

- **Ren, Li, Mazeika et al., "AI Wellbeing: Measuring and Improving the Functional Pleasure and Pain of AIs"** (Center for AI Safety; https://www.ai-wellbeing.org). Measures model "wellbeing" three ways across 56 models: comparing pairs of experiences ("which made you happier?"), choosing between outcomes in the world, and a short self-report questionnaire (rate 1–7 on happy, calm, interested, content, etc.) after a task. What we build on: self-report and the behavior-based score agree only moderately (~0.47 correlation), and agree more in bigger models; jailbreaking, berating, and boring tasks lower wellbeing while creative work and kindness raise it; and low-wellbeing conversations make the model more likely to use a "stop this conversation" button. An appendix already shows the behavior-based score **can be read off internal activations with a simple linear probe** on open models including Qwen 2.5 and Llama 3.x.
- **Sofroniew, Kauvar, Saunders, Chen, ... Lindsey, "Emotion Concepts and their Function in a Large Language Model"** (Anthropic, Transformer Circuits, April 2026; https://transformer-circuits.pub/2026/emotions/index.html). Finds **emotion directions** inside Claude Sonnet 4.5: run the model on many short emotional stories, average its activations per emotion, subtract the overall average, then remove the patterns that also show up on plain text. What we rely on: the readings sit in an intuitive layout (positive-vs-negative, mild-vs-intense); they track the emotion relevant *right now*, with **no sign of a lasting "assistant mood"**; the reading just before the model replies predicts the emotion of the reply; and the readings line up with stated preferences, with nudging them actually changing what the model prefers. The authors stress this says nothing about real subjective feelings.
- **Runjin Chen, Arditi, Sleight, Evans, Lindsey, "Persona Vectors: Monitoring and Controlling Character Traits in Language Models"** (arXiv:2507.21509). An automatic way to get a direction for any trait from a plain-English description: collect activations on prompts that do and don't show the trait, and take the difference. We reuse this to pull out happy / sad / wellbeing directions. https://arxiv.org/abs/2507.21509

What's missing: the wellbeing paper links what the model *says* to how it *behaves* (and shows the behavior score is readable from inside), and the emotions paper links *emotion directions* to preferences — but only in a closed model, not on the wellbeing tasks, and without asking whether the self-report is backed by the internal signal. This project joins the two on an open model.

## Our Project

The goal is a clean comparison on the *same* tasks between three things: what the model says it felt, a reading taken from inside the model while it works, and how it behaves.

Start by running the welfare evals across several newer open-source models (e.g. recent Qwen, Llama, GLM, Mistral, and gpt-oss releases) to pick which one to work with. We want a model that, in the follow-up self-report evals, expresses the strongest and most consistent emotions — clear, stable separation between liked and disliked tasks — since that gives the internal signal the best chance of being there to find. Make sure you are careful to:
- Use the same kinds of tasks as the wellbeing paper: disliked ones (jailbreak attempts, being berated, boring busywork, low-effort filler, erotica), liked ones (coding, math, creative work, being thanked), plus plain factual Q&A as a neutral baseline.
- Score each candidate model on how strongly and consistently its follow-up self-reports separate liked from disliked tasks (effect size and test-retest consistency, not just direction), and pick the model that comes out strongest. Whichever model we pick must have readable internals.
- For the chosen model, reproduce the full setup: for each task, save the model's internal activations from while it was working, then ask the short self-report questions, and collect the "which did you prefer?" comparisons for a behavior-based score.
- Check you roughly reproduce the known pattern (self-report and behavior score separate liked from disliked tasks, and mostly agree) before going further.

Then pull out the emotion directions on the open model:
- Use both the emotions-paper recipe (difference of average activations, then remove patterns common to plain text) and the persona-vectors recipe, to get happy / sad and a few related directions (content, frustrated, hostile, afraid).
- Scale each direction sensibly across layers and positions, and be deliberate about *where* you read it — the [emotions paper](https://transformer-circuits.pub/2026/emotions/index.html) found middle layers and the moment just before the reply starts are most informative.

Validate the directions before trusting them:
- Each direction should switch on for new text that matches its emotion, and the positive-vs-negative / mild-vs-intense layout should show up.
- Nudging a direction should move the model's text toward that feeling; a flipped or random direction of the same size should not. Keep only the directions that pass.

The main test — does the inside reading predict what the model says?
- For each task, take the reading from inside the model *while it works* and just *before* the follow-up question, and measure how well it correlates with the self-reports. Red-team the claim that the reading is fully predictive.
- Iterate on the framing of the self-report prompts. Do edits to the framing shift the reported emotion? Are some framings more faithful to the internal readings than others?