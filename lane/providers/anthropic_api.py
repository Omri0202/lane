"""
anthropic_api.py — the Anthropic adapter, via the official SDK.

Unlike the OpenAI-compatible providers, this one genuinely rebuilds the
request: the Messages API has a different shape, so there is nothing to pass
through. That is exactly the case where a vendor SDK earns its place — it owns
auth, retries, timeouts, and the event types that streaming produces.

Two model-specific behaviours are handled here rather than left to fail:

  * temperature / top_p are REJECTED with a 400 on the current Opus and Sonnet
    line. Every OpenAI client sends temperature. `Model.sampling` says whether
    this model tolerates it, and translate.to_anthropic drops it when not.

  * thinking is on by default on those models and its text is omitted by
    default. Thinking blocks are dropped on the way out because an
    OpenAI-shaped client has nowhere to put them.
"""

from __future__ import annotations

from typing import AsyncIterator

from .. import translate
from .openai_compat import ProviderError


class AnthropicProvider:
    name = "anthropic"

    def _client(self, key: str):
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "anthropic", 500,
                "the `anthropic` package is not installed — "
                "run: pip install anthropic") from exc
        return AsyncAnthropic(api_key=key, max_retries=2, timeout=600.0)

    @staticmethod
    def _wrap(exc: Exception) -> ProviderError:
        status = getattr(exc, "status_code", None) or 502
        body = getattr(exc, "body", None)
        detail = str(exc)
        if isinstance(body, dict):
            detail = (body.get("error") or {}).get("message") or detail
        return ProviderError("anthropic", int(status), detail)

    async def complete(self, body: dict, model_id: str, key: str,
                       *, allow_sampling: bool = True) -> dict:
        req = translate.to_anthropic(body, model_id,
                                     allow_sampling=allow_sampling)
        client = self._client(key)
        try:
            msg = await client.messages.create(**req)
        except Exception as exc:
            raise self._wrap(exc) from exc
        return translate.from_anthropic(msg.model_dump(), model_id=model_id)

    async def stream(self, body: dict, model_id: str, key: str,
                     *, allow_sampling: bool = True,
                     include_usage: bool = True,
                     usage: dict | None = None) -> AsyncIterator[str]:
        """Yields OpenAI-shaped SSE frames.

        The raw event stream is used rather than the SDK's text helper because
        tool calls have to survive the trip: `.text_stream` would silently drop
        every tool_use block, which turns an agentic client into one that
        appears to answer with an empty message.

        Token counts land in the caller-supplied `usage` dict. They cannot be
        returned — this is a generator — and they must not be stashed on the
        provider instance, which is shared by every concurrent request and
        would hand one user's token count to another user's ledger entry.
        """
        req = translate.to_anthropic(body, model_id,
                                     allow_sampling=allow_sampling)
        client = self._client(key)
        tr = translate.StreamTranslator(model_id)
        yield translate.sse(tr.first())
        try:
            stream = await client.messages.create(**req, stream=True)
            async for event in stream:
                payload = event.model_dump() if hasattr(event, "model_dump") \
                    else dict(event)
                for chunk in tr.event(payload):
                    yield translate.sse(chunk)
        except Exception as exc:
            raise self._wrap(exc) from exc
        for chunk in tr.final(include_usage=include_usage):
            yield translate.sse(chunk)
        yield translate.sse("[DONE]")
        if usage is not None:
            usage["in"] = tr.in_tokens
            usage["out"] = tr.out_tokens

    async def list_models(self, key: str) -> list[str]:
        client = self._client(key)
        try:
            page = await client.models.list(limit=100)
        except Exception as exc:
            raise self._wrap(exc) from exc
        return [m.id for m in page.data]
