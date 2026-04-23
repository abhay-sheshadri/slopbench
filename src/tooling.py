"""Minimal LLM inference with SQLite caching.

Supports Anthropic, OpenAI, OpenRouter, and Tinker models with a unified
async interface. All results are cached in a SQLite WAL-mode database.

Providers & model routing:
    - Anthropic:    "claude-sonnet-4-6", "claude-opus-4-7", etc.
    - OpenAI:       "gpt-5.4", "gpt-5.4-mini", etc.
    - OpenRouter:   "openrouter/<model-id>" (any model on OpenRouter)
    - Tinker:       "tinker/<model>" or "tinker://<checkpoint>" (base model sampling)
    - vLLM:         "vllm/<model>" (local/remote vLLM server, base model sampling)

    Reasoning effort can be appended with a colon, e.g. "gpt-5.4:medium".
    Unknown model IDs fall back to Anthropic.

There are two modes of calling complete():

    1. Chat completion (list of message dicts) — for all providers:
       text = await complete([
           {"role": "user", "content": "What is 2+2?"},
       ], model="claude-sonnet-4-6")

    2. Base model text completion (raw string) — tinker/vllm/together only:
       text = await complete("Once upon a time", model="tinker://path/to/checkpoint")

    String prompts to chat providers (Anthropic, OpenAI, OpenRouter) will raise
    a TypeError. Always use message dicts for chat models.

Usage:
    from src.tooling import complete, complete_batch

    # Chat completion — always pass a list of message dicts:
    text = await complete([
        {"role": "user", "content": "Say hello"},
    ], model="claude-sonnet-4-6")

    # Multi-turn:
    text = await complete([
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "Now multiply that by 3."},
    ], model="claude-sonnet-4-6")

    # Prefills — end with an assistant message to continue from a prefix:
    text = await complete([
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "The answer is"},
    ], model="claude-sonnet-4-6")
    # → " 4."

    # Reasoning/thinking traces — always captured and cached. Use
    # include_reasoning=True to prepend them as <think>...</think>:
    text = await complete([
        {"role": "user", "content": "Hard problem"},
    ], model="claude-sonnet-4-6",
       extra_body={"output_config": {"effort": "high"}},
       include_reasoning=True)
    # → "<think>\n..reasoning..\n</think>\n\nThe answer is..."
    # By default (include_reasoning=False), <think> blocks are stripped.

    # Base model sampling — string prompt, tinker/vllm/together only:
    text = await complete("Once upon a time", model="tinker://path/to/checkpoint")
    text = await complete("Once upon a time", model="vllm/meta-llama/Llama-3-8B")

    # Batch completion (Anthropic + OpenAI — ~50% cost savings):
    texts = await complete_batch([
        [{"role": "user", "content": "Say 1"}],
        [{"role": "user", "content": "Say 2"}],
    ], model="claude-sonnet-4-6")  # or model="gpt-5.4"

    # Caching is on by default; disable per-call with use_cache=False:
    text = await complete([{"role": "user", "content": "Say hello"}], use_cache=False)
"""

import asyncio
import atexit
import hashlib
import json
import os
import re
import signal
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import anthropic
import openai
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Types ────────────────────────────────────────────────────────────


@dataclass
class LLMResponse:
    """Full response from an LLM call, including optional reasoning trace.

    Attributes:
        text: The completion text (always present).
        thinking: Reasoning/thinking trace from the model, if available.
            Populated for Anthropic extended thinking, OpenAI reasoning
            summaries (Responses API), and OpenRouter reasoning models.
    """

    text: str
    thinking: str | None = None


_THINK_TAG_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from model output."""
    return _THINK_TAG_RE.sub("", text).lstrip()


def _format_output(
    result: LLMResponse, include_reasoning: bool, is_base_completion: bool
) -> str:
    """Format an LLMResponse into the final output string.

    Args:
        result: The raw LLMResponse from the provider or cache.
        include_reasoning: Whether to prepend cached thinking as <think> tags.
        is_base_completion: True when using a text completions endpoint (base
            model sampling via tinker/vllm/together with a string prompt).
            Base completion output is returned as-is — never stripped or wrapped.
    """
    if is_base_completion:
        return result.text
    if include_reasoning and result.thinking:
        return f"<think>\n{result.thinking}\n</think>\n\n{result.text}"
    return _strip_think_tags(result.text)


# ── Config ───────────────────────────────────────────────────────────

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache_sqlite"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DB = CACHE_DIR / "llm_cache.db"

DEFAULT_MAX_RETRIES = 10
DEFAULT_POLL_INTERVAL = 10
BATCH_CHUNK_SIZE = 5000
DEFAULT_MAX_CONCURRENT_BATCHES = 10


# ── Provider registry ────────────────────────────────────────────────


def _make_anthropic_client():
    return anthropic.AsyncAnthropic()


def _make_anthropic_sync_client():
    return anthropic.Anthropic()


def _make_openai_client():
    return openai.AsyncOpenAI()


def _make_openrouter_client():
    return openai.AsyncOpenAI(
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )


def _make_tinker_client():
    return openai.AsyncOpenAI(
        api_key=os.environ.get("TINKER_API_KEY"),
        base_url="https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1",
    )


def _make_vllm_client():
    return openai.AsyncOpenAI(
        api_key=os.environ.get("VLLM_API_KEY", "EMPTY"),
        base_url=os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1"),
    )


def _make_together_client():
    return openai.AsyncOpenAI(
        api_key=os.environ.get("TOGETHER_API_KEY"),
        base_url="https://api.together.xyz/v1",
    )


_ANTHROPIC_NO_TEMPERATURE = {"claude-opus-4-7"}

PROVIDERS = {
    "anthropic": {
        "models": {
            "claude-sonnet-4-6",
            "claude-sonnet-4-5-20250929",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-7",
            "claude-opus-4-6",
            "claude-opus-4-1-20250805",
        },
        "concurrency": 50,
        "call": "_call_anthropic",
        "client_factory": _make_anthropic_client,
    },
    "openai": {
        "models": {
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-5-nano",
            "gpt-5-mini",
            "gpt-5",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
            "gpt-5.4-pro",
            "gpt-4o",
            "gpt-4o-mini",
        },
        "concurrency": 50,
        "call": "_call_openai_responses",
        "client_factory": _make_openai_client,
    },
    "openrouter": {
        "models": set(),  # matched by "openrouter/" prefix
        "prefix": "openrouter/",
        "concurrency": 50,
        "call": "_call_openai",
        "client_factory": _make_openrouter_client,
    },
    "tinker": {
        "models": set(),  # matched by "tinker/" prefix or "tinker://" checkpoint paths
        "prefix": "tinker/",
        "concurrency": 50,
        "call": "_call_openai_text",
        "client_factory": _make_tinker_client,
    },
    "vllm": {
        "models": set(),  # matched by "vllm/" prefix
        "prefix": "vllm/",
        "concurrency": 50,
        "call": "_call_openai_text",
        "client_factory": _make_vllm_client,
    },
    "together": {
        "models": set(),  # matched by "together/" prefix
        "prefix": "together/",
        "concurrency": 50,
        "call": "_call_openai_text",
        "client_factory": _make_together_client,
    },
}


ANTHROPIC_MODELS = PROVIDERS["anthropic"]["models"]
OPENAI_MODELS = PROVIDERS["openai"]["models"]


def resolve_model(model_id: str) -> tuple[str, str, dict]:
    """Parse model ID into (api_model_id, provider_name, extra_kwargs)."""
    extra = {}

    # Tinker checkpoint paths (tinker://...) are passed as-is to the API
    if model_id.startswith("tinker://"):
        return model_id, "tinker", extra

    # Strip reasoning effort suffix (e.g. "gpt-5:medium")
    if ":" in model_id:
        model_id, effort = model_id.rsplit(":", 1)
        extra["reasoning_effort"] = effort

    # Check prefix-based providers first (e.g. "openrouter/...", "tinker/...")
    for name, cfg in PROVIDERS.items():
        prefix = cfg.get("prefix")
        if prefix and model_id.startswith(prefix):
            return model_id[len(prefix) :], name, extra

    # Check model sets
    for name, cfg in PROVIDERS.items():
        if model_id in cfg["models"]:
            return model_id, name, extra

    # Default to anthropic
    return model_id, "anthropic", extra


# ── Clients (lazy singletons) ───────────────────────────────────────

_clients: dict[str, object] = {}


def _get_client(provider: str):
    if provider not in _clients:
        cfg = PROVIDERS[provider]
        _clients[provider] = cfg["client_factory"]()
    return _clients[provider]


# Separate sync client for batch API
_anthropic_sync: anthropic.Anthropic | None = None


def _get_anthropic_sync() -> anthropic.Anthropic:
    global _anthropic_sync
    if _anthropic_sync is None:
        _anthropic_sync = _make_anthropic_sync_client()
    return _anthropic_sync


# ── Semaphores ──────────────────────────────────────────────────────

_semaphores: dict[str, asyncio.Semaphore] = {}


def _get_semaphore(provider: str) -> asyncio.Semaphore:
    if provider not in _semaphores:
        limit = PROVIDERS.get(provider, {}).get("concurrency", 50)
        _semaphores[provider] = asyncio.Semaphore(limit)
    return _semaphores[provider]


# ── Cache ────────────────────────────────────────────────────────────


def _init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(CACHE_DB), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            completion TEXT NOT NULL,
            model TEXT,
            created_at REAL
        )"""
    )
    conn.commit()
    return conn


_db = _init_db()


def _cache_key(
    model: str,
    messages: list[dict],
    temperature: float | None,
    max_tokens: int,
    **kwargs,
) -> str:
    blob = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _serialize_response(resp: LLMResponse) -> str:
    """Serialize an LLMResponse to a JSON string for caching."""
    return json.dumps({"text": resp.text, "thinking": resp.thinking})


def _deserialize_response(raw: str) -> LLMResponse:
    """Deserialize a cached string back to LLMResponse."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "text" in data:
            return LLMResponse(text=data["text"], thinking=data.get("thinking"))
    except (json.JSONDecodeError, TypeError):
        pass
    # Legacy plain-string cache entry
    return LLMResponse(text=raw)


def cache_get(key: str) -> LLMResponse | None:
    row = _db.execute("SELECT completion FROM cache WHERE key = ?", (key,)).fetchone()
    return _deserialize_response(row[0]) if row else None


def cache_put(key: str, response: LLMResponse, model: str):
    _db.execute(
        "INSERT OR REPLACE INTO cache (key, completion, model, created_at) VALUES (?, ?, ?, ?)",
        (key, _serialize_response(response), model, time.time()),
    )
    _db.commit()


def cache_put_many(entries: list[tuple[str, LLMResponse, str]]):
    _db.executemany(
        "INSERT OR REPLACE INTO cache (key, completion, model, created_at) VALUES (?, ?, ?, ?)",
        [(k, _serialize_response(r), m, time.time()) for k, r, m in entries],
    )
    _db.commit()


def cache_get_many(keys: list[str]) -> dict[str, LLMResponse]:
    if not keys:
        return {}
    results = {}
    for i in range(0, len(keys), 500):
        chunk = keys[i : i + 500]
        placeholders = ",".join("?" * len(chunk))
        rows = _db.execute(
            f"SELECT key, completion FROM cache WHERE key IN ({placeholders})", chunk
        ).fetchall()
        for k, v in rows:
            results[k] = _deserialize_response(v)
    return results


# ── Provider call functions ──────────────────────────────────────────


async def _call_anthropic(
    model: str,
    messages: list[dict],
    temperature: float | None,
    max_tokens: int,
    client,
    raw_prompt: str | None = None,
    **kwargs,
) -> LLMResponse:
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    chat_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m["role"] != "system"
    ]

    api_kwargs = {}
    if system_parts:
        api_kwargs["system"] = "\n\n".join(system_parts)
    if "thinking" in kwargs:
        api_kwargs["thinking"] = kwargs["thinking"]
    if "extra_body" in kwargs:
        api_kwargs["extra_body"] = kwargs["extra_body"]
    if temperature is not None and model not in _ANTHROPIC_NO_TEMPERATURE:
        api_kwargs["temperature"] = temperature

    resp = await client.messages.create(
        model=model,
        messages=chat_messages,
        max_tokens=max_tokens,
        **api_kwargs,
    )
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    thinking = "".join(b.thinking for b in resp.content if b.type == "thinking") or None
    return LLMResponse(text=text, thinking=thinking)


def _raise_empty() -> None:
    import httpx

    raise openai.APIError(
        "Empty response (no choices)", request=httpx.Request("POST", ""), body=None
    )


async def _call_openai(
    model: str,
    messages: list[dict],
    temperature: float | None,
    max_tokens: int,
    client,
    raw_prompt: str | None = None,
    **kwargs,
) -> LLMResponse:
    api_kwargs = {}
    if "reasoning_effort" in kwargs:
        api_kwargs["reasoning_effort"] = kwargs["reasoning_effort"]
    if "extra_body" in kwargs:
        api_kwargs["extra_body"] = kwargs["extra_body"]
    if temperature is not None:
        api_kwargs["temperature"] = temperature

    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=max_tokens,
        **api_kwargs,
    )
    if not resp.choices or not resp.choices[0].message.content:
        _raise_empty()
    text = resp.choices[0].message.content
    # OpenRouter returns reasoning in model_extra (not a named attribute)
    thinking = None
    extra = getattr(resp.choices[0].message, "model_extra", None) or {}
    if extra.get("reasoning"):
        thinking = extra["reasoning"]
    return LLMResponse(text=text, thinking=thinking)


async def _call_openai_responses(
    model: str,
    messages: list[dict],
    temperature: float | None,
    max_tokens: int,
    client,
    raw_prompt: str | None = None,
    **kwargs,
) -> LLMResponse:
    """OpenAI Responses API — supports reasoning summaries."""
    input_items = []
    for msg in messages:
        if msg["role"] == "system":
            input_items.append({"role": "developer", "content": msg["content"]})
        else:
            input_items.append({"role": msg["role"], "content": msg["content"]})

    api_kwargs: dict = {}
    if max_tokens:
        api_kwargs["max_output_tokens"] = max_tokens

    # Build reasoning config — temperature is not supported alongside reasoning
    reasoning_effort = kwargs.get("reasoning_effort")
    if reasoning_effort:
        api_kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
    elif temperature is not None:
        api_kwargs["temperature"] = temperature
    if "extra_body" in kwargs:
        api_kwargs["extra_body"] = kwargs["extra_body"]

    resp = await client.responses.create(
        model=model,
        input=input_items,
        **api_kwargs,
    )

    # Extract text and reasoning summary from output items
    text_parts = []
    thinking_parts = []
    has_reasoning = False
    for item in resp.output:
        if item.type == "reasoning":
            has_reasoning = True
            for s in getattr(item, "summary", None) or []:
                if hasattr(s, "text"):
                    thinking_parts.append(s.text)
        elif item.type == "message":
            for c in item.content or []:
                if hasattr(c, "text"):
                    text_parts.append(c.text)

    text = "".join(text_parts)
    # Mark reasoning as present even when summary is empty (trivial prompts)
    thinking = (
        "\n".join(thinking_parts)
        if thinking_parts
        else ("(reasoning)" if has_reasoning else None)
    )
    if not text:
        _raise_empty()
    return LLMResponse(text=text, thinking=thinking)


async def _call_openai_text(
    model: str,
    messages: list[dict],
    temperature: float | None,
    max_tokens: int,
    client,
    raw_prompt: str | None = None,
    **kwargs,
) -> LLMResponse:
    """OpenAI-compatible text completion (not chat).

    When raw_prompt is provided, uses /completions for base-model sampling.
    Falls back to /chat/completions for message-list calls.
    """
    if raw_prompt is not None:
        api_kwargs = {"max_tokens": max_tokens}
        if temperature is not None:
            api_kwargs["temperature"] = temperature
        if "extra_body" in kwargs:
            api_kwargs["extra_body"] = kwargs["extra_body"]
        resp = await client.completions.create(
            model=model,
            prompt=raw_prompt,
            **api_kwargs,
        )
        if not resp.choices or not resp.choices[0].text:
            _raise_empty()
        return LLMResponse(text=resp.choices[0].text)

    # Fall back to chat completions for message lists
    api_kwargs = {"max_completion_tokens": max_tokens}
    if temperature is not None:
        api_kwargs["temperature"] = temperature
    if "extra_body" in kwargs:
        api_kwargs["extra_body"] = kwargs["extra_body"]
    if "reasoning_effort" in kwargs:
        api_kwargs["reasoning_effort"] = kwargs["reasoning_effort"]
    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        **api_kwargs,
    )
    if not resp.choices or not resp.choices[0].message.content:
        _raise_empty()
    return LLMResponse(text=resp.choices[0].message.content)


# Wire up direct function references (PROVIDERS is defined before functions)
PROVIDERS["anthropic"]["call"] = _call_anthropic
PROVIDERS["openai"]["call"] = _call_openai_responses
PROVIDERS["openrouter"]["call"] = _call_openai
PROVIDERS["tinker"]["call"] = _call_openai_text
PROVIDERS["vllm"]["call"] = _call_openai_text
PROVIDERS["together"]["call"] = _call_openai_text


# ── Retry helper ─────────────────────────────────────────────────────


async def _retry_with_backoff(
    fn,
    *,
    retries: int = DEFAULT_MAX_RETRIES,
    label: str = "",
):
    for attempt in range(retries):
        try:
            return await fn()
        except (anthropic.RateLimitError, openai.RateLimitError):
            wait = min(2**attempt, 60)
            print(
                f"  Rate limited [{label}] (attempt {attempt + 1}/{retries}), waiting {wait}s..."
            )
            await asyncio.sleep(wait)
        except (anthropic.APIError, openai.APIError) as e:
            if attempt == retries - 1:
                raise
            wait = min(2**attempt, 30)
            print(
                f"  API error [{label}] (attempt {attempt + 1}/{retries}): {e}, retrying in {wait}s..."
            )
            await asyncio.sleep(wait)
    return LLMResponse(text="")


# ── Single completion ────────────────────────────────────────────────


def _verify_reasoning(
    result: LLMResponse | None,
    include_reasoning: bool,
    is_base_completion: bool,
    api_id: str,
) -> None:
    """Raise if include_reasoning=True but no reasoning trace was produced."""
    if not include_reasoning or is_base_completion:
        return
    has_thinking = bool(result and result.thinking)
    has_think_tags = bool(result and "<think>" in (result.text or ""))
    if not has_thinking and not has_think_tags:
        raise RuntimeError(
            f"include_reasoning=True but model {api_id!r} produced no reasoning "
            f"trace. Check that the model supports reasoning/thinking and that "
            f"the appropriate kwargs (e.g. thinking=, extra_body=) are set."
        )


async def complete(
    prompt: str | list[dict],
    model: str = "claude-sonnet-4-6",
    temperature: float | None = None,
    max_tokens: int = 4096,
    use_cache: bool = True,
    retries: int = DEFAULT_MAX_RETRIES,
    include_reasoning: bool = False,
    salt: str | None = None,
    **kwargs,
) -> str:
    """Complete a prompt. Returns the completion text as a string.

    Args:
        prompt: Either a raw string (base model text completion via tinker/vllm/
            together) or a list of message dicts (chat completion via any provider).
            String prompts are only accepted for base-model providers that support
            the /completions endpoint. For chat models, always pass message dicts.
        temperature: Sampling temperature. Pass None (default) to omit from the
            API call, letting the provider use its default. Some models (e.g.
            Opus 4.7, OpenAI reasoning models) reject explicit temperature.
        include_reasoning: If True and the model produced a reasoning/thinking
            trace, prepend it as ``<think>...</think>`` (matching the standard
            chat-template convention used by DeepSeek, Qwen, etc.).
            If False (default), any ``<think>`` blocks in chat output are stripped.
            Has no effect on base-model completions (output is never modified).
        salt: Optional string mixed into the cache key to force distinct cached
            samples for otherwise identical calls (e.g. ``salt="sample_3"`` for
            best-of-N sampling). Does not affect the API call itself.

    Reasoning traces are always captured and cached regardless of this flag.
    """
    api_id, provider, resolved_extra = resolve_model(model)
    merged = {**resolved_extra, **kwargs}
    call_fn = PROVIDERS[provider]["call"]

    if isinstance(prompt, str):
        # String prompts are for base-model text completion only
        if call_fn is not _call_openai_text:
            raise TypeError(
                f"String prompts are only supported for base-model providers "
                f"(tinker/vllm/together), got {provider!r} for model {model!r}. "
                f"Use a list of message dicts for chat models."
            )
        raw_prompt = prompt
        is_base_completion = True
        messages = [{"role": "user", "content": prompt}]  # for cache key only
    else:
        raw_prompt = None
        is_base_completion = False
        messages = prompt

    # Cache lookup
    cache_kwargs = {k: v for k, v in merged.items() if not callable(v)}
    if call_fn is _call_openai_responses:
        cache_kwargs["_api"] = "responses"
    if salt is not None:
        cache_kwargs["_salt"] = salt
    key = _cache_key(api_id, messages, temperature, max_tokens, **cache_kwargs)
    if use_cache:
        cached = cache_get(key)
        if cached is not None:
            _verify_reasoning(cached, include_reasoning, is_base_completion, api_id)
            return _format_output(cached, include_reasoning, is_base_completion)

    sem = _get_semaphore(provider)
    client = _get_client(provider)

    async def _attempt():
        async with sem:
            return await call_fn(
                api_id,
                messages,
                temperature,
                max_tokens,
                client,
                raw_prompt=raw_prompt,
                **merged,
            )

    result = await _retry_with_backoff(_attempt, retries=retries, label=api_id)

    if use_cache and result and result.text:
        cache_put(key, result, api_id)

    _verify_reasoning(result, include_reasoning, is_base_completion, api_id)
    return _format_output(result, include_reasoning, is_base_completion)


# ── Batch completion (Anthropic + OpenAI) ─────────────────────────────


@contextmanager
def _batch_cleanup(cancel_fn):
    """Register a cleanup function for batch cancellation on exit/signal."""
    atexit.register(cancel_fn)
    prev_int = signal.signal(signal.SIGINT, cancel_fn)
    prev_term = signal.signal(signal.SIGTERM, cancel_fn)
    try:
        yield
    finally:
        atexit.unregister(cancel_fn)
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)


def _batch_anthropic(
    api_id: str,
    uncached_indices: list[int],
    messages_list: list[list[dict]],
    temperature: float | None,
    max_tokens: int,
    merged: dict,
    chunk_size: int,
    poll_interval: int,
) -> dict[int, LLMResponse]:
    """Submit and collect results from Anthropic's batch API (sync).

    All chunks are submitted up front, then polled concurrently in one loop.
    """
    client = _get_anthropic_sync()
    uncached_messages = [messages_list[i] for i in uncached_indices]

    # Build and submit chunks
    chunks: list[tuple[str, list[int]]] = []
    for chunk_start in range(0, len(uncached_indices), chunk_size):
        chunk_end = min(chunk_start + chunk_size, len(uncached_indices))
        chunk_indices = uncached_indices[chunk_start:chunk_end]
        chunk_msgs = uncached_messages[chunk_start:chunk_end]

        requests = []
        for i, msgs in enumerate(chunk_msgs):
            system_parts = [m["content"] for m in msgs if m["role"] == "system"]
            chat_msgs = [m for m in msgs if m["role"] != "system"]
            params = {
                "model": api_id,
                "messages": chat_msgs,
                "max_tokens": max_tokens,
            }
            if temperature is not None and api_id not in _ANTHROPIC_NO_TEMPERATURE:
                params["temperature"] = temperature
            if system_parts:
                params["system"] = "\n\n".join(system_parts)
            if "thinking" in merged:
                params["thinking"] = merged["thinking"]
            requests.append(
                anthropic.types.messages.batch_create_params.Request(
                    custom_id=str(i),
                    params=params,
                )
            )

        batch = client.messages.batches.create(requests=requests)
        print(f"  Batch {batch.id}: {len(requests)} requests submitted")
        chunks.append((batch.id, chunk_indices))

    # Cleanup handler — cancels any in-progress batches on exit/signal
    pending_ids = {bid for bid, _ in chunks}

    def _cancel(signum=None, frame=None):
        if not pending_ids:
            return
        print(f"\n  Cancelling {len(pending_ids)} Anthropic batches...")
        for bid in list(pending_ids):
            try:
                client.messages.batches.cancel(bid)
            except Exception:
                pass
        if signum is not None:
            raise SystemExit(1)

    with _batch_cleanup(_cancel):
        # Poll until all batches complete
        elapsed = 0
        while pending_ids:
            for bid in list(pending_ids):
                try:
                    status = client.messages.batches.retrieve(bid)
                except Exception as e:
                    print(f"  Polling error for {bid}: {e}, will retry...")
                    continue
                if status.processing_status == "ended":
                    pending_ids.discard(bid)
                    print(f"  Batch {bid} completed: {status.request_counts}")
            if pending_ids:
                if elapsed > 0 and elapsed % 300 == 0:
                    print(
                        f"  {len(pending_ids)} batches still processing ({elapsed // 60}m elapsed)..."
                    )
                time.sleep(poll_interval)
                elapsed += poll_interval

        # Collect results
        completions: dict[int, LLMResponse] = {}
        for batch_id, chunk_indices in chunks:
            results = {}
            for result in client.messages.batches.results(batch_id):
                idx = int(result.custom_id)
                if result.result.type == "succeeded":
                    content = result.result.message.content
                    text = "".join(b.text for b in content if hasattr(b, "text"))
                    thinking = (
                        "".join(b.thinking for b in content if b.type == "thinking")
                        or None
                    )
                    results[idx] = LLMResponse(text=text, thinking=thinking)
                else:
                    results[idx] = LLMResponse(text="")

            for local_idx, original_idx in enumerate(chunk_indices):
                completions[original_idx] = results.get(local_idx, LLMResponse(text=""))

    return completions


def _batch_openai(
    api_id: str,
    provider: str,
    uncached_indices: list[int],
    messages_list: list[list[dict]],
    temperature: float | None,
    max_tokens: int,
    merged: dict,
    chunk_size: int,
    poll_interval: int,
) -> dict[int, LLMResponse]:
    """Submit and collect results from OpenAI's batch API (sync).

    Chunks are submitted and polled sequentially (one at a time).
    Works with any OpenAI-compatible provider that supports the batch endpoint
    (currently "openai" provider only).
    """
    client = openai.OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
    )
    uncached_messages = [messages_list[i] for i in uncached_indices]
    completions: dict[int, LLMResponse] = {}
    active_batch_ids: list[str] = []

    def _cancel(signum=None, frame=None):
        print(f"\n  Cancelling {len(active_batch_ids)} OpenAI batches...")
        for bid in active_batch_ids:
            try:
                client.batches.cancel(bid)
                print(f"  Cancelled {bid}")
            except Exception:
                pass
        if signum is not None:
            raise SystemExit(1)

    with _batch_cleanup(_cancel):
        # Process in chunks (OpenAI limit: 50k requests per batch)
        for chunk_start in range(0, len(uncached_indices), chunk_size):
            chunk_end = min(chunk_start + chunk_size, len(uncached_indices))
            chunk_indices = uncached_indices[chunk_start:chunk_end]
            chunk_msgs = uncached_messages[chunk_start:chunk_end]

            # Write JSONL request file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".jsonl", delete=False
            ) as f:
                jsonl_path = f.name
                for i, msgs in enumerate(chunk_msgs):
                    body = {
                        "model": api_id,
                        "messages": msgs,
                        "max_completion_tokens": max_tokens,
                    }
                    if temperature is not None:
                        body["temperature"] = temperature
                    if "reasoning_effort" in merged:
                        body["reasoning_effort"] = merged["reasoning_effort"]
                    request = {
                        "custom_id": str(i),
                        "method": "POST",
                        "url": "/v1/chat/completions",
                        "body": body,
                    }
                    f.write(json.dumps(request) + "\n")

            # Upload file and create batch
            with open(jsonl_path, "rb") as f:
                uploaded = client.files.create(file=f, purpose="batch")
            os.unlink(jsonl_path)

            batch = client.batches.create(
                input_file_id=uploaded.id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
            )
            active_batch_ids.append(batch.id)
            print(f"  Batch {batch.id}: {len(chunk_indices)} requests submitted")

            # Poll until done
            elapsed = 0
            while True:
                status = client.batches.retrieve(batch.id)
                counts = status.request_counts
                if status.status == "completed":
                    active_batch_ids.remove(batch.id)
                    print(
                        f"  Batch {batch.id} completed: "
                        f"{counts.completed}/{counts.total} succeeded, "
                        f"{counts.failed} failed"
                    )
                    break
                elif status.status in ("failed", "expired", "cancelled"):
                    active_batch_ids.remove(batch.id)
                    print(f"  Batch {batch.id} {status.status}: {status.errors}")
                    break
                if elapsed > 0 and elapsed % 300 == 0:
                    print(
                        f"  Batch {batch.id}: {status.status} "
                        f"({counts.completed}/{counts.total}, {elapsed // 60}m elapsed)..."
                    )
                time.sleep(poll_interval)
                elapsed += poll_interval

            # Download and parse results
            if status.output_file_id:
                content = client.files.content(status.output_file_id).content
                for line in content.decode("utf-8").strip().split("\n"):
                    if not line:
                        continue
                    row = json.loads(line)
                    local_idx = int(row["custom_id"])
                    original_idx = chunk_indices[local_idx]
                    if row.get("error"):
                        completions[original_idx] = LLMResponse(text="")
                    else:
                        body = row["response"]["body"]
                        choice = body["choices"][0]
                        text = choice["message"]["content"] or ""
                        reasoning = choice["message"].get("reasoning_content")
                        completions[original_idx] = LLMResponse(text=text, thinking=reasoning)

    return completions


async def complete_batch(
    prompts: list[list[dict]],
    model: str = "claude-sonnet-4-6",
    temperature: float | None = None,
    max_tokens: int = 4096,
    use_cache: bool = True,
    chunk_size: int = BATCH_CHUNK_SIZE,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    include_reasoning: bool = False,
    **kwargs,
) -> list[str]:
    """Batch complete prompts via Anthropic or OpenAI batch API.

    Supports Anthropic models (claude-*) and OpenAI models (gpt-*).
    Both providers offer ~50% cost savings vs real-time API calls.

    Args:
        prompts: List of message lists (each a list of {role, content} dicts).
        model: Model ID — routes to the appropriate batch API automatically.
        include_reasoning: If True, prepend reasoning as <think> tags.
        chunk_size: Max requests per batch (Anthropic: 5000, OpenAI: 50000).
        poll_interval: Seconds between status checks.
    """
    messages_list = list(prompts)
    api_id, provider, resolved_extra = resolve_model(model)
    if provider not in ("anthropic", "openai"):
        raise ValueError(
            f"Batch API supports Anthropic and OpenAI models, got {model} ({provider})"
        )
    merged = {**resolved_extra, **kwargs}
    call_fn = PROVIDERS[provider]["call"]

    # Cache lookup
    cache_kwargs = {k: v for k, v in merged.items() if not callable(v)}
    if call_fn is _call_openai_responses:
        cache_kwargs["_api"] = "responses"
    keys = [
        _cache_key(api_id, msgs, temperature, max_tokens, **cache_kwargs)
        for msgs in messages_list
    ]
    cached = cache_get_many(keys) if use_cache else {}
    uncached_indices = [i for i, k in enumerate(keys) if k not in cached]

    print(
        f"  Cache: {len(keys) - len(uncached_indices)}/{len(keys)} hits, "
        f"{len(uncached_indices)} to fetch via {provider} batch API"
    )

    if not uncached_indices:
        return [
            _format_output(
                cached.get(k, LLMResponse(text="")), include_reasoning, False
            )
            for k in keys
        ]

    # Dispatch to provider-specific batch implementation (sync, run in thread)
    if provider == "anthropic":
        all_completions = await asyncio.to_thread(
            _batch_anthropic,
            api_id,
            uncached_indices,
            messages_list,
            temperature,
            max_tokens,
            merged,
            chunk_size,
            poll_interval,
        )
    else:
        all_completions = await asyncio.to_thread(
            _batch_openai,
            api_id,
            provider,
            uncached_indices,
            messages_list,
            temperature,
            max_tokens,
            merged,
            chunk_size,
            poll_interval,
        )

    # Cache new results
    cache_entries = [
        (keys[i], resp, api_id) for i, resp in all_completions.items() if resp.text
    ]
    if cache_entries:
        cache_put_many(cache_entries)
        print(f"  Cached {len(cache_entries)} new results")

    # Assemble final output
    output = []
    for i, k in enumerate(keys):
        if k in cached:
            resp = cached[k]
        elif i in all_completions:
            resp = all_completions[i]
        else:
            resp = LLMResponse(text="")
        output.append(_format_output(resp, include_reasoning, False))

    return output
