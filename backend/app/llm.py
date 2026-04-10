"""Thin wrapper around the Anthropic client. Centralizes model IDs and JSON parsing.

Prompt caching: every `system` prompt here is the same across all candidates
(triage, structure, score). We mark it with `cache_control: ephemeral` so
Anthropic keeps a ~5-minute cache entry. Repeat calls read at 1/10th the
input-token price. Writing to cache is billed at 1.25x; the break-even is
at ~2 cache hits, which we clear within the first few candidates of any batch.
"""
from __future__ import annotations

import json
import re
import time
from typing import NamedTuple
from anthropic import Anthropic

from app.config import get_settings


class LLMResult(NamedTuple):
    """Carrier for LLM response text + usage metadata."""
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    duration_ms: int

    def meta_dict(self) -> dict:
        """Return a flat dict suitable for log_event meta."""
        return {
            "llm_model": self.model,
            "llm_input_tokens": self.input_tokens,
            "llm_output_tokens": self.output_tokens,
            "llm_cache_read_tokens": self.cache_read_tokens,
            "llm_cache_creation_tokens": self.cache_creation_tokens,
            "llm_duration_ms": self.duration_ms,
        }


def _client() -> Anthropic:
    return Anthropic(api_key=get_settings().anthropic_api_key)


def _cached_system(system: str) -> list[dict]:
    """Wrap a plain system prompt in the block-form required for cache_control."""
    return [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _extract_usage(resp, model: str, duration_ms: int, text: str) -> LLMResult:
    usage = resp.usage
    return LLMResult(
        text=text,
        model=model,
        input_tokens=getattr(usage, "input_tokens", 0),
        output_tokens=getattr(usage, "output_tokens", 0),
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0),
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0),
        duration_ms=duration_ms,
    )


def call_sonnet(
    system: str,
    user: str,
    max_tokens: int = 2048,
    temperature: float | None = None,
) -> LLMResult:
    s = get_settings()
    kwargs: dict = {
        "model": s.sonnet_model,
        "max_tokens": max_tokens,
        "system": _cached_system(system),
        "messages": [{"role": "user", "content": user}],
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    t0 = time.monotonic()
    resp = _client().messages.create(**kwargs)
    duration_ms = int((time.monotonic() - t0) * 1000)
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    return _extract_usage(resp, s.sonnet_model, duration_ms, text)


def call_opus(system: str, user: str, max_tokens: int = 3000) -> LLMResult:
    s = get_settings()
    t0 = time.monotonic()
    resp = _client().messages.create(
        model=s.opus_model,
        max_tokens=max_tokens,
        system=_cached_system(system),
        messages=[{"role": "user", "content": user}],
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    return _extract_usage(resp, s.opus_model, duration_ms, text)


def parse_json_block(text: str) -> dict:
    """Extract the first JSON object from a model response, tolerant of code fences."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    # First {...} balanced object
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in model response")
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON in model response")
