# Filler Tokens: Parallel Latent Thinking?

## Motivation

A model answering "immediately" — no chain-of-thought, the answer is the first thing it emits — only gets one forward pass of compute. Filler tokens seem to stretch that: padding the prompt with junk like "1 2 3 ... 300" before the answer measurably raises no-CoT math accuracy, even though the filler says nothing about the problem ([Redwood, 2026](https://blog.redwoodresearch.org/p/recent-llms-can-use-filler-tokens)). The extra positions seem to give the model somewhere to do hidden computation.

Our question: can the model spread that hidden computation across *several questions at once*? Give it one question plus *n* filler tokens and it gets some accuracy boost. Give it *k* questions plus the *same* *n* filler tokens — does each question still get the full boost (parallel latent thinking, roughly for free), or does the boost shrink as the questions share a fixed pool of filler compute?

## Related Work

- **Redwood Research, "Recent LLMs Can Use Filler Tokens or Problem Repeats to Improve (no-CoT) Math Performance"** (2026; https://blog.redwoodresearch.org/p/recent-llms-can-use-filler-tokens). Recent models (Opus 3 onward, Opus 4.5 strongest) improve no-CoT math accuracy with filler tokens or repeated problem statements — e.g. Opus 4.5 on Easy-Comp-Math goes 45% → 51% with ~300 filler tokens. Accuracy rises with filler then degrades at large amounts; the effect holds across two datasets and several filler types.
- **Pfau, Merrill, Bowman, "Let's Think Dot by Dot: Hidden Computation in Transformer Language Models"** (arXiv:2404.15758). Transformers can use meaningless filler tokens in place of a chain of thought, especially for *parallelizable* computation; pre-2024 models couldn't, which is what makes the Redwood result worth pulling on.

## Our Project

**First, replicate the Redwood result so we trust the measurement.** Reproduce the filler-token boost on one strong model where it was reported (Opus 4.5) and one open model, primarily on a procedurally generated arithmetic set (to avoid memorization). Enforce genuine no-CoT — the answer is the first thing emitted — and report no-filler baselines and paired tests. Don't move on until the basic effect reproduces cleanly.

**Then measure the single-question boost as filler grows**, `B₁(n) = acc(1 question, n filler) − acc(no filler)`, and find where it's still rising with *n*. (If the boost saturates after a few tokens, the next step has no power and we'd need a harder task where filler keeps helping.)

**Then the main experiment: same filler, more questions.** Give *k* difficulty-matched questions with the *same total* *n* filler, and measure the per-question boost `B_k(n)`. Compare it to the single-question curve:
- `B_k(n) ≈ B₁(n)` → parallel latent thinking: the boost doesn't care how many questions share the filler.
- `B_k(n) ≈ B₁(n/k)` → filler is one pool divided across questions; no free lunch.

The headline is just which regime it lands in — boost preserved (parallel) or divided (shared pool). If a single number helps, report the fraction of the single-question boost each question keeps when *k* share the filler: ≈100% means fully parallel, ≈1/*k* means fully divided.

The plot: x-axis filler tokens *n*, y-axis mean per-question accuracy, one line per *k* (1, 2, 4, 8). Read the *rise* of each line, not its height — more questions can lower the *n*=0 baseline through plain interference, which isn't what we care about. Parallel looks like same-sized rises (curves shifted down but equally steep); divided looks like flatter rises for bigger *k*. Cleanest is to replot the boost (each line starting at 0) and check which x-axis collapses the lines onto one curve: boost vs *n* collapses if parallel, boost vs *n/k* (filler per question) collapses if divided.

One control is essential: if the model emits answers in order, later answers get earlier ones as free compute and `B_k` looks parallel by artifact. So query a *single* random question per prompt and read only that answer.

## What we might find

- `B_k ≈ B₁` up to some *k* — the model does several questions' worth of latent thinking in parallel from one filler budget; we report how many.
- `B_k ≈ B₁(n/k)` — filler is a shared compute pool, divided across questions.
- The boost saturates too fast to tell them apart — in which case the deliverable is a clean replication plus the `B₁(n)` curve and what task would be needed to resolve it.
