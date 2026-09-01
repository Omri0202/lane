"""
Tests for the OpenAI-compatible front door.

Every provider call is stubbed. These assert the proxy's own behaviour — how
it reads the model field, what it reports back, when it falls back and when it
refuses to — none of which should need a network or a key to verify.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from lane import catalog, config, keys, ledger, server
from lane.catalog import Model
from lane.providers import ProviderError

CHEAP = Model(id="t-cheap", provider="anthropic", display="T Cheap", tier=50,
              in_price=0.10, out_price=0.40, context=200_000, max_output=8192)
STRONG = Model(id="t-strong", provider="anthropic", display="T Strong",
               tier=95, in_price=5.0, out_price=25.0, context=1_000_000,
               max_output=64000, sampling=False)
POOL = [CHEAP, STRONG]


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Never touch the developer's real keys, config, or ledger."""
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "LEDGER_FILE", tmp_path / "ledger.jsonl")
    config.reload()
    monkeypatch.setattr(catalog, "usable", lambda *a, **k: list(POOL))
    monkeypatch.setattr(catalog, "by_id",
                        lambda i: next((m for m in POOL if m.id == i), None))
    monkeypatch.setattr(keys, "get", lambda p: "test-key")
    monkeypatch.setattr(keys, "present", lambda: ["anthropic"])
    yield


class FakeProvider:
    """Records what it was asked for and answers without a network."""

    def __init__(self, fail_with: ProviderError | None = None):
        self.calls: list[tuple] = []
        self.fail_with = fail_with

    async def complete(self, body, model_id, key, **kw):
        self.calls.append((model_id, kw))
        if self.fail_with:
            raise self.fail_with
        return {
            "id": "x", "object": "chat.completion", "created": 0,
            "model": model_id,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "hi"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                      "total_tokens": 150},
        }

    async def stream(self, body, model_id, key, usage=None, **kw):
        self.calls.append((model_id, kw))
        if self.fail_with:
            raise self.fail_with
        yield 'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
        if usage is not None:
            usage["in"], usage["out"] = 100, 50
        yield "data: [DONE]\n\n"


@pytest.fixture
def client(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(server.providers, "get", lambda p: fake)
    c = TestClient(server.app)
    c.fake = fake
    return c


def body(model="auto", **kw):
    return {"model": model,
            "messages": [{"role": "user", "content": "hello there"}], **kw}


# ── routing through the model field ──────────────────────────────────────────

def test_auto_routes_and_reports_its_choice(client):
    r = client.post("/v1/chat/completions", json=body("auto"))
    assert r.status_code == 200
    assert r.headers["x-lane-model"] in {m.id for m in POOL}
    assert r.headers["x-lane-lane"]
    assert r.headers["x-lane-reason"]


def test_save_and_performance_diverge(client):
    save = client.post("/v1/chat/completions", json=body("lane-save"))
    perf = client.post("/v1/chat/completions", json=body("lane-perf"))
    assert save.headers["x-lane-model"] == CHEAP.id
    assert perf.headers["x-lane-model"] == STRONG.id


def test_mode_header_overrides_the_model_field(client):
    r = client.post("/v1/chat/completions", json=body("auto"),
                    headers={"x-lane-mode": "performance"})
    assert r.headers["x-lane-model"] == STRONG.id


def test_an_explicit_model_id_is_obeyed_not_routed(client):
    """A router you cannot switch off is a router people work around."""
    r = client.post("/v1/chat/completions", json=body(CHEAP.id))
    assert r.headers["x-lane-model"] == CHEAP.id
    assert r.headers["x-lane-mode"] == "pinned"


def test_forced_lane_skips_the_classifier(client):
    r = client.post("/v1/chat/completions", json=body("lane-reasoning"))
    assert r.headers["x-lane-lane"] == "reasoning"


# ── the sampling trap ────────────────────────────────────────────────────────

def test_sampling_permission_follows_the_model(client):
    """The catalog says STRONG rejects temperature. The adapter must be told,
    or every request to it 400s and the model looks dead."""
    client.post("/v1/chat/completions",
                json=body("lane-perf", temperature=0.7))
    model_id, kwargs = client.fake.calls[-1]
    assert model_id == STRONG.id
    assert kwargs["allow_sampling"] is False

    client.post("/v1/chat/completions",
                json=body("lane-save", temperature=0.7))
    model_id, kwargs = client.fake.calls[-1]
    assert model_id == CHEAP.id
    assert kwargs["allow_sampling"] is True


# ── accounting ───────────────────────────────────────────────────────────────

def test_every_request_lands_in_the_ledger_with_a_counterfactual(client):
    config.set("baseline_model", STRONG.id)
    client.post("/v1/chat/completions", json=body("lane-save"))
    rows = ledger.read()
    assert len(rows) == 1
    row = rows[0]
    assert row["model"] == CHEAP.id
    assert row["in"] == 100 and row["out"] == 50
    assert row["cost"] == pytest.approx(CHEAP.cost(100, 50))
    assert row["baseline_cost"] == pytest.approx(STRONG.cost(100, 50))
    assert row["saved"] > 0


def test_streaming_records_usage_after_the_last_frame(client):
    with client.stream("POST", "/v1/chat/completions",
                       json=body("auto", stream=True)) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    assert "[DONE]" in text
    rows = ledger.read()
    assert rows and rows[-1]["streamed"] and rows[-1]["out"] == 50


# ── failure behaviour ────────────────────────────────────────────────────────

def test_a_bad_request_is_not_retried_on_another_model(monkeypatch):
    """A 400 will be a 400 everywhere. Retrying it just spends more money."""
    fake = FakeProvider(fail_with=ProviderError("anthropic", 400, "bad input"))
    monkeypatch.setattr(server.providers, "get", lambda p: fake)
    c = TestClient(server.app)
    r = c.post("/v1/chat/completions", json=body("auto"))
    assert r.status_code == 400
    assert len(fake.calls) == 1


def test_a_transient_failure_falls_back_to_the_next_model(monkeypatch):
    fake = FakeProvider(fail_with=ProviderError("anthropic", 529, "overloaded"))
    monkeypatch.setattr(server.providers, "get", lambda p: fake)
    c = TestClient(server.app)
    r = c.post("/v1/chat/completions", json=body("lane-perf"))
    assert r.status_code == 529
    assert len(fake.calls) > 1, "should have tried a runner-up"


@pytest.mark.parametrize("status,detail", [
    (401, "invalid x-api-key"),
    (403, "account suspended"),
    (400, "Your credit balance is too low to access the Anthropic API."),
    (429, "You exceeded your current quota, please check your billing"),
])
def test_a_dead_account_routes_to_another_provider(monkeypatch, status, detail):
    """The failure that made LANE unusable on a free tier.

    A Groq key that works plus an Anthropic account with no credits sent every
    REASONING request to Anthropic — its models are the only ones clearing the
    bar — where it failed, without ever trying the provider that would have
    answered. A billing failure is a fact about the provider, not the request.

    Note the 400 and the 429: providers disagree about the status code for "you
    cannot pay", so the code alone cannot be the test.
    """
    working = Model(id="t-other", provider="groq", display="T Other", tier=60,
                    in_price=0.1, out_price=0.4, context=200_000,
                    max_output=8192)
    monkeypatch.setattr(catalog, "usable", lambda *a, **k: POOL + [working])
    monkeypatch.setattr(keys, "present", lambda: ["anthropic", "groq"])

    calls = []

    class Split:
        async def complete(self, b, model_id, key, **kw):
            calls.append(model_id)
            if model_id != working.id:
                raise ProviderError("anthropic", status, detail)
            return {"id": "x", "object": "chat.completion", "created": 0,
                    "model": model_id,
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant",
                                             "content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                              "total_tokens": 2}}

    monkeypatch.setattr(server.providers, "get", lambda p: Split())
    r = TestClient(server.app).post("/v1/chat/completions",
                                    json=body("lane-perf"))
    assert r.status_code == 200, f"should have crossed to groq; tried {calls}"
    assert r.headers["x-lane-model"] == working.id
    assert r.headers["x-lane-provider"] == "groq"


def test_a_dead_provider_is_not_retried_model_by_model(monkeypatch):
    """Excluding the PROVIDER, not just the model — otherwise a three-model
    fallback burns all three attempts inside one dead account."""
    fake = FakeProvider(fail_with=ProviderError("anthropic", 401, "bad key"))
    monkeypatch.setattr(server.providers, "get", lambda p: fake)
    r = TestClient(server.app).post("/v1/chat/completions",
                                    json=body("lane-perf"))
    assert r.status_code == 401
    assert len(fake.calls) == 1, (
        f"tried {len(fake.calls)} models on one dead account")
    assert "disabled_providers" in r.json()["error"]["message"]


def test_failures_are_recorded_too(monkeypatch):
    fake = FakeProvider(fail_with=ProviderError("anthropic", 400, "nope"))
    monkeypatch.setattr(server.providers, "get", lambda p: fake)
    c = TestClient(server.app)
    c.post("/v1/chat/completions", json=body("auto"))
    rows = ledger.read()
    assert rows and rows[-1]["ok"] is False and rows[-1]["error"]


def test_cost_guard_refuses_before_spending(client):
    config.set("max_cost_per_request", 0.0001)
    r = client.post("/v1/chat/completions",
                    json=body("lane-perf", max_tokens=60000))
    assert r.status_code == 402
    assert "limit" in r.json()["error"]["message"]
    assert not client.fake.calls, "must refuse before calling the provider"


def test_malformed_body_is_rejected_cleanly(client):
    r = client.post("/v1/chat/completions", content=b"not json",
                    headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_request_error"


# ── discovery endpoints ──────────────────────────────────────────────────────

def test_models_lists_aliases_before_concrete_models(client):
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert ids[0] == "auto"
    assert {"lane-save", "lane-perf", "lane-balanced"} <= set(ids)
    assert CHEAP.id in ids


def test_dry_run_costs_nothing_and_explains_all_modes(client):
    r = client.post("/lane/route",
                    json={"messages": [{"role": "user",
                                        "content": "fix my sql join"}]})
    data = r.json()
    assert data["classification"]["lane"] == "reasoning"
    assert set(data["choices"]) == set(config.MODES)
    assert not client.fake.calls


def test_health_reports_readiness(client):
    data = client.get("/health").json()
    assert data["status"] == "ok"
    assert data["models"] == len(POOL)
