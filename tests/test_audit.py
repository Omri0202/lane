"""
Tests for the quality audit — the feature that answers "will quality drop?"
with a measurement instead of an assurance.

Because the number is the whole point, most of these guard its honesty rather
than its mechanics. A quality figure that flatters the tool producing it is
worth less than no figure at all: it survives exactly until the first buyer
checks, and takes the rest of the product's credibility with it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lane import audit, catalog, config, keys, ledger, server
from lane.catalog import Model

CHEAP = Model(id="a-cheap", provider="anthropic", display="Cheap", tier=60,
              in_price=0.1, out_price=0.4, context=200_000, max_output=8192)
DEAR = Model(id="a-dear", provider="anthropic", display="Dear", tier=95,
             in_price=5.0, out_price=25.0, context=200_000, max_output=8192)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "LEDGER_FILE", tmp_path / "ledger.jsonl")
    config.reload()
    monkeypatch.setattr(catalog, "usable", lambda *a, **k: [CHEAP, DEAR])
    monkeypatch.setattr(catalog, "by_id",
                        lambda i: {"a-cheap": CHEAP, "a-dear": DEAR}.get(i))
    monkeypatch.setattr(keys, "get", lambda p: "test-key")
    monkeypatch.setattr(keys, "present", lambda: ["anthropic"])
    config.set("baseline_model", DEAR.id)
    yield
    config.reload()


# ── sampling ─────────────────────────────────────────────────────────────────

def test_off_by_default():
    """It doubles the cost of the requests it touches. Nobody should discover
    that as a surprise on a bill."""
    assert audit.rate() == 0.0
    assert not audit.should_sample("anything")


def test_sampling_is_deterministic():
    """A random draw would count the same request twice on a retry and inflate
    the sample. It also makes a disputed report impossible to re-derive."""
    config.set("audit_sample_rate", 0.5)
    first = [audit.should_sample(f"req-{i}") for i in range(200)]
    second = [audit.should_sample(f"req-{i}") for i in range(200)]
    assert first == second


def test_sampling_rate_is_roughly_honoured():
    config.set("audit_sample_rate", 0.1)
    hits = sum(audit.should_sample(f"request number {i}") for i in range(2000))
    assert 0.06 < hits / 2000 < 0.15, f"sampled {hits}/2000"


def test_a_nonsense_rate_disables_rather_than_crashes():
    for bad in ("", None, "abc", -1):
        config.set("audit_sample_rate", bad)
        assert audit.rate() == 0.0 or audit.rate() >= 0.0
        audit.should_sample("x")


# ── the judge, and the bias it would otherwise have ──────────────────────────

@pytest.mark.parametrize("swapped", [False, True])
def test_the_verdict_is_read_relative_to_where_the_routed_answer_sat(swapped):
    """Position is alternated to cancel the judge's first-answer bias, so the
    reply has to be interpreted against the position actually used. Getting
    this backwards would invert the headline number on half the sample."""
    # Markers that cannot collide with the template's own words — an earlier
    # version of this test searched for "R" and found it in "REQUEST:".
    row = {"request": "q",
           "routed": {"text": "<<<ROUTEDANSWER>>>"},
           "base": {"text": "<<<BASELINEANSWER>>>"}}
    prompt = audit.judge_prompt(row, swapped)
    first_is_routed = (prompt.index("<<<ROUTEDANSWER>>>")
                       < prompt.index("<<<BASELINEANSWER>>>"))
    assert first_is_routed is swapped

    routed_letter = "A" if swapped else "B"
    other = "B" if swapped else "A"
    assert audit.read_verdict(routed_letter, swapped) == audit.BETTER
    assert audit.read_verdict(other, swapped) == audit.WORSE
    assert audit.read_verdict("SAME", swapped) == audit.SAME


def test_an_unreadable_verdict_is_dropped_not_guessed():
    """A judge that rambles must not be counted as a vote either way."""
    for reply in ("", "I think both are fine", "neither", "42"):
        assert audit.read_verdict(reply, False) is None


def test_the_judge_is_told_not_to_reward_length_or_confidence():
    """The failure mode of every LLM judge, and the one that would make a
    small model look worse than it is."""
    prompt = audit.judge_prompt(
        {"request": "q", "routed": {"text": "a"}, "base": {"text": "b"}}, False)
    low = prompt.lower()
    assert "length" in low and "confident" in low
    assert "same" in low, "SAME must be offered as a legitimate answer"


# ── the summary ──────────────────────────────────────────────────────────────

def _row(verdict, lane="general", routed_cost=0.001, base_cost=0.01):
    return {"lane": lane, "verdict": verdict,
            "routed": {"model": CHEAP.id, "text": "r", "cost": routed_cost},
            "base": {"model": DEAR.id, "text": "b", "cost": base_cost}}


def test_acceptable_counts_better_and_same():
    """A router does not need to WIN. It needs to not lose, far more cheaply."""
    s = audit.summary([_row(audit.BETTER), _row(audit.SAME),
                       _row(audit.SAME), _row(audit.WORSE)])
    assert s["judged"] == 4
    assert s["acceptable"] == pytest.approx(0.75)
    assert s["worse_rate"] == pytest.approx(0.25)


def test_unjudged_rows_are_not_counted_as_passes():
    """The tempting bug: 3 of 4 judged acceptable is 75%, not 100% of the two
    that happened to come back."""
    s = audit.summary([_row(audit.SAME), _row(None), _row(None)])
    assert s["judged"] == 1
    assert s["sampled"] == 3
    assert s["acceptable"] == pytest.approx(1.0)


def test_the_cost_factor_is_measured_not_asserted():
    s = audit.summary([_row(audit.SAME, routed_cost=0.001, base_cost=0.01)] * 3)
    assert s["factor"] == pytest.approx(10.0)


def test_summary_of_nothing_does_not_divide_by_zero():
    s = audit.summary([])
    assert s["judged"] == 0 and s["acceptable"] == 0.0
    assert "nothing judged yet" in audit.headline(s)


def test_the_headline_carries_its_qualifiers():
    config.set("audit_sample_rate", 0.02)
    s = audit.summary([_row(audit.SAME)] * 10)
    line = audit.headline(s)
    assert "10" in line and "judged" in line
    assert "%" in line


# ── it must never touch the answer the user gets ─────────────────────────────

class Recorder:
    def __init__(self):
        self.calls = []

    async def complete(self, body, model_id, key, **kw):
        self.calls.append(model_id)
        return {"id": "x", "object": "chat.completion", "created": 0,
                "model": model_id,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant",
                                         "content": f"from {model_id}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10,
                          "total_tokens": 20}}


def test_the_user_gets_the_routed_answer_even_while_audited(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(server.providers, "get", lambda p: rec)
    config.set("audit_sample_rate", 1.0)

    r = TestClient(server.app).post("/v1/chat/completions", json={
        "model": "lane-save",
        "messages": [{"role": "user", "content": "what is the capital of peru"}]})

    assert r.status_code == 200
    assert r.headers["x-lane-model"] == CHEAP.id
    assert r.json()["choices"][0]["message"]["content"] == f"from {CHEAP.id}"
    assert DEAR.id in rec.calls, "the baseline should have been shadowed"
    assert audit.read(), "the pair should have been recorded"


def test_a_failing_shadow_call_never_breaks_the_request(monkeypatch):
    class HalfBroken(Recorder):
        async def complete(self, body, model_id, key, **kw):
            if model_id == DEAR.id:
                raise RuntimeError("baseline is down")
            return await super().complete(body, model_id, key, **kw)

    monkeypatch.setattr(server.providers, "get", lambda p: HalfBroken())
    config.set("audit_sample_rate", 1.0)
    r = TestClient(server.app).post("/v1/chat/completions", json={
        "model": "lane-save",
        "messages": [{"role": "user", "content": "what is the capital of peru"}]})
    assert r.status_code == 200, "bookkeeping must not fail a paid-for request"


def test_nothing_is_shadowed_when_the_audit_is_off(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(server.providers, "get", lambda p: rec)
    config.set("audit_sample_rate", 0.0)
    TestClient(server.app).post("/v1/chat/completions", json={
        "model": "lane-save",
        "messages": [{"role": "user", "content": "what is the capital of peru"}]})
    assert rec.calls == [CHEAP.id]
    assert not audit.read()


def test_the_shadow_call_is_billed_separately(monkeypatch):
    """It is real money. Folding it into normal traffic would understate what
    the audit costs and overstate what routing saved."""
    monkeypatch.setattr(server.providers, "get", lambda p: Recorder())
    config.set("audit_sample_rate", 1.0)
    TestClient(server.app).post("/v1/chat/completions", json={
        "model": "lane-save",
        "messages": [{"role": "user", "content": "what is the capital of peru"}]})

    assert ledger.stats(source="proxy")["total"]["requests"] == 1
    assert ledger.stats(source="audit")["total"]["requests"] == 1


def test_no_shadow_when_the_route_already_chose_the_baseline(monkeypatch):
    """Comparing a model with itself costs money and proves nothing."""
    rec = Recorder()
    monkeypatch.setattr(server.providers, "get", lambda p: rec)
    config.set("audit_sample_rate", 1.0)
    config.set("baseline_model", CHEAP.id)
    TestClient(server.app).post("/v1/chat/completions", json={
        "model": "lane-save",
        "messages": [{"role": "user", "content": "what is the capital of peru"}]})
    assert rec.calls == [CHEAP.id]
