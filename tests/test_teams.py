"""
Tests for attribution and budgets.

Most of these guard properties an enterprise buyer will ask about directly:
that a budget cannot be stepped over, that turning on teams cannot be
sidestepped by omitting a header, and that a stolen config file is not a set of
working credentials.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from lane import catalog, config, ledger, server, teams
from lane.catalog import Model

CHEAP = Model(id="t-cheap", provider="anthropic", display="Cheap", tier=70,
              in_price=1.0, out_price=5.0, context=200_000, max_output=8192)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "LEDGER_FILE", tmp_path / "ledger.jsonl")
    config.reload()
    monkeypatch.setattr(catalog, "usable", lambda *a, **k: [CHEAP])
    monkeypatch.setattr(catalog, "by_id",
                        lambda i: CHEAP if i == CHEAP.id else None)
    monkeypatch.setattr(server.keys, "get", lambda p: "provider-key")
    monkeypatch.setattr(server.keys, "present", lambda: ["anthropic"])

    class Fake:
        async def complete(self, body, model_id, key, **kw):
            return {"id": "x", "object": "chat.completion", "created": 0,
                    "model": model_id,
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant",
                                             "content": "hi"}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 1000,
                              "total_tokens": 2000}}

    monkeypatch.setattr(server.providers, "get", lambda p: Fake())
    return TestClient(server.app)


def ask(client, key=None):
    headers = {"authorization": f"Bearer {key}"} if key else {}
    return client.post("/v1/chat/completions", headers=headers, json={
        "model": "lane-save",
        "messages": [{"role": "user", "content": "what is the capital of peru"}]})


# ── turning it on ────────────────────────────────────────────────────────────

def test_no_teams_means_no_authentication(client):
    """A laptop install must not demand a header for nobody's benefit."""
    assert not teams.enabled()
    assert ask(client).status_code == 200


def test_the_first_team_switches_authentication_on(client):
    """Otherwise every budget in the system is bypassed by omitting a
    header, which would make the whole feature decorative."""
    teams.create("Engineering", budget=100)
    assert teams.enabled()
    assert ask(client).status_code == 401


@pytest.mark.parametrize("key", [
    None, "", "not-a-lane-key", "lane-sk-invented", "Bearer nonsense"])
def test_a_bad_key_is_refused(client, key):
    teams.create("Engineering", budget=100)
    assert ask(client, key).status_code == 401


def test_a_valid_key_is_attributed(client):
    _, key = teams.create("Engineering", budget=100)
    assert ask(client, key).status_code == 200
    rows = ledger.read()
    assert rows and rows[-1]["team"] == "engineering"


# ── budgets ──────────────────────────────────────────────────────────────────

def test_a_hard_budget_refuses_before_the_money_is_spent(client):
    _, key = teams.create("Support", budget=0.000001, hard=True)
    r = ask(client, key)
    assert r.status_code == 402
    assert "budget" in r.json()["error"]["message"].lower()
    assert not [x for x in ledger.read() if x.get("cost")], (
        "nothing should have been spent")


def test_a_soft_budget_lets_the_request_through(client):
    """Some teams must not be interrupted. Someone should still be told."""
    _, key = teams.create("Ops", budget=0.000001, hard=False)
    assert ask(client, key).status_code == 200


def test_no_budget_means_no_limit(client):
    _, key = teams.create("Research", budget=0)
    assert ask(client, key).status_code == 200


def test_the_estimate_is_charged_before_the_call(client):
    """A ceiling crossed once per period is not a ceiling. A single very large
    request must not be able to step over the limit in one go."""
    team, _ = teams.create("Small", budget=1.0, hard=True)
    huge = 10_000_000
    ok, note = teams.check(team, estimated_cost=huge)
    assert not ok and "budget" in note.lower()


def test_spend_accumulates_and_then_blocks(client):
    """The whole point, end to end: requests go through until the budget is
    reached, then stop."""
    # 1000 in + 1000 out on CHEAP = $0.001 + $0.005 = $0.006 per request.
    _, key = teams.create("Team", budget=0.02, hard=True)
    codes = [ask(client, key).status_code for _ in range(6)]
    assert 200 in codes and 402 in codes, codes
    assert codes.index(402) > 0, "the first request should have succeeded"
    # Once blocked it stays blocked, rather than oscillating.
    assert codes[codes.index(402):] == [402] * (len(codes) - codes.index(402))


def test_a_disabled_team_is_refused_without_deleting_its_history(client):
    _, key = teams.create("Contractor", budget=100)
    assert ask(client, key).status_code == 200
    teams.set_disabled("contractor", True)
    r = ask(client, key)
    assert r.status_code in (401, 402)
    assert any(x.get("team") == "contractor" for x in ledger.read()), (
        "past spend must survive for the record")


# ── keys ─────────────────────────────────────────────────────────────────────

def test_the_key_is_never_stored_in_the_clear(client, tmp_path):
    """A stolen teams.json must be a list of names and budgets, not a set of
    working credentials."""
    _, key = teams.create("Engineering", budget=100)
    raw = (tmp_path / "teams.json").read_text(encoding="utf-8")
    assert key not in raw
    assert teams.PREFIX not in raw
    assert json.loads(raw)["teams"][0]["key_hash"]


def test_rotation_invalidates_the_old_key_immediately(client):
    """Rotation happens because a key leaked. A grace period is the window the
    leak gets used in."""
    _, old = teams.create("Engineering", budget=100)
    assert ask(client, old).status_code == 200
    new = teams.rotate("engineering")
    assert ask(client, old).status_code == 401
    assert ask(client, new).status_code == 200


def test_one_team_cannot_use_another_teams_key(client):
    _, eng = teams.create("Engineering", budget=100)
    _, sup = teams.create("Support", budget=100)
    assert eng != sup
    ask(client, sup)
    assert {r["team"] for r in ledger.read() if r.get("team")} == {"support"}


def test_removing_a_team_kills_its_key(client):
    _, key = teams.create("Gone", budget=100)
    teams.remove("gone")
    teams.create("Other", budget=100)      # keep auth switched on
    assert ask(client, key).status_code == 401


def test_keys_are_unique_and_long_enough_to_be_unguessable(client):
    made = {teams.create(f"team{i}", budget=1)[1] for i in range(20)}
    assert len(made) == 20
    for key in made:
        assert key.startswith(teams.PREFIX)
        assert len(key) > 40


# ── reporting ────────────────────────────────────────────────────────────────

def test_spend_is_reported_per_team(client):
    _, a = teams.create("Alpha", budget=100)
    _, b = teams.create("Beta", budget=100)
    ask(client, a), ask(client, a), ask(client, b)

    by_team = ledger.stats(source="proxy")["by_team"]
    assert by_team["alpha"]["requests"] == 2
    assert by_team["beta"]["requests"] == 1
    assert ledger.stats(source="proxy", team="alpha")["total"]["requests"] == 2


def test_advisor_savings_never_consume_a_real_budget(client):
    """Advisor rows are potential savings on advice nobody can prove was
    taken. Letting a hypothetical number eat a real budget would be
    indefensible."""
    team, key = teams.create("Engineering", budget=100)
    before = teams.spent("engineering")
    ledger.advice(lane="simple", site="claude", recommended=CHEAP.id,
                  top=CHEAP.id, rec_cost=50.0, top_cost=99.0,
                  in_tokens=10, out_tokens=10)
    assert teams.spent("engineering") == before


def test_audit_shadow_calls_do_count_against_the_budget(client):
    """They are real money on the same account."""
    teams.create("Engineering", budget=100)
    ledger.record(lane="simple", mode="audit", model=CHEAP.id,
                  provider="anthropic", in_tokens=1000, out_tokens=1000,
                  source="audit", team="engineering")
    assert teams.spent("engineering") > 0
