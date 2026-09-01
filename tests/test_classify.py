"""
Grades the router on phrasing it was never trained on.

This is the test that matters. A classifier is trivially perfect on its own
training examples, so a suite that only checked those would pass forever while
the product got worse. Everything here is scored against corpus.HELDOUT, which
shares no phrasing with corpus.TRAIN.

The thresholds below are deliberately a little below the measured numbers.
They are a floor that catches regressions, not a target — tightening them to
exactly today's score would turn every honest improvement elsewhere into a
red build.

A warning about maintenance: every time HELDOUT is consulted to tune a
constant, it leaks a little into the design and becomes slightly less of a
test. If routing quality needs real work, add logged prompts from `lane tail`
to TRAIN and write a fresh held-out set — do not soften this one.
"""

from __future__ import annotations

import pytest

from lane import classify
from lane.corpus import HELDOUT, TRAIN
from lane.lanes import ORDER, Lane


def predict(text: str) -> str:
    """Exactly what the server does for a plain text prompt."""
    return classify.classify([{"role": "user", "content": text}])["lane"]


def demand(lane: str) -> int:
    return ORDER.index(lane) if lane in ORDER else len(ORDER)


def score():
    exact = under = over = 0
    misses = []
    for text, gold in HELDOUT:
        got = predict(text)
        if got == gold:
            exact += 1
        else:
            misses.append((text, gold, got))
            if demand(got) < demand(gold):
                under += 1
            else:
                over += 1
    n = len(HELDOUT)
    return exact / n, under / n, over / n, misses


def test_heldout_accuracy():
    exact, _, _, misses = score()
    assert exact >= 0.82, (
        f"held-out accuracy fell to {exact:.1%}; misses:\n" +
        "\n".join(f"  {g} -> {p}: {t!r}" for t, g, p in misses))


def test_never_under_routes():
    """The failure that costs real money and real trust.

    Sending a reasoning problem to a cheap model produces a confidently wrong
    answer the user must notice, re-ask, and pay for twice. Sending a greeting
    to an expensive one wastes a fraction of a cent. These are not comparable,
    and the router is tuned so the first one does not happen.
    """
    _, under, _, misses = score()
    bad = [(t, g, p) for t, g, p in misses if demand(p) < demand(g)]
    assert under <= 0.04, (
        f"under-routing rose to {under:.1%}:\n" +
        "\n".join(f"  {g} -> {p}: {t!r}" for t, g, p in bad))


def test_structural_beats_text():
    """An attached image outranks whatever the words say."""
    msg = [{"role": "user", "content": [
        {"type": "text", "text": "write me a python function to sort a list"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}},
    ]}]
    d = classify.classify(msg)
    assert d["lane"] == Lane.VISION
    assert d["tier"] == "structural"


def test_declared_tools_win():
    d = classify.classify([{"role": "user", "content": "hey"}],
                          tools=[{"type": "function",
                                  "function": {"name": "get_weather"}}])
    assert d["lane"] == Lane.TOOLS


@pytest.mark.parametrize("text", [
    "Traceback (most recent call last):\n  File \"a.py\", line 3",
    "```python\nprint(1)\n```",
    "please think carefully about this one",
])
def test_tier0_is_deterministic(text):
    d = classify.classify([{"role": "user", "content": text}])
    assert d["lane"] == Lane.REASONING
    assert d["tier"] == "0"


def test_only_the_last_user_turn_is_read():
    """A long technical history must not drag a 'thanks' into the top lane.

    This is the single most expensive mistake a router can make in a chat
    client, because every conversation ends with pleasantries and every one of
    them would be billed at reasoning rates.
    """
    history = [
        {"role": "user", "content": "why does my b-tree rebalance wrongly"},
        {"role": "assistant", "content": "Because the split threshold is off."},
        {"role": "user", "content": "thanks!"},
    ]
    assert classify.classify(history)["lane"] == Lane.TRIVIAL


def test_classification_is_free_and_fast():
    """No network, no model call, and fast enough to be invisible."""
    d = classify.classify([{"role": "user", "content": "explain gravity"}])
    assert d["took_us"] < 50_000, "classification should be well under 50ms"


def test_never_raises_on_junk():
    for junk in ([], [{}], [{"role": "user"}],
                 [{"role": "user", "content": None}],
                 [{"role": "user", "content": []}],
                 [{"role": "user", "content": "\x00�" * 50}]):
        assert classify.classify(junk)["lane"] in ORDER + [
            Lane.VISION, Lane.TOOLS]


def test_train_and_heldout_share_no_phrasing():
    """Guards the one property that makes this suite meaningful."""
    train = {t.strip().lower() for t, _ in TRAIN}
    held = {t.strip().lower() for t, _ in HELDOUT}
    assert not (train & held), f"leaked into HELDOUT: {train & held}"
