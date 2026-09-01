"""
translate.py — OpenAI request shape in, Anthropic Messages shape out, and back.

LANE speaks OpenAI at the front door because that is what every client already
speaks. Anthropic's Messages API is a different shape, and the differences are
not cosmetic:

  * system prompts are a top-level parameter, not a message with role "system"
  * max_tokens is required, not optional
  * tool results are user-turn content blocks, not messages with role "tool"
  * temperature and top_p are REJECTED WITH A 400 on the current Opus/Sonnet
    line — and every OpenAI client sends temperature unprompted. This one is
    why `sampling` exists in the catalog. Forwarding what the client sent would
    make the best models in the catalog permanently unroutable, and the error
    would look like the model was down.

Everything here is pure function over dicts so it can be tested without a
network, a key, or a running server.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid

#: Anthropic returns its own stop reasons; OpenAI clients branch on theirs.
_STOP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "pause_turn": "stop",
    "refusal": "content_filter",
}

_DATA_URI = re.compile(r"^data:(?P<mt>[\w./+-]+);base64,(?P<data>.+)$", re.S)


# ── request: OpenAI → Anthropic ──────────────────────────────────────────────

def _image_block(url: str) -> dict | None:
    """An OpenAI image_url becomes an Anthropic image block. Both a data: URI
    and a plain https URL are accepted, because clients send both."""
    if not url:
        return None
    m = _DATA_URI.match(url.strip())
    if m:
        return {"type": "image", "source": {
            "type": "base64", "media_type": m.group("mt"),
            "data": m.group("data").strip()}}
    if url.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _content_blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    blocks = []
    for part in content or []:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "text":
            if part.get("text"):
                blocks.append({"type": "text", "text": part["text"]})
        elif kind in ("image_url", "input_image"):
            url = (part.get("image_url") or {}).get("url") if isinstance(
                part.get("image_url"), dict) else part.get("image_url")
            url = url or part.get("url")
            blk = _image_block(url)
            if blk:
                blocks.append(blk)
    return blocks


def to_anthropic(body: dict, model_id: str, *, allow_sampling: bool) -> dict:
    """Build an Anthropic Messages request from an OpenAI chat request."""
    system_parts: list[str] = []
    messages: list[dict] = []

    for msg in body.get("messages") or []:
        role = msg.get("role")

        if role in ("system", "developer"):
            content = msg.get("content")
            system_parts.append(content if isinstance(content, str)
                                else "\n".join(
                                    p.get("text", "") for p in content or []
                                    if isinstance(p, dict)))
            continue

        if role == "tool":
            # OpenAI models a tool result as its own message. Anthropic models
            # it as a block inside the following USER turn, so consecutive
            # results must merge into one message rather than becoming several.
            block = {"type": "tool_result",
                     "tool_use_id": msg.get("tool_call_id") or "",
                     "content": msg.get("content") or ""}
            if messages and messages[-1]["role"] == "user" and isinstance(
                    messages[-1]["content"], list) and messages[-1]["content"] \
                    and messages[-1]["content"][0].get("type") == "tool_result":
                messages[-1]["content"].append(block)
            else:
                messages.append({"role": "user", "content": [block]})
            continue

        if role == "assistant":
            blocks = _content_blocks(msg.get("content"))
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                blocks.append({"type": "tool_use", "id": call.get("id") or "",
                               "name": fn.get("name") or "", "input": args})
            if blocks:
                messages.append({"role": "assistant", "content": blocks})
            continue

        blocks = _content_blocks(msg.get("content"))
        if blocks:
            messages.append({"role": "user", "content": blocks})

    # Anthropic requires at least one message and requires max_tokens.
    if not messages:
        messages = [{"role": "user", "content": [{"type": "text", "text": ""}]}]

    out: dict = {
        "model": model_id,
        "messages": messages,
        "max_tokens": int(body.get("max_tokens")
                          or body.get("max_completion_tokens") or 4096),
    }
    if system_parts:
        out["system"] = "\n\n".join(p for p in system_parts if p)

    stop = body.get("stop")
    if stop:
        out["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)

    if allow_sampling:
        if body.get("temperature") is not None:
            out["temperature"] = body["temperature"]
        if body.get("top_p") is not None:
            out["top_p"] = body["top_p"]

    tools = body.get("tools")
    if tools:
        converted = []
        for t in tools:
            fn = t.get("function") if t.get("type") == "function" else t
            if not fn or not fn.get("name"):
                continue
            converted.append({
                "name": fn["name"],
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters")
                or {"type": "object", "properties": {}},
            })
        if converted:
            out["tools"] = converted

    choice = body.get("tool_choice")
    if choice == "required":
        out["tool_choice"] = {"type": "any"}
    elif choice == "none":
        out.pop("tools", None)
    elif isinstance(choice, dict) and choice.get("function", {}).get("name"):
        out["tool_choice"] = {"type": "tool",
                              "name": choice["function"]["name"]}
    return out


# ── response: Anthropic → OpenAI ─────────────────────────────────────────────

def _new_id() -> str:
    return "chatcmpl-" + uuid.uuid4().hex[:24]


def from_anthropic(resp: dict, *, model_id: str,
                   completion_id: str | None = None) -> dict:
    """Anthropic Message object (as a dict) into an OpenAI chat completion."""
    text_parts: list[str] = []
    tool_calls: list[dict] = []

    for block in resp.get("content") or []:
        kind = block.get("type")
        if kind == "text":
            text_parts.append(block.get("text") or "")
        elif kind == "tool_use":
            tool_calls.append({
                "id": block.get("id") or f"call_{uuid.uuid4().hex[:16]}",
                "type": "function",
                "function": {"name": block.get("name") or "",
                             "arguments": json.dumps(block.get("input") or {})},
            })
        # `thinking` blocks are deliberately dropped: an OpenAI-shaped client
        # has nowhere to put them, and on the current models their text is
        # empty by default anyway.

    message: dict = {"role": "assistant",
                     "content": "".join(text_parts) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls

    usage = resp.get("usage") or {}
    prompt_tokens = int(usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)

    return {
        "id": completion_id or _new_id(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": _STOP.get(resp.get("stop_reason"), "stop"),
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


# ── streaming: Anthropic events → OpenAI chunks ──────────────────────────────

class StreamTranslator:
    """Turns the Anthropic SSE event sequence into OpenAI chat chunks.

    Anthropic streams structured blocks — a block opens, deltas arrive, the
    block closes. OpenAI streams a flat delta channel plus an indexed tool-call
    channel. The mapping is stateful, which is why this is a class: a
    tool_use block's name arrives in content_block_start while its arguments
    arrive as input_json_delta fragments afterwards, and the OpenAI shape wants
    the name on the first chunk of that index.
    """

    def __init__(self, model_id: str, completion_id: str | None = None):
        self.model_id = model_id
        self.id = completion_id or _new_id()
        self.created = int(time.time())
        self.in_tokens = 0
        self.out_tokens = 0
        self.finish = "stop"
        self._block_types: dict[int, str] = {}
        self._tool_index = -1

    def _chunk(self, delta: dict, finish=None) -> dict:
        return {
            "id": self.id, "object": "chat.completion.chunk",
            "created": self.created, "model": self.model_id,
            "choices": [{"index": 0, "delta": delta,
                         "finish_reason": finish}],
        }

    def first(self) -> dict:
        return self._chunk({"role": "assistant", "content": ""})

    def event(self, ev: dict) -> list[dict]:
        """One Anthropic event in, zero or more OpenAI chunks out."""
        kind = ev.get("type")

        if kind == "message_start":
            usage = (ev.get("message") or {}).get("usage") or {}
            self.in_tokens = int(usage.get("input_tokens") or 0)
            return []

        if kind == "content_block_start":
            idx = ev.get("index", 0)
            block = ev.get("content_block") or {}
            self._block_types[idx] = block.get("type") or "text"
            if block.get("type") == "tool_use":
                self._tool_index += 1
                return [self._chunk({"tool_calls": [{
                    "index": self._tool_index,
                    "id": block.get("id") or f"call_{uuid.uuid4().hex[:16]}",
                    "type": "function",
                    "function": {"name": block.get("name") or "",
                                 "arguments": ""}}]})]
            return []

        if kind == "content_block_delta":
            delta = ev.get("delta") or {}
            dtype = delta.get("type")
            if dtype == "text_delta":
                return [self._chunk({"content": delta.get("text") or ""})]
            if dtype == "input_json_delta":
                return [self._chunk({"tool_calls": [{
                    "index": max(self._tool_index, 0),
                    "function": {
                        "arguments": delta.get("partial_json") or ""}}]})]
            # thinking_delta and signature_delta have no OpenAI equivalent.
            return []

        if kind == "message_delta":
            usage = ev.get("usage") or {}
            if usage.get("output_tokens") is not None:
                self.out_tokens = int(usage["output_tokens"])
            reason = (ev.get("delta") or {}).get("stop_reason")
            if reason:
                self.finish = _STOP.get(reason, "stop")
            return []

        return []

    def final(self, include_usage: bool = False) -> list[dict]:
        chunks = [self._chunk({}, finish=self.finish)]
        if include_usage:
            chunks.append({
                "id": self.id, "object": "chat.completion.chunk",
                "created": self.created, "model": self.model_id,
                "choices": [],
                "usage": {
                    "prompt_tokens": self.in_tokens,
                    "completion_tokens": self.out_tokens,
                    "total_tokens": self.in_tokens + self.out_tokens},
            })
        return chunks


def sse(payload) -> str:
    """One server-sent-event frame."""
    if payload == "[DONE]":
        return "data: [DONE]\n\n"
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
