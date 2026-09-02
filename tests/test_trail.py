"""
Tests for the audit trail and the role model.

The trail's only value is that it is hard to revise quietly, so most of these
tamper with the file and check the chain notices. The rest guard the promise
that prompts never land in it — an audit log that accumulates the text of every
question anyone asked is a data-protection liability, and it is the first thing
a compliance reviewer objects to.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from lane import catalog, config, server, teams, trail
from lane.catalog import Model

CHEAP = Model(id="t-cheap", provider="anthropic", display="Cheap", tier=60,
              in_price=1.0, out_price=5.0, context=200_000, max_output=8192)
DEAR = Model(id="t-dear", provider="anthropic", display="Dear", tier=95,
             in_price=5.0, out_price=25.0, context=200_000, max_output=8192)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "LEDGER_FILE", tmp_path / "ledger.jsonl")
    config.reload()
    return tmp_path


@pytest.fixture
def client(home, monkeypatch):
    monkeypatch.setattr(catalog, "usable", lambda *a, **k: [CHEAP, DEAR])
    monkeypatch.setattr(catalog, "by_id",
                        lambda i: {"t-cheap": CHEAP, "t-dear": DEAR}.get(i))
    monkeypatch.setattr(catalog, "all_models", lambda: [CHEAP, DEAR])
    monkeypatch.setattr(server.keys, "get", lambda p: "provider-key")
    monkeypatch.setattr(server.keys, "present", lambda: ["anthropic"])

    class Fake:
        async def complete(self, body, model_id, key, **kw):
            return {"id": "x", "object": "chat.completion", "created": 0,
                    "model": model_id,
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": "hi"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10,
                              "total_tokens": 20}}

    monkeypatch.setattr(server.providers, "get", lambda p: Fake())
    return TestClient(server.app)


def ask(client, key, model="lane-perf", content="why does my sql join fail"):
    return client.post("/v1/chat/completions",
                       headers={"authorization": f"Bearer {key}"},
                       json={"model": model,
                             "messages": [{"role": "user", "content": content}]})


# ── the chain ────────────────────────────────────────────────────────────────

def test_an_empty_trail_verifies(home):
    assert trail.verify()["ok"]


def test_entries_chain_and_verify(home):
    for i in range(5):
        trail.record(trail.TEAM_CREATED, target=f"team{i}")
    v = trail.verify()
    assert v["ok"] and v["entries"] == 5

    rows = trail.read()
    assert rows[0]["prev"] == trail.GENESIS
    for a, b in zip(rows, rows[1:]):
        assert b["prev"] == a["hash"]
        assert b["seq"] == a["seq"] + 1


def test_an_edited_entry_is_detected(home):
    """The case this exists for: someone raises a budget after the fact and
    leaves the hash alone."""
    trail.record(trail.BUDGET_CHANGED, target="support",
                 detail={"budget": 25.0})
    trail.record(trail.TEAM_CREATED, target="other")

    path = home / "trail.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row["detail"]["budget"] = 99999.0
    lines[0] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    v = trail.verify()
    assert not v["ok"] and v["reason"] == "hash"
    assert "edited" in v["message"]


def test_a_deleted_entry_is_detected(home):
    for i in range(4):
        trail.record(trail.TEAM_CREATED, target=f"team{i}")
    path = home / "trail.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    v = trail.verify()
    assert not v["ok"] and v["reason"] in ("link", "sequence")


def test_a_rewritten_entry_with_a_recomputed_hash_still_breaks_the_link(home):
    """Recomputing the tampered entry's own hash is the obvious next move.
    It fixes that entry and breaks every one after it."""
    for i in range(3):
        trail.record(trail.TEAM_CREATED, target=f"team{i}")
    path = home / "trail.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row["target"] = "somebody-else"
    body = {k: row[k] for k in
            ("seq", "t", "iso", "actor", "action", "target", "detail", "prev")}
    row["hash"] = trail._digest(body)         # a consistent forgery
    lines[0] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    v = trail.verify()
    assert not v["ok"] and v["reason"] == "link"


def test_a_corrupt_line_is_reported_not_skipped(home):
    trail.record(trail.TEAM_CREATED, target="a")
    with (home / "trail.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("this is not json\n")
    v = trail.verify()
    assert not v["ok"] and v["reason"] == "corrupt"


def test_seal_returns_a_head_hash_that_changes_with_every_entry(home):
    trail.record(trail.TEAM_CREATED, target="a")
    first = trail.verify()["head"]
    trail.record(trail.TEAM_CREATED, target="b")
    assert trail.verify()["head"] != first


def test_logging_never_raises(home, monkeypatch):
    """A failure to log must not fail the thing being logged, or the log
    becomes a reason to avoid using the tool."""
    monkeypatch.setattr(config, "HOME", home / "does" / "not" / "exist" / "\0")
    assert trail.record(trail.TEAM_CREATED, target="x") == {}


# ── what it records, and what it must not ────────────────────────────────────

def test_prompts_never_reach_the_trail(client):
    secret = "my-password-is-hunter2-and-the-merger-closes-friday"
    _, key = teams.create("Engineering", budget=100)
    ask(client, key, content=secret)

    raw = json.dumps(trail.read())
    assert secret not in raw
    assert "hunter2" not in raw
    served = [r for r in trail.read() if r["action"] == trail.REQUEST_SERVED]
    assert served, "the request should still be recorded"
    assert set(served[-1]["detail"]) <= {"lane", "model", "cost"}


def test_administrative_actions_are_recorded(client):
    teams.create("Engineering", budget=100)
    trail.record(trail.KEY_ROTATED, target="engineering")
    trail.record(trail.BUDGET_CHANGED, target="engineering",
                 detail={"budget": 250.0, "period": "monthly", "hard": True})
    actions = [r["action"] for r in trail.read()]
    assert trail.KEY_ROTATED in actions and trail.BUDGET_CHANGED in actions


def test_refusals_are_recorded_with_a_reason(client):
    _, key = teams.create("Finance", budget=0, role=teams.VIEWER)
    assert ask(client, key).status_code == 403
    refused = [r for r in trail.read() if r["action"] == trail.REQUEST_REFUSED]
    assert refused and "role" in refused[-1]["detail"]["why"]


def test_a_failed_authentication_is_recorded(client):
    teams.create("Engineering", budget=100)
    ask(client, "lane-sk-invented")
    assert any(r["action"] == trail.AUTH_FAILED for r in trail.read())


def test_every_action_has_a_human_description(home):
    for action in [v for k, v in vars(trail).items()
                   if k.isupper() and isinstance(v, str) and "." in v]:
        entry = trail.record(action, target="thing", detail={"budget": 1.0,
                                                             "role": "member"})
        assert trail.describe(entry).strip(), f"{action} has no description"


# ── roles ────────────────────────────────────────────────────────────────────

def test_a_viewer_cannot_send_requests(client):
    _, key = teams.create("Finance", role=teams.VIEWER)
    r = ask(client, key)
    assert r.status_code == 403
    assert "viewer" in r.json()["error"]["message"]


def test_a_member_can_send_requests(client):
    _, key = teams.create("Engineering", role=teams.MEMBER)
    assert ask(client, key).status_code == 200


def test_an_admin_can_send_requests_too(client):
    _, key = teams.create("Platform", role=teams.ADMIN)
    assert ask(client, key).status_code == 200


def test_capabilities_are_what_the_roles_claim():
    for role, expect in [(teams.MEMBER, {"infer"}),
                         (teams.VIEWER, {"read"}),
                         (teams.ADMIN, {"infer", "read", "manage"})]:
        team = {"role": role}
        for cap in ("infer", "read", "manage"):
            assert teams.can(team, cap) is (cap in expect), (role, cap)


def test_a_disabled_key_has_no_capabilities():
    assert not teams.can({"role": teams.ADMIN, "disabled": True}, "infer")


def test_an_unknown_role_is_refused_at_creation():
    with pytest.raises(ValueError):
        teams.create("Bad", role="superuser")


# ── model restrictions ───────────────────────────────────────────────────────

def test_a_restricted_team_is_routed_within_its_allowance(client):
    """Not refused — routed. A policy that produces errors instead of
    alternatives is a policy that gets switched off."""
    _, key = teams.create("Support", budget=100,
                          allowed_models=[CHEAP.id])
    r = ask(client, key, model="lane-perf")
    assert r.status_code == 200
    assert r.headers["x-lane-model"] == CHEAP.id


def test_an_unrestricted_team_reaches_the_better_model(client):
    _, key = teams.create("Engineering", budget=100)
    r = ask(client, key, model="lane-perf")
    assert r.headers["x-lane-model"] == DEAR.id


def test_a_restricted_team_cannot_pin_a_forbidden_model(client):
    """The restriction must survive an explicit model id, or it is advisory."""
    _, key = teams.create("Support", budget=100, allowed_models=[CHEAP.id])
    r = ask(client, key, model=DEAR.id)
    assert r.status_code == 403
    assert "not permitted" in r.json()["error"]["message"]


def test_an_empty_restriction_means_no_restriction(client):
    _, key = teams.create("Engineering", budget=100, allowed_models=[])
    assert ask(client, key).status_code == 200


def test_a_restriction_to_nothing_reachable_says_so(client):
    _, key = teams.create("Stuck", budget=100,
                          allowed_models=["a-model-that-is-gone"])
    r = ask(client, key)
    assert r.status_code == 503
    assert "restricted" in r.json()["error"]["message"]
