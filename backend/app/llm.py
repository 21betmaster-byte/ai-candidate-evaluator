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
from anthropic import Anthropic

from app.config import get_settings


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


def call_sonnet(
    system: str,
    user: str,
    max_tokens: int = 2048,
    temperature: float | None = None,
) -> str:
    s = get_settings()
    kwargs: dict = {
        "model": s.sonnet_model,
        "max_tokens": max_tokens,
        "system": _cached_system(system),
        "messages": [{"role": "user", "content": user}],
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = _client().messages.create(**kwargs)
    return "".join(b.text for b in resp.content if hasattr(b, "text"))


def call_opus(system: str, user: str, max_tokens: int = 3000) -> str:
    s = get_settings()
    resp = _client().messages.create(
        model=s.opus_model,
        max_tokens=max_tokens,
        system=_cached_system(system),
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if hasattr(b, "text"))


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
