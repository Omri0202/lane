"""
Tests for the loop that is the product:

    ask for something your models cannot do
      -> LANE names the model that can, and what it costs
      -> you paste that key
      -> the message you already typed goes through

The failure this replaces is a 503 reading "no available model can serve an
image request", which tells somebody nothing they can act on and ends the
conversation they were having.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lane import catalog, config, keys, lanes, server
from lane.lanes import Lane


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "LEDGER_FILE", tmp_path / "ledger.jsonl")
    config.reload()
    # A user with Anthropic only: chat models, no image generator.
    monkeypatch.setattr(keys, "present", lambda: ["anthropic"])
    monkeypatch.setattr(server.keys, "present", lambda: ["anthropic"])
    return TestClient(server.app)


def ask(client, text):
    return client.post("/v1/chat/completions", json={
        "model": "auto", "messages": [{"role": "user", "content": text}]})


# ── the offer ────────────────────────────────────────────────────────────────

def test_an_image_request_offers_the_providers_that_can(client):
    r = ask(client, "create a picture of a dog on a beach")
    assert r.status_code == 503
    body = r.json()
    assert body["error"]["type"] == "capability_unavailable"

    offer = body["lane"]
    assert offer["lane"] == Lane.IMAGE_GEN
    assert "images" in offer["need"]
    assert {p["provider"] for p in offer["providers"]} == {"openai", "google"}


def test_the_offer_names_models_prices_and_where_to_get_a_key(client):
    """Everything needed to act, in the response. A message that says only
    "not supported" makes somebody go and read documentation instead."""
    offer = ask(client, "draw me a logo for a coffee shop").json()["lane"]
    for p in offer["providers"]:
        assert p["provider_name"]
        assert p["console"].startswith("https://")
        assert p["models"], "a provider with no model is not an offer"
        for m in p["models"]:
            assert m["display"] and m["cost"] > 0
            assert m["per_image"] is True


def test_it_never_offers_a_provider_you_already_have(client, monkeypatch):
    """Suggesting a key somebody has already given you reads as broken.

    Tested against the helper rather than the endpoint, because with the
    OpenAI key present there is no gap to report at all — the request simply
    routes. The property being guarded is narrower than that: whatever the
    caller already has must never appear in an offer.
    """
    monkeypatch.setattr(server.keys, "present", lambda: ["anthropic"])
    both = server._capability_offer(Lane.IMAGE_GEN)
    assert {p["provider"] for p in both["providers"]} == {"openai", "google"}

    monkeypatch.setattr(server.keys, "present", lambda: ["anthropic", "openai"])
    fewer = server._capability_offer(Lane.IMAGE_GEN)
    assert {p["provider"] for p in fewer["providers"]} == {"google"}

    monkeypatch.setattr(server.keys, "present",
                        lambda: ["anthropic", "openai", "google"])
    assert server._capability_offer(Lane.IMAGE_GEN) is None, (
        "with every provider connected there is nothing left to offer")


def test_no_offer_when_nothing_could_serve_it_either(client, monkeypatch):
    """If adding a key would not help, saying "add a key" is a lie. The plain
    error is the honest answer."""
    monkeypatch.setattr(catalog, "all_models",
                        lambda: [m for m in catalog._build()[0]
                                 if m.kind != "image"])
    r = ask(client, "create a picture of a dog")
    assert r.status_code == 503
    assert "lane" not in r.json()


def test_an_ordinary_request_is_answered_not_offered(client, monkeypatch):
    """The offer must only appear on a genuine capability gap."""
    class Fake:
        async def complete(self, body, model_id, key, **kw):
            return {"id": "x", "object": "chat.completion", "created": 0,
                    "model": model_id,
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant",
                                             "content": "Lima"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 5,
                              "total_tokens": 10}}

    monkeypatch.setattr(server.providers, "get", lambda p: Fake())
    monkeypatch.setattr(server.keys, "get", lambda p: "key")
    r = ask(client, "what is the capital of peru")
    assert r.status_code == 200


def test_the_offer_carries_the_setup_address(client):
    offer = ask(client, "create a picture of a dog").json()["lane"]
    assert offer["setup_url"].startswith("http://")
    assert offer["setup_url"].endswith("/setup")


# ── the same detection, on the sites the panel runs on ───────────────────────

def test_the_panel_says_which_site_can_do_it(client):
    a = client.post("/lane/advise", json={
        "text": "create a picture of a dog on a beach", "site": "claude"}).json()
    assert a["unavailable_here"] is True
    assert a["site_name"] == "Claude"
    assert {e["site"] for e in a["elsewhere"]} <= {"ChatGPT", "Gemini"}
    assert "draws" in a["explain"] or "draw" in a["explain"]


def test_the_panel_covers_capabilities_beyond_images(client, monkeypatch):
    """Not only the wrong KIND of model — the right kind lacking the
    capability. A site whose models cannot search should say so too."""
    from lane.catalog import Model
    blind = Model(id="x-noweb", provider="anthropic", display="No Web",
                  tier=90, in_price=1, out_price=1, context=200_000,
                  max_output=8192, web=False, vision=False)
    seer = Model(id="x-web", provider="openai", display="Searcher", tier=70,
                 in_price=1, out_price=1, context=200_000, max_output=8192,
                 web=True)
    monkeypatch.setattr(catalog, "declared",
                        lambda p=None: [m for m in (blind, seer)
                                        if p is None or m.provider == p])
    monkeypatch.setattr(catalog, "all_models", lambda: [blind, seer])

    a = client.post("/lane/advise", json={
        "text": "what is the latest news about the election",
        "site": "claude"}).json()
    assert a["lane"] == Lane.WEB_SEARCH
    assert a["unavailable_here"] is True
    assert a["elsewhere"], "it should name the site that can search"


def test_a_site_that_can_do_it_gets_a_normal_recommendation(client):
    a = client.post("/lane/advise", json={
        "text": "create a picture of a dog", "site": "chatgpt"}).json()
    assert a["unavailable_here"] is False
    assert a["recommend"]["per_image"] is True


# ── the need phrases are written for a person ────────────────────────────────

@pytest.mark.parametrize("lane", [Lane.IMAGE_GEN, Lane.VISION, Lane.TOOLS,
                                  Lane.WEB_SEARCH])
def test_every_capability_lane_has_a_readable_need(lane):
    phrase = server._NEED_PHRASE.get(lane)
    assert phrase and phrase.startswith("a model"), lane
    assert lanes.needs(lane) or lanes.kind(lane) == "image", (
        f"{lane} is in the need table but requires nothing")
