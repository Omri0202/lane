"""
Tests for setup: giving LANE your keys, and telling it what you can reach.

The security boundary is the important part. These are the only endpoints that
write credentials, and the same browser that has them open also has claude.ai
open in another tab. A chat site may ask LANE which model to use; it must never
be able to read or replace an API key.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lane import catalog, config, keys, server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "LEDGER_FILE", tmp_path / "ledger.jsonl")
    config.reload()
    catalog.reload()
    yield TestClient(server.app)
    config.reload()
    catalog.reload()


# ── the security boundary ────────────────────────────────────────────────────

def test_a_chat_site_cannot_write_a_key(client):
    r = client.post("/lane/setup-key",
                    json={"provider": "groq", "key": "gsk_" + "x" * 52},
                    headers={"Origin": "https://claude.ai"})
    assert r.status_code == 403


def test_a_chat_site_cannot_read_or_change_the_model_selection(client):
    r = client.post("/lane/setup-models", json={"models": []},
                    headers={"Origin": "https://claude.ai"})
    assert r.status_code == 403


def test_setup_endpoints_carry_no_cors_headers(client):
    """Belt to the 403's braces. Without these headers a browser refuses the
    preflight that a JSON body forces, so the request never arrives at all."""
    for path in ("/lane/setup-key", "/lane/setup-models"):
        r = client.post(path, json={}, headers={"Origin": "https://claude.ai"})
        assert "access-control-allow-origin" not in r.headers, path


def test_the_advisory_endpoint_still_works_from_a_chat_site(client):
    """The boundary must not cut off the thing the panel is for."""
    r = client.post("/lane/advise",
                    json={"text": "why does my sql join drop rows",
                          "site": "claude"},
                    headers={"Origin": "https://claude.ai"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "https://claude.ai"


def test_a_same_origin_request_is_allowed(client):
    r = client.post("/lane/setup-models", json={"models": []},
                    headers={"Origin": "http://testserver", "Host": "testserver"})
    assert r.status_code == 200


# ── keys are verified, not just stored ───────────────────────────────────────

def test_an_obviously_broken_key_is_refused_before_the_network(client):
    r = client.post("/lane/setup-key", json={"provider": "groq", "key": "gs"})
    assert r.status_code == 400
    assert "character" in r.json()["error"]["message"]


def test_an_unknown_provider_is_refused(client):
    r = client.post("/lane/setup-key",
                    json={"provider": "hotmail", "key": "x" * 40})
    assert r.status_code == 400


def test_a_key_the_provider_rejects_is_not_stored(client, monkeypatch):
    """"Saved" has to mean stored AND accepted. Reporting success on a key that
    was never tried is how a two-character paste survived long enough to look
    like a routing bug."""
    stored = []
    monkeypatch.setattr(keys, "set", lambda p, k: stored.append((p, k)))

    class Refuses:
        async def list_models(self, key):
            raise RuntimeError("401 invalid api key")

    monkeypatch.setattr(server.providers, "get", lambda p: Refuses())
    r = client.post("/lane/setup-key",
                    json={"provider": "groq", "key": "gsk_" + "x" * 52})
    assert r.status_code == 400
    assert not stored, "a rejected key must not reach the keyring"


def test_a_working_key_is_stored_and_reported(client, monkeypatch):
    monkeypatch.setattr(keys, "set", lambda p, k: "system keyring")

    class Works:
        async def list_models(self, key):
            return ["a", "b", "c"]

    monkeypatch.setattr(server.providers, "get", lambda p: Works())
    r = client.post("/lane/setup-key",
                    json={"provider": "groq", "key": "gsk_" + "x" * 52})
    assert r.json() == {"ok": True, "connected": True,
                        "stored_in": "system keyring",
                        "models_available": 3, "warning": ""}


# ── telling LANE what you can reach ──────────────────────────────────────────

def test_the_selection_narrows_what_the_advisor_recommends(client):
    """The whole point. Somebody on a plan without Opus should never be told
    to use Opus — that is not advice, it is a chore with an extra step."""
    keep = ["claude-sonnet-5", "claude-haiku-4-5"]
    assert client.post("/lane/setup-models",
                       json={"models": keep}).json()["ok"]

    a = client.post("/lane/advise",
                    json={"text": "why does my recursive fibonacci take so "
                                  "long on large inputs",
                          "site": "claude", "variation": "best"}).json()
    assert a["recommend"]["id"] in keep
    assert {o["id"] for o in a["options"]} <= set(keep)
    assert a["assuming_all"] is False


def test_selecting_everything_stores_nothing(client):
    """An explicit list identical to the catalog is just noise that goes stale
    the next time a model is added."""
    every = [m.id for m in catalog.all_models()]
    client.post("/lane/setup-models", json={"models": every})
    assert config.get("enabled_models") == []


def test_an_empty_selection_means_everything_not_nothing(client):
    """Storing "nothing" would leave the advisor with no models to suggest and
    no way back except hand-editing a config file."""
    client.post("/lane/setup-models", json={"models": []})
    assert config.get("enabled_models") == []
    a = client.post("/lane/advise",
                    json={"text": "why does my sql join drop rows",
                          "site": "claude"}).json()
    assert a["options"], "advice must still be possible"


def test_unknown_model_ids_are_dropped(client):
    client.post("/lane/setup-models",
                json={"models": ["claude-sonnet-5", "not-a-model"]})
    assert config.get("enabled_models") == ["claude-sonnet-5"]


def test_a_non_list_selection_is_refused(client):
    r = client.post("/lane/setup-models", json={"models": "claude-sonnet-5"})
    assert r.status_code == 400


# ── the page draws itself from one place ─────────────────────────────────────

def test_setup_state_has_what_the_page_renders(client):
    d = client.get("/lane/setup-state").json()
    assert {p["id"] for p in d["providers"]} == set(keys.PROVIDERS)
    for p in d["providers"]:
        assert p["console"].startswith("https://")
        assert "key" not in {k.lower() for k in p} or not p.get("key"), (
            "the raw key must never reach the page")
    assert len(d["models"]) == len(catalog.all_models())
    for m in d["models"]:
        assert "enabled" in m and "strengths" in m


def test_the_page_is_served(client):
    r = client.get("/setup")
    assert r.status_code == 200
    assert "setup" in r.text.lower()
