"""
Tests for the OpenAI ↔ Anthropic wire translation.

Pure dict-in dict-out, so none of this needs a key, a network, or a server.
The cases chosen are the ones that break real clients rather than the ones
that are easy to write: system prompts, tool round-trips, images, and the
sampling parameters that make a 400 look like an outage.
"""

from __future__ import annotations

import json

from lane import translate


def test_system_messages_become_the_system_parameter():
    out = translate.to_anthropic({
        "messages": [
            {"role": "system", "content": "You are terse."},
            {"role": "system", "content": "Answer in English."},
            {"role": "user", "content": "hi"},
        ]}, "claude-opus-5", allow_sampling=False)
    assert "You are terse." in out["system"]
    assert "Answer in English." in out["system"]
    assert all(m["role"] != "system" for m in out["messages"])


def test_max_tokens_is_always_present():
    """Anthropic requires it; OpenAI treats it as optional. A client that omits
    it must not produce a 400."""
    out = translate.to_anthropic(
        {"messages": [{"role": "user", "content": "hi"}]},
        "claude-opus-5", allow_sampling=False)
    assert out["max_tokens"] > 0


def test_sampling_is_dropped_when_the_model_rejects_it():
    """The bug this whole flag exists for: every OpenAI client sends
    temperature, and the current Opus/Sonnet line answers it with a 400. If
    this leaks through, the best models in the catalog look permanently down.
    """
    body = {"messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.7, "top_p": 0.9}
    blocked = translate.to_anthropic(body, "claude-opus-5",
                                     allow_sampling=False)
    assert "temperature" not in blocked and "top_p" not in blocked

    allowed = translate.to_anthropic(body, "claude-haiku-4-5",
                                     allow_sampling=True)
    assert allowed["temperature"] == 0.7 and allowed["top_p"] == 0.9


def test_data_uri_image_becomes_a_base64_block():
    out = translate.to_anthropic({"messages": [{"role": "user", "content": [
        {"type": "text", "text": "what is this"},
        {"type": "image_url",
         "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]}]}, "claude-opus-5", allow_sampling=False)
    blocks = out["messages"][0]["content"]
    image = [b for b in blocks if b["type"] == "image"][0]
    assert image["source"] == {"type": "base64", "media_type": "image/png",
                               "data": "QUJD"}


def test_http_image_url_is_passed_through_as_a_url_source():
    out = translate.to_anthropic({"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "https://x.test/a.png"}},
    ]}]}, "claude-opus-5", allow_sampling=False)
    image = out["messages"][0]["content"][0]
    assert image["source"]["type"] == "url"


def test_tool_definitions_are_unwrapped():
    out = translate.to_anthropic({
        "messages": [{"role": "user", "content": "weather?"}],
        "tools": [{"type": "function", "function": {
            "name": "get_weather", "description": "look it up",
            "parameters": {"type": "object", "properties": {"city": {}}}}}],
    }, "claude-opus-5", allow_sampling=False)
    tool = out["tools"][0]
    assert tool["name"] == "get_weather"
    assert tool["input_schema"]["properties"] == {"city": {}}


def test_consecutive_tool_results_merge_into_one_user_turn():
    """Parallel tool calls come back as several OpenAI 'tool' messages, but
    Anthropic wants all their results in a single user turn. Emitting one
    message each is accepted by nothing."""
    out = translate.to_anthropic({"messages": [
        {"role": "user", "content": "weather in both?"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "w", "arguments": '{"city":"a"}'}},
            {"id": "c2", "type": "function",
             "function": {"name": "w", "arguments": '{"city":"b"}'}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "sunny"},
        {"role": "tool", "tool_call_id": "c2", "content": "rain"},
    ]}, "claude-opus-5", allow_sampling=False)

    assistant = out["messages"][1]
    assert [b["type"] for b in assistant["content"]] == ["tool_use", "tool_use"]
    assert assistant["content"][0]["input"] == {"city": "a"}

    results = out["messages"][2]
    assert results["role"] == "user"
    assert len(results["content"]) == 2
    assert {b["tool_use_id"] for b in results["content"]} == {"c1", "c2"}


def test_response_maps_content_and_usage():
    out = translate.from_anthropic({
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 11, "output_tokens": 5},
    }, model_id="claude-opus-5")
    assert out["choices"][0]["message"]["content"] == "hello"
    assert out["choices"][0]["finish_reason"] == "stop"
    assert out["usage"] == {"prompt_tokens": 11, "completion_tokens": 5,
                            "total_tokens": 16}


def test_response_thinking_blocks_are_dropped_not_concatenated():
    """Thinking is on by default on the current models. Folding it into the
    content would put reasoning text into the user's answer."""
    out = translate.from_anthropic({
        "content": [{"type": "thinking", "thinking": "hmm"},
                    {"type": "text", "text": "42"}],
        "stop_reason": "end_turn", "usage": {},
    }, model_id="claude-opus-5")
    assert out["choices"][0]["message"]["content"] == "42"


def test_response_tool_use_becomes_openai_tool_calls():
    out = translate.from_anthropic({
        "content": [{"type": "tool_use", "id": "tu_1", "name": "w",
                     "input": {"city": "berlin"}}],
        "stop_reason": "tool_use", "usage": {},
    }, model_id="claude-opus-5")
    call = out["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "w"
    assert json.loads(call["function"]["arguments"]) == {"city": "berlin"}
    assert out["choices"][0]["finish_reason"] == "tool_calls"


def test_refusal_maps_to_content_filter():
    out = translate.from_anthropic(
        {"content": [], "stop_reason": "refusal", "usage": {}},
        model_id="claude-opus-5")
    assert out["choices"][0]["finish_reason"] == "content_filter"


def test_stream_translator_produces_a_valid_openai_sequence():
    tr = translate.StreamTranslator("claude-opus-5")
    assert tr.first()["choices"][0]["delta"]["role"] == "assistant"

    tr.event({"type": "message_start",
              "message": {"usage": {"input_tokens": 20}}})
    tr.event({"type": "content_block_start", "index": 0,
              "content_block": {"type": "text"}})
    chunks = tr.event({"type": "content_block_delta", "index": 0,
                       "delta": {"type": "text_delta", "text": "hi"}})
    assert chunks[0]["choices"][0]["delta"]["content"] == "hi"

    tr.event({"type": "message_delta", "delta": {"stop_reason": "end_turn"},
              "usage": {"output_tokens": 7}})
    final = tr.final(include_usage=True)
    assert final[0]["choices"][0]["finish_reason"] == "stop"
    assert final[1]["usage"]["prompt_tokens"] == 20
    assert final[1]["usage"]["completion_tokens"] == 7


def test_stream_translator_carries_tool_call_names_and_arguments():
    """The name arrives on block start, the arguments arrive as fragments
    afterwards. OpenAI wants the name on the first chunk of that tool index."""
    tr = translate.StreamTranslator("claude-opus-5")
    start = tr.event({"type": "content_block_start", "index": 0,
                      "content_block": {"type": "tool_use", "id": "tu_1",
                                        "name": "search"}})
    call = start[0]["choices"][0]["delta"]["tool_calls"][0]
    assert call["index"] == 0 and call["function"]["name"] == "search"

    frag = tr.event({"type": "content_block_delta", "index": 0,
                     "delta": {"type": "input_json_delta",
                               "partial_json": '{"q":'}})
    assert frag[0]["choices"][0]["delta"]["tool_calls"][0][
        "function"]["arguments"] == '{"q":'


def test_thinking_deltas_emit_nothing():
    tr = translate.StreamTranslator("claude-opus-5")
    assert tr.event({"type": "content_block_delta", "index": 0,
                     "delta": {"type": "thinking_delta",
                               "thinking": "..."}}) == []


def test_sse_framing():
    assert translate.sse("[DONE]") == "data: [DONE]\n\n"
    frame = translate.sse({"a": 1})
    assert frame.startswith("data: ") and frame.endswith("\n\n")
    assert json.loads(frame[6:].strip()) == {"a": 1}


def test_empty_messages_still_produce_a_valid_request():
    out = translate.to_anthropic({"messages": []}, "claude-opus-5",
                                 allow_sampling=False)
    assert out["messages"] and out["messages"][0]["role"] == "user"
