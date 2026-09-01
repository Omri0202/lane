"""
Tests for the advisor endpoint — what to pick, what it costs, and why.

The case that matters most is the one that motivated all of it: asking Claude
for a picture. Every other lane degrades gracefully when the advice is slightly
off, because a slightly-too-cheap chat model still answers. An image request
sent to a chat model does not produce a worse picture; it produces no picture,
and the advice was not imperfect but impossible.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lane import classify, config, server
from lane.lanes import Lane


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    config.reload()
    return TestClient(server.app)


def advise(client, text, site="claude"):
    r = client.post("/lane/advise", json={"text": text, "site": site})
    assert r.status_code == 200
    return r.json()


# ── recognising the kind of request ──────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "create a picture of Germany",
    "draw me a logo for a coffee shop",
    "generate a photo of a sunset over Tel Aviv",
    "I want an illustration of a dragon",
    "design a poster for our school play",
    "make an image of a cat wearing a hat",
])
def test_image_requests_are_recognised(text):
    d = classify.classify([{"role": "user", "content": text}])
    assert d["lane"] == Lane.IMAGE_GEN, f"{text!r} -> {d['lane']}"
    assert d["tier"] == "0", "must be deterministic, not a statistical guess"


@pytest.mark.parametrize("text", [
    "describe this picture for me",
    "what is in the photo above",
    "the image is blurry, why is that",
    "write me a function that resizes images",
    "explain how image compression works",
])
def test_talking_about_images_is_not_asking_for_one(text):
    """The nouns are the same; only the verb separates them. A rule that fired
    on the nouns alone would hijack every conversation about a photo."""
    d = classify.classify([{"role": "user", "content": text}])
    assert d["lane"] != Lane.IMAGE_GEN, f"{text!r} wrongly read as image_gen"


# ── the site cannot do it ────────────────────────────────────────────────────

def test_claude_is_told_plainly_it_cannot_draw(client):
    a = advise(client, "create a picture of Germany", site="claude")
    assert a["lane"] == Lane.IMAGE_GEN
    assert a["unavailable_here"] is True
    assert a["site_name"] == "Claude"
    assert a["elsewhere"], "must name somewhere that can"
    assert {e["site"] for e in a["elsewhere"]} <= {"ChatGPT", "Gemini"}
    assert all(e["cost"] > 0 for e in a["elsewhere"])
    assert "draws" in a["explain"] or "draw" in a["explain"]


def test_no_chat_model_is_ever_offered_for_an_image_request(client):
    """The failure being guarded against: recommending Opus for a picture
    because it is the strongest model on the site."""
    a = advise(client, "draw me a logo for a coffee shop", site="claude")
    assert not a.get("options"), "a chat model was offered for an image request"


def test_the_site_that_can_draw_gets_a_normal_recommendation(client):
    a = advise(client, "create a picture of Germany", site="chatgpt")
    assert a["unavailable_here"] is False
    assert a["recommend"]["per_image"] is True
    assert a["recommend"]["cost"] > 0
    assert a["kind"] == "image"


# ── costing this specific message ────────────────────────────────────────────

def test_costs_are_for_this_request_not_a_rate_card(client):
    short = advise(client, "what is the capital of Peru")
    long_ = advise(client, "why does my recursive fibonacci take so long "
                           "on large inputs and how would you fix it")
    assert short["est_out"] < long_["est_out"], (
        "a reasoning reply should be estimated longer than a lookup")
    assert short["recommend"]["cost"] < long_["recommend"]["cost"]


def test_output_tokens_are_counted(client):
    """Output is priced 4-5x higher than input everywhere. An estimate that
    counted only the prompt would understate every request, always in the
    direction that flatters the tool."""
    a = advise(client, "explain how compound interest works in detail")
    assert a["est_out"] > a["est_in"] * 5


def test_the_saving_is_arithmetic_not_decoration(client):
    a = advise(client, "thanks that worked perfectly")
    if a["is_top"]:
        pytest.skip("nothing cheaper on this catalog")
    assert a["saving"] == pytest.approx(
        a["top"]["cost"] - a["recommend"]["cost"], rel=1e-6)
    assert a["factor"] == pytest.approx(
        a["top"]["cost"] / a["recommend"]["cost"], rel=0.05)


def test_every_answer_explains_itself(client):
    for text in ["thanks that worked", "what is the capital of Peru",
                 "why does my sql join drop rows",
                 "draft an email declining politely",
                 "create a picture of Germany"]:
        a = advise(client, text)
        assert a["explain"].strip(), f"no explanation for {text!r}"
        assert len(a["explain"]) > 25, "an explanation should be a sentence"


# ── advice you can act on ────────────────────────────────────────────────────

def test_only_models_from_the_site_you_are_on_are_offered(client):
    a = advise(client, "why does my sql join drop rows", site="claude")
    for opt in a["options"]:
        assert opt["id"].startswith("claude"), (
            f"{opt['id']} is not something a claude.ai user can pick")


def test_an_unknown_site_still_answers(client):
    a = advise(client, "why does my sql join drop rows", site="")
    assert a["lane"] and a.get("explain") is not None


def test_empty_input_does_not_explode(client):
    for text in ["", "   ", "?"]:
        r = client.post("/lane/advise", json={"text": text, "site": "claude"})
        assert r.status_code == 200


def test_cors_is_granted_to_chat_sites_but_not_to_completions(client):
    """A page that could reach the completions endpoint cross-origin could
    spend the user's money without being asked."""
    origin = "https://claude.ai"
    ok = client.post("/lane/advise", json={"text": "hello there friend"},
                     headers={"Origin": origin})
    assert ok.headers.get("access-control-allow-origin") == origin

    spend = client.post("/v1/chat/completions",
                        json={"model": "auto", "messages": []},
                        headers={"Origin": origin})
    assert "access-control-allow-origin" not in spend.headers


def test_an_unlisted_origin_gets_no_cors(client):
    r = client.post("/lane/advise", json={"text": "hello there friend"},
                    headers={"Origin": "https://evil.test"})
    assert "access-control-allow-origin" not in r.headers
