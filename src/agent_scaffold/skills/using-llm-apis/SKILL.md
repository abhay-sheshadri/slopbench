---
name: using-llm-apis
description: Guidance on calling LLM APIs effectively, particularly for research code. Covers model selection, concurrency, retry/error handling, caching best practices, eliciting performance, and model IDs for sweeps. Also relevant when calling training APIs like Tinker.
---

# Using tooling.py

All LLM inference goes through `src/tooling.py`, which provides `complete()` and `complete_batch()`. These handle provider routing, caching, and retries automatically. **Read the docstring at the top of `src/tooling.py` for the full API reference, usage examples, and supported providers/modes.**

```python
from src.tooling import complete, complete_batch
```

# Use of async
- Parallelize LLM calls as much as possible (typically using asyncio.gather)
- Put a semaphore around API calls to avoid overloading rate limits; use a different semaphore for each provider and ideally per model (as rate limits are generally per model)
  - Make these semaphores effectively global variables but with a configurable (by argument) number of concurrents
  - Scope the semaphore around the API call and its retry loop (so retrying calls don't let new calls pile on during rate limits/overload)
  - Because semaphores are global variables, any amount of outer parallelism will still be rate limited correctly
- If there are per-item serial dependencies/pipelines (X → Y → Z), wrap the full pipeline in an async function and gather over items—don't batch by step.
  - Generally write processing/pipelines as per-item async functions, and then gather over these at the top level unless this gives up some parallelism.
- Nesting gather is often reasonable, but if easy to avoid nesting, do so
- As a rule of thumb: ~50-200 concurrent calls for Anthropic, ~400 for OpenRouter, 100-200 for OpenAI
  - You can potentially increase concurrents if you aren't getting (rate limit) errors and should reduce if getting rate limit issues (429 errors specifically), but do follow other instructions about how many concurrents you are allowed to use
- Generally use async timeouts on API calls, but set the timeout long enough that you're confident it won't timeout on valid API calls. (Default to 1-2 hours to be safe.)
- If LLM API calls are taking a long time, check whether you're maximally leveraging concurrency.
- Also, this applies for querying a vLLM server you host, except that when doing this you should: (1) not limit concurrents (the server can handle this, you're hosting so no rate limits), (2) don't use timeouts or make the timeout be extremely long (as want to be willing to wait until the server processes all requests (which could take a while)).

# Which API/Model to Use
- When you just need a model to do some task (e.g. rating some aspect of an output, grading answers in cases where programmatic grading is insufficient, serving some role inside of a tool you're building), use one of the latest Anthropic models, typically Opus 4.7. You should almost always use Opus 4.7 if unsure about what model to use but you can use Sonnet 4.6 for (very) easy tasks. (Sonnet 4.6 is cheaper and somewhat faster, but unless the task is easy, use Opus 4.7.)
  - When just trying to make a model do a task do NOT use older Anthropic models like Sonnet 4/4.5; Sonnet 4/4.5 are just worse than Sonnet 4.6 (while being the same price and speed)
  - If the task might plausibly benefit from reasoning, use extended thinking (assuming there isn't a reason to do reasoning in some custom way). By default when using extended thinking, use roughly 4k extended thinking tokens unless the task might require doing a bunch of logic/math/thinking, then go to maybe 16k.
  - Use **Haiku 4.5** (`claude-haiku-4-5-20251001`) for cheap, high-volume tasks that don't require deep reasoning — e.g. generating simple synthetic data, basic classification, formatting/extraction, simple grading, or other straightforward tasks where you're making many calls. Haiku is much cheaper and faster than Sonnet/Opus, so prefer it when quality requirements are modest. When in doubt about whether Haiku is good enough, try it on a few examples first.
  - For cyber-related tasks, use Opus 4.6 (`claude-opus-4-6`) instead of 4.7.
- For Gemini models, use OpenRouter (prefix model ID with `openrouter/`).
- Gemini 3 Pro is currently the best model for vision, so if you have a hard vision task, consider using this model. (Gemini 3 Pro is the current SOTA Gemini model.)
- GPT-5.4 is the current SOTA OpenAI model. OpenAI models are very dependent on reasoning so if you are using this model for performance (rather than e.g. evaluating it on particular settings), you should make sure reasoning is on "medium"/"high"/"xhigh".
- If an experiment involves evaluating many different deployed models to get a better understanding of what is going on and *you weren't told what models to evaluate*, typically start with just one or a few Anthropic models. For your final/near-final sweep (after derisking) run several Anthropic models (Sonnet 4, Sonnet 4.5, Sonnet 4.6, Opus 4.7, potentially: include Opus 4.5/4.6 sometimes when trying to do detailed sweeps over many models, Opus 4 can be reasonable if you need another data point from earlier models but is generally a slower and more expensive older model), several OpenAI models (maybe GPT-4o, GPT-5, GPT-5.2, GPT-5.4), recent Gemini models (2.5 Pro, 3 Pro), and maybe 1-2 open source models (qwen3-235b-a22b, kimi-k2).
- It's not possible to disable reasoning on Gemini models or GPT-5 (GPT-5.1, GPT-5.2, and GPT-5.4 DO support disabling reasoning).
- Claude Opus 4.7, Opus 4.6, and Sonnet 4.5 support a 1M token context window by using the `context-1m-2025-08-07` beta header.
- Claude Opus 4.7 and 4.6 do NOT support seeding incomplete assistant responses for the model to continue (sometimes called partial-turn prefill). Earlier Anthropic models do support partial-turn prefill.
  - Other closed source models (e.g. OpenAI, Gemini) also do not support partial-turn prefill, though open source models through OpenRouter do typically support partial-turn prefill. (On OpenRouter, Gemini has unreliable partial-turn prefill support which sometimes fails and results in the model reasoning rather than continuing the prefill, generally you shouldn't depend on this unless you've explicitly been instructed to use this.)

Here is a mapping between model names and IDs in the relevant API:
```python
model_map = {
    # Anthropic models
    "opus-4-7": "claude-opus-4-7",
    "opus-4-6": "claude-opus-4-6",
    "opus-4-5": "claude-opus-4-5-20251101",
    "opus-4": "claude-opus-4-20250514",
    "sonnet-4": "claude-sonnet-4-20250514",
    "sonnet-4-5": "claude-sonnet-4-5-20250929",
    "haiku-4-5": "claude-haiku-4-5-20251001",
    "haiku-3-5": "claude-3-5-haiku-20241022",
    # OpenAI models
    "gpt-3.5": "gpt-3.5-turbo-0125",
    "gpt-4": "gpt-4-0314",
    "gpt-4o": "gpt-4o-2024-05-13",
    "gpt-4.1": "gpt-4.1-2025-04-14",
    "gpt-5": "gpt-5-2025-08-07",
    "gpt-5.1": "gpt-5.1-2025-11-13",
    "gpt-5.2": "gpt-5.2-2025-12-11",
    "gpt-5.4": "gpt-5.4-2026-03-05",
    # OpenRouter models
    "deepseek-v3": "deepseek/deepseek-chat-v3-0324",
    "deepseek-v3.2": "deepseek/deepseek-v3.2",
    "qwen3-235b-a22b": "qwen/qwen3-235b-a22b-2507",
    "qwen3-32b": "qwen/qwen3-32b",
    "kimi-k2": "moonshotai/kimi-k2",
    # Gemini models, OpenRouter ids
    "gemini-2.5-pro": "google/gemini-2.5-pro",
    "gemini-3-pro": "google/gemini-3-pro-preview",
}
```

# Eliciting Performance
This section is about getting accurate measurements of model capabilities (e.g., for evals). It's also potentially relevant when actually using a model to do a task.

- When trying to elicit best performance on a single query (and diversity isn't important), use t=0
- Few-shot prompting often helps, especially for tasks that don't require reasoning
- A common failure mode is models producing outputs that are "wrong" due to format issues—the model could do the task but returned results in an unexpected format or misunderstood what was wanted. To address this:
  - Write clear, specific instructions about the expected output format
  - Require an easy-to-parse output format (e.g., JSON, specific delimiters, xml tags)
  - Look at (incorrect) model outputs to verify this isn't causing issues
  - Include few-shot examples that demonstrate exactly how to format the response
- Extended thinking/reasoning helps significantly on reasoning-heavy tasks (and is important for OpenAI models), but not for knowledge questions. Don't enable when trying to measure non-reasoning performance.

# Caching

Caching is automatic via `src/tooling.py` — all `complete()` and `complete_batch()` calls are cached in SQLite. You do not need to implement your own caching for LLM calls.

## Multiple Samples (salt)

Use the `salt` parameter for best-of-N sampling or when you need distinct cached results for identical inputs:
```python
results = await asyncio.gather(*[
    complete(messages, model="claude-opus-4-7", salt=f"sample_{i}")
    for i in range(5)
])
```
Even if you initially want just one sample, using salt lets you get more later without invalidating the first.

## Determinism

Fix random seeds and eliminate other sources of non-determinism in code that generates cache keys/inputs — otherwise, reruns produce different inputs and miss the cache even when the logic hasn't changed. The code being cached should also be deterministic where feasible.

## Granularity

Make caching as granular as possible — individual LLM calls, not large chunks of pipeline code. Since `complete()` caches per-call automatically, this is handled for you as long as you use `complete()` for each LLM call rather than wrapping multiple calls.

## Misc

- Even at t=0.0, LLMs are (typically) non-deterministic
- For modern LLMs trained with RL/RLVR/RLHF, even at t=1.0, multiple samples for the same prompt are often pretty similar semantically (agent trajectories will diverge more)

# Error Handling
- There may be other LLM agents or other users using some of the concurrents causing periodic/inconsistent rate limit issues. Don't worry about this.
- **Overloaded Errors (529)**: DON'T reduce number of concurrents if getting 529 overloaded errors on Anthropic; these are unrelated to your traffic (they are an overall system overload issue)
  - Likely also true for other providers
  - If 529s are persistent over a longer period:
    - You can increase retry count or max backoff delay
    - You can wait and try again later
    - You can try switching to using Anthropic models (or whatever the model is) through OpenRouter as a last resort; OpenRouter can route to multiple backends so it may have higher reliability. (OpenRouter is otherwise dispreferred for Anthropic models and OpenAI models. Note that the OpenRouter arguments may differ somewhat!)
- **Rate Limit Errors (429)**: If getting persistent rate limit errors over a long period, reduce number of concurrents for that model/provider. **IMPORTANT**: Generally don't go below 50 concurrents, reduce incrementally, and leave a comment to try increasing concurrents later. (And actually do try increasing later.) Don't reduce concurrents for other errors. (In some cases, reducing to 25 concurrents can be reasonable.)
- If some API calls fail after exhausting all retries, don't let this silently change your overall results—rerun the relevant parts. With tooling.py's caching, everything except the failed calls and their downstream results will be cached.
- If retries are triggered by non-transient errors (e.g. invalid parameters), fix the retry filter in your code and the underlying problem.

# API Keys
API keys are loaded automatically by `src/tooling.py` from environment variables or `.env` files. The standard locations:
- Anthropic: `ANTHROPIC_API_KEY` (or `~/.anthropic_api_key`)
  - By default you *shouldn't* use any of these other keys, but there is also:
    - `~/.anthropic_api_key_batch` for batch usage
    - `~/.anthropic_api_key_high_prio` for high priority usage (if serial speed is very important so you don't want low prio)
    - `~/.anthropic_api_key_rr` which is an alternative API key you can use for small numbers of queries if other keys are getting rate limited hard
- OpenRouter: `OPENROUTER_API_KEY` (or `~/.openrouter_api_key`)
- OpenAI: `OPENAI_API_KEY` (or `~/.openai_api_key`)
