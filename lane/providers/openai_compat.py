"""
openai_compat.py — providers that already speak the OpenAI wire format.

OpenAI obviously does. Google's Gemini exposes an OpenAI-compatible endpoint
too, which is why one adapter serves both: pointing the same code at a
different base URL is the entire difference.

This is a deliberate use of raw HTTP rather than a vendor SDK, and the reason
is that LANE is a proxy. The body arriving at the front door is already in the
exact shape the provider wants; the only edit is the model field. Rebuilding
that body through an SDK's typed parameters would mean enumerating every field
the SDK knows about and silently dropping every one it does not — so a client
sending a parameter newer than LANE's pinned SDK version would lose it without
a word. Forwarding the dict preserves what LANE does not understand, which is
the correct behaviour for something in the middle.

(The Anthropic adapter is the opposite case and uses the official SDK: there
the body has to be genuinely rebuilt, because the shapes differ.)
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
}

#: Parameters that mean something to LANE and nothing to a provider.
_STRIP = ("lane", "lane_mode", "lane_lane")

_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)


class OpenAICompatProvider:
    name: str

    def __init__(self, name: str):
        self.name = name
        self.base_url = BASE_URLS[name]

    def _headers(self, key: str) -> dict:
        return {"Authorization": f"Bearer {key}",
                "Content-Type": "application/json"}

    def _body(self, body: dict, model_id: str) -> dict:
        out = {k: v for k, v in body.items() if k not in _STRIP}
        out["model"] = model_id
        return out

    async def complete(self, body: dict, model_id: str, key: str) -> dict:
        payload = self._body(body, model_id)
        payload.pop("stream", None)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(f"{self.base_url}/chat/completions",
                                  headers=self._headers(key), json=payload)
            if r.status_code >= 400:
                raise ProviderError(self.name, r.status_code, r.text)
            return r.json()

    async def stream(self, body: dict, model_id: str, key: str,
                     usage: dict | None = None) -> AsyncIterator[str]:
        """Yields raw SSE frames, already in OpenAI shape.

        Usage is captured on the way past rather than re-derived: OpenAI only
        sends it when stream_options asks, so LANE asks. Without it the ledger
        would have to guess at token counts, and a guessed cost is worse than
        no cost.
        """
        payload = self._body(body, model_id)
        payload["stream"] = True
        payload.setdefault("stream_options", {})["include_usage"] = True

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST",
                                     f"{self.base_url}/chat/completions",
                                     headers=self._headers(key),
                                     json=payload) as r:
                if r.status_code >= 400:
                    detail = (await r.aread()).decode("utf-8", "replace")
                    raise ProviderError(self.name, r.status_code, detail)
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    yield line + "\n\n" if line.startswith("data:") else line

    async def list_models(self, key: str) -> list[str]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            r = await client.get(f"{self.base_url}/models",
                                 headers=self._headers(key))
            if r.status_code >= 400:
                raise ProviderError(self.name, r.status_code, r.text)
            data = r.json().get("data") or []
            # Gemini returns ids like "models/gemini-2.5-pro"; the catalog and
            # the chat endpoint both use the bare name.
            return [str(m.get("id", "")).split("/")[-1] for m in data
                    if m.get("id")]


class ProviderError(RuntimeError):
    """A provider refused the request. Carries enough to hand back verbatim —
    a proxy that rewrites the upstream error makes debugging impossible."""

    def __init__(self, provider: str, status: int, detail: str):
        self.provider = provider
        self.status = status
        self.detail = detail
        message = detail
        try:
            parsed = json.loads(detail)
            message = (parsed.get("error") or {}).get("message") or detail
        except Exception:
            pass
        super().__init__(f"{provider} returned {status}: {message[:500]}")


def _sniff_usage(line: str, usage: dict) -> None:
    """Read token counts out of a frame on its way to the client.

    The frame is forwarded byte-for-byte either way; this only watches. A proxy
    that buffered the stream to compute its own accounting would add latency to
    every token for the sake of a number nobody is waiting for.
    """
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return
    try:
        data = json.loads(payload)
    except Exception:
        return
    u = data.get("usage")
    if isinstance(u, dict):
        usage["in"] = int(u.get("prompt_tokens") or usage.get("in", 0))
        usage["out"] = int(u.get("completion_tokens") or usage.get("out", 0))
