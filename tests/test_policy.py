"""
Tests for turning a lane into a model.

These use a small fixed catalog rather than the shipped one, so they assert
behaviour rather than today's prices. A test that asserts "save mode picks
Haiku" starts failing the day a cheaper model is added — which is a successful
outcome being reported as a bug.
"""

from __future__ import annotations

import pytest

from lane import lanes, policy
from lane.catalog import Model
from lane.config import MODE_BALANCED, MODE_PERFORMANCE, MODE_SAVE
from lane.lanes import Lane

CHEAP = Model(id="cheap", provider="p", display="Cheap", tier=50,
              in_price=0.10, out_price=0.40, context=100_000,
              max_output=8192)
MID = Model(id="mid", provider="p", display="Mid", tier=75,
            in_price=0.50, out_price=2.00, context=200_000, max_output=16384)
STRONG = Model(id="strong", provider="p", display="Strong", tier=95,
               in_price=5.00, out_price=25.00, context=1_000_000,
               max_output=64000)
#: Deliberately the most tempting model in every ranking — highest tier AND
#: cheapest — but it cannot see or call tools. It is kept OUT of the ordinary
#: pool, because a model that wins every mode makes the mode tests vacuous. It
#: is added back only where the point is that capability requirements outrank
#: both price and tier.
BLIND = Model(id="blind", provider="p", display="Blind", tier=99,
              in_price=0.01, out_price=0.02, context=1_000_000,
              max_output=64000, vision=False, tools=False)

POOL = [CHEAP, MID, STRONG]


def choose(lane, mode, models=None, **kw):
    return policy.choose(lane, mode=mode, models=models or POOL, **kw)


def test_save_takes_the_cheapest_above_the_floor():
    d = choose(Lane.SIMPLE, MODE_SAVE)
    assert d.model.tier >= lanes.floor(Lane.SIMPLE)
    assert d.model is CHEAP


def test_save_will_not_go_below_the_floor():
    """The rail that stops cost routing degrading into a bad-model router."""
    d = choose(Lane.REASONING, MODE_SAVE)
    assert d.model.tier >= lanes.floor(Lane.REASONING)
    assert d.model is not CHEAP


def test_performance_takes_the_strongest_feasible():
    assert choose(Lane.REASONING, MODE_PERFORMANCE).model is STRONG


def test_balanced_maximises_capability_per_dollar():
    d = choose(Lane.GENERAL, MODE_BALANCED)
    best = max((m for m in POOL if m.tier >= lanes.floor(Lane.GENERAL)),
               key=lambda m: m.value)
    assert d.model is best


def test_capability_requirements_are_hard():
    """BLIND is the strongest AND nearly free, so every mode would pick it on
    price or tier alone. It cannot see, so it must never serve a vision lane —
    a constraint no mode may trade away."""
    tempting = POOL + [BLIND]
    for mode in (MODE_SAVE, MODE_BALANCED, MODE_PERFORMANCE):
        assert choose(Lane.VISION, mode, models=tempting).model is not BLIND
        assert choose(Lane.TOOLS, mode, models=tempting).model is not BLIND
    # ...and it does win when nothing rules it out, proving it was tempting.
    assert choose(Lane.GENERAL, MODE_SAVE, models=tempting).model is BLIND


def test_context_window_excludes_models_that_cannot_fit_the_prompt():
    d = choose(Lane.GENERAL, MODE_SAVE, prompt_tokens=150_000)
    assert d.model.context >= 150_000
    assert d.model is not CHEAP


def test_degrades_loudly_rather_than_silently():
    """When nothing meets the bar the request is still served, but the caller
    is told — a silent downgrade is how users lose trust in a router."""
    d = policy.choose(Lane.REASONING, mode=MODE_SAVE, models=[CHEAP])
    assert d.model is CHEAP
    assert d.degraded and d.degraded_note


def test_degrading_takes_the_strongest_not_the_cheapest():
    """Regression: with only a free-tier provider installed, balanced mode
    answered the REASONING lane with the weakest model in the pool.

    Once the floor cannot be met it was being dropped entirely and the ordinary
    mode ranking applied — and with no floor, the cheapest model also has the
    best capability-per-dollar, so 'balanced' and 'save' both picked the worst
    model for the hardest request. When the bar cannot be met, mode stops
    applying: the user asked for more than exists, so give them the most there
    is.
    """
    weak_pool = [CHEAP, MID]          # neither reaches the reasoning floor
    assert all(m.tier < lanes.floor(Lane.REASONING) for m in weak_pool)
    for mode in (MODE_SAVE, MODE_BALANCED, MODE_PERFORMANCE):
        d = policy.choose(Lane.REASONING, mode=mode, models=weak_pool)
        assert d.degraded, f"{mode} should report degradation"
        assert d.model is MID, (
            f"{mode} picked {d.model.id}; the strongest available is required "
            f"when nothing meets the bar")


def test_raises_when_nothing_can_serve_it():
    with pytest.raises(policy.NoModelAvailable):
        policy.choose(Lane.VISION, mode=MODE_SAVE, models=[BLIND])
    with pytest.raises(policy.NoModelAvailable):
        policy.choose(Lane.GENERAL, mode=MODE_SAVE, models=[])


def test_ranking_is_total_so_choices_are_reproducible():
    """Two models identical on the ranked key must still order deterministically
    — otherwise the model a user gets depends on catalog file order."""
    a = Model(id="a", provider="p", display="A", tier=80, in_price=1.0,
              out_price=1.0, context=100_000, max_output=8192, speed=10)
    b = Model(id="b", provider="p", display="B", tier=80, in_price=1.0,
              out_price=1.0, context=100_000, max_output=8192, speed=99)
    first = [policy.choose(Lane.GENERAL, mode=MODE_PERFORMANCE,
                           models=[a, b]).model.id for _ in range(5)]
    second = [policy.choose(Lane.GENERAL, mode=MODE_PERFORMANCE,
                            models=[b, a]).model.id for _ in range(5)]
    assert len(set(first + second)) == 1


def test_token_estimate_counts_images_as_substantial():
    text_only = policy.estimate_tokens(
        [{"role": "user", "content": "hello"}])
    with_image = policy.estimate_tokens([{"role": "user", "content": [
        {"type": "text", "text": "hello"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,A"}},
    ]}])
    assert with_image > text_only + 500


def test_route_end_to_end_picks_a_reasoning_model_for_code():
    d = policy.route([{"role": "user", "content": "why does my sql join fail"}],
                     mode=MODE_PERFORMANCE, models=POOL)
    assert d.lane == Lane.REASONING
    assert d.model is STRONG
    assert "reason" in d.reason.lower() or d.reason
