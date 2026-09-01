"""
Tests for the two variations the product is sold on.

SAVE  — the cheapest model that still does the job properly.
BEST  — the model whose strengths fit the request.

The distinction only means something if BEST is not simply "the most
expensive". A mode that returns the top of the price list for every request is
a rate card wearing a recommendation's clothes: the user could have found that
answer without installing anything.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lane import catalog, config, ledger, policy, server
from lane.catalog import Model
from lane.lanes import Lane

# A catalog where "biggest" and "best fit" deliberately disagree: the top-tier
# model is a deep thinker with no speed, and the cheap one is built for speed.
THINKER = Model(id="t-think", provider="p", display="Thinker", tier=95,
                in_price=5.0, out_price=25.0, context=500_000,
                max_output=32000, speed=30, strengths=("depth", "code"))
WRITER = Model(id="t-write", provider="p", display="Writer", tier=85,
               in_price=1.0, out_price=5.0, context=500_000,
               max_output=32000, speed=60, strengths=("prose",))
QUICK = Model(id="t-quick", provider="p", display="Quick", tier=60,
              in_price=0.1, out_price=0.4, context=500_000,
              max_output=32000, speed=200, strengths=("speed",))
POOL = [THINKER, WRITER, QUICK]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "LEDGER_FILE", tmp_path / "ledger.jsonl")
    config.reload()
    return TestClient(server.app)


# ── best means fit, not size ─────────────────────────────────────────────────

def test_best_prefers_the_fitting_model_over_the_biggest():
    """A greeting does not become better on a frontier model. If BEST returns
    the top tier here it is not reading the request at all."""
    d = policy.choose(Lane.TRIVIAL, mode=config.MODE_PERFORMANCE, models=POOL)
    assert d.model is QUICK, f"BEST picked {d.model.id} for a greeting"


def test_best_picks_the_thinker_for_a_reasoning_problem():
    d = policy.choose(Lane.REASONING, mode=config.MODE_PERFORMANCE,
                      models=POOL)
    assert d.model is THINKER


def test_best_picks_the_writer_for_prose_over_a_stronger_model():
    """THINKER outranks WRITER on tier. Long-form wants prose, and the whole
    point of the variation is that the ranking follows the request."""
    d = policy.choose(Lane.LONGFORM, mode=config.MODE_PERFORMANCE,
                      models=POOL)
    assert d.model is WRITER, (
        f"picked {d.model.id}; tier alone would have chosen the thinker")


def test_best_says_why_it_fits():
    d = policy.choose(Lane.REASONING, mode=config.MODE_PERFORMANCE,
                      models=POOL)
    assert "think" in d.reason.lower()


def test_best_admits_when_nothing_fits():
    """Rather than dressing up 'most expensive' as 'best'."""
    d = policy.choose(Lane.VISION, mode=config.MODE_PERFORMANCE,
                      models=[Model(id="x", provider="p", display="X", tier=90,
                                    in_price=1, out_price=1, context=100_000,
                                    max_output=8192, strengths=())])
    assert "nothing you have is built for" in d.reason


def test_save_and_best_are_allowed_to_agree():
    """When the cheap model IS the right tool, both variations say so. A
    difference forced for its own sake would be worse than none."""
    save = policy.choose(Lane.TRIVIAL, mode=config.MODE_SAVE, models=POOL)
    best = policy.choose(Lane.TRIVIAL, mode=config.MODE_PERFORMANCE,
                         models=POOL)
    assert save.model is best.model is QUICK


# ── the wire ─────────────────────────────────────────────────────────────────

def _advise(client, text, variation):
    r = client.post("/lane/advise",
                    json={"text": text, "site": "claude",
                          "variation": variation})
    assert r.status_code == 200
    return r.json()


def test_the_variation_is_chosen_per_message_not_per_server(client):
    save = _advise(client, "why does my sql join drop rows", "save")
    best = _advise(client, "why does my sql join drop rows", "best")
    assert save["variation"] == "save" and best["variation"] == "best"
    assert best["recommend"]["cost"] >= save["recommend"]["cost"]


def test_an_unknown_variation_falls_back_to_saving(client):
    """Save is the default because it is the reason people install this."""
    a = _advise(client, "why does my sql join drop rows", "nonsense")
    assert a["variation"] == "save"


def test_best_never_contradicts_save_about_the_same_message(client):
    """Both explanations are visible one click apart. An earlier version had
    BEST assert "nothing cheaper clears the bar" on a request where SAVE had
    just named something cheaper that did."""
    text = "why does my recursive fibonacci take so long on large inputs"
    save = _advise(client, text, "save")
    best = _advise(client, text, "best")
    if save["recommend"]["id"] != best["recommend"]["id"]:
        assert "nothing cheaper" not in best["explain"].lower()
        assert "cheapest" in best["explain"].lower()


# ── the scoreboard ───────────────────────────────────────────────────────────

def test_advice_is_counted_only_when_a_message_is_sent(client):
    """The panel re-advises on every keystroke. Counting those would turn one
    message into forty and make the headline number meaningless."""
    for _ in range(5):
        _advise(client, "what is the capital of peru", "save")
    assert client.get("/lane/advice-stats").json()["messages"] == 0


def test_logging_advice_accumulates_a_potential_saving(client):
    a = _advise(client, "what is the capital of peru", "save")
    for _ in range(3):
        r = client.post("/lane/advice-log", json={
            "lane": a["lane"], "site": "claude",
            "model": a["recommend"]["id"], "top": a["top"]["id"],
            "est_in": a["est_in"], "est_out": a["est_out"]})
        assert r.json()["ok"] is True

    s = client.get("/lane/advice-stats").json()
    assert s["messages"] == 3
    assert s["potential_saving"] > 0
    assert s["would_cost"] > s["would_spend"]
    assert s["potential_saving"] == pytest.approx(
        s["would_cost"] - s["would_spend"], rel=1e-6)


def test_advisor_and_proxy_totals_are_never_added_together(client):
    """One is money that left the account; the other is money that would have
    stayed had the advice been taken, which nobody can verify. A single
    combined figure would be larger and dishonest."""
    a = _advise(client, "what is the capital of peru", "save")
    client.post("/lane/advice-log", json={
        "lane": a["lane"], "site": "claude", "model": a["recommend"]["id"],
        "top": a["top"]["id"], "est_in": 100, "est_out": 100})
    ledger.record(lane="general", mode="save", model=a["recommend"]["id"],
                  provider="anthropic", in_tokens=100, out_tokens=100)

    assert ledger.stats(source="advisor")["total"]["requests"] == 1
    assert ledger.stats(source="proxy")["total"]["requests"] == 1
    assert ledger.stats()["total"]["requests"] == 1, (
        "the default view must be proxy-only, never the sum")


def test_an_unknown_model_is_not_logged(client):
    r = client.post("/lane/advice-log", json={
        "lane": "simple", "site": "claude", "model": "made-up",
        "top": "also-made-up", "est_in": 10, "est_out": 10})
    assert r.json()["ok"] is False
    assert client.get("/lane/advice-stats").json()["messages"] == 0
