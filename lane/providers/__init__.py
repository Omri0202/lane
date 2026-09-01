"""
providers — one adapter per API shape, resolved by name.

Two adapters cover three providers, because Google's Gemini exposes an
OpenAI-compatible endpoint and needs nothing but a different base URL.
Anthropic gets its own because the Messages API is a genuinely different shape.

Adapters are cached per provider. They hold no per-request state — see the
`usage` sink parameter on `stream` — so one instance serves every concurrent
request safely.
"""

from __future__ import annotations

from .openai_compat import OpenAICompatProvider, ProviderError

__all__ = ["get", "ProviderError", "OpenAICompatProvider"]

_cache: dict = {}


def get(provider: str):
    """Return the adapter for a provider name. Raises KeyError if unknown."""
    provider = (provider or "").lower().strip()
    if provider in _cache:
        return _cache[provider]

    if provider == "anthropic":
        from .anthropic_api import AnthropicProvider
        adapter = AnthropicProvider()
    elif provider in ("openai", "google"):
        adapter = OpenAICompatProvider(provider)
    else:
        raise KeyError(f"no adapter for provider {provider!r}")

    _cache[provider] = adapter
    return adapter
