"""
Tests for the capability lanes — the ones that are about what a model CAN do
rather than how well it does it.

Every lane in the original set degrades gracefully when the classification is a
little off: a slightly-too-cheap chat model still produces an answer. These
three do not. A chat model asked for a picture produces no picture. A model
without web access answers a question about today from a stale memory, and
does it confidently. So detection here is deterministic, and the interesting
cases are all near-misses that must NOT fire.
"""

from __future__ import annotations

import pytest

from lane import classify, lanes, policy
from lane.catalog import Model
from lane.lanes import Lane

# ── translate vs porting code ────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "translate this paragraph into spanish",
    "how do you say thank you in japanese",
    "say that in hebrew",
    "whats the polish word for bread",
    "put this in german for me",
    "i need the whole thing in arabic",
    "translate from russian to english",
])
def test_translation_between_human_languages(text):
    assert classify.classify([{"role": "user", "content": text}])["lane"] \
        == Lane.TRANSLATE


@pytest.mark.parametrize("text", [
    "translate this bash script into powershell",
    "convert this python function to javascript",
    "translate this sql query into an orm call",
    "port this module from java to kotlin",
    "rewrite these bash commands for powershell",
])
def test_porting_code_is_reasoning_not_translation(text):
    """Same verb, entirely different job.

    This is guarded in two places on purpose. The tier 0 rule refuses it
    because a programming language is named, and the same veto is applied
    again after tier 1 — which had learned "translate" as a strong token and
    was overturning the rule. A statistical hunch must not beat a fact.
    """
    assert classify.classify([{"role": "user", "content": text}])["lane"] \
        == Lane.REASONING


def test_translation_needs_a_language_to_be_named():
    """Without one there is nothing to translate into, so it is not a
    translation request — it is somebody using the word."""
    d = classify.classify([{"role": "user",
                            "content": "this translation reads badly"}])
    assert d["lane"] != Lane.TRANSLATE


# ── web search vs words that merely sound current ────────────────────────────

@pytest.mark.parametrize("text", [
    "what is the latest news about the election",
    "search the web for reviews of this laptop",
    "current price of bitcoin",
    "who won the match last night",
    "todays exchange rate for the shekel",
    "whats happening in the markets today",
    "google it for me",
])
def test_live_information_requests(text):
    assert classify.classify([{"role": "user", "content": text}])["lane"] \
        == Lane.WEB_SEARCH


@pytest.mark.parametrize("text", [
    "why does my binary search overflow",
    "how does binary search work",
    "show me the latest commit on that branch",
    "what is the current value of this variable",
    "what language do they speak in brazil",
])
def test_the_words_that_only_sound_like_lookups(text):
    """"search", "latest" and "current" all mean something else in a
    developer's mouth. A bare keyword match sent "why does my binary search
    overflow" to the web lane in an earlier router."""
    assert classify.classify([{"role": "user", "content": text}])["lane"] \
        != Lane.WEB_SEARCH


# ── capability is a hard filter ──────────────────────────────────────────────

BLIND_TO_WEB = Model(id="noweb", provider="p", display="No Web", tier=99,
                     in_price=0.01, out_price=0.02, context=200_000,
                     max_output=8192, web=False)
CAN_SEARCH = Model(id="web", provider="p", display="Searcher", tier=62,
                   in_price=5.0, out_price=25.0, context=200_000,
                   max_output=8192, web=True)


def test_a_model_that_cannot_search_never_serves_a_lookup():
    """BLIND_TO_WEB is the strongest and nearly free, so every mode would take
    it on price or tier. It cannot look anything up, and the strongest model
    answering from a stale memory is worse than a weak one that can search."""
    for mode in ("save", "balanced", "performance"):
        d = policy.choose(Lane.WEB_SEARCH, mode=mode,
                          models=[BLIND_TO_WEB, CAN_SEARCH])
        assert d.model is CAN_SEARCH, f"{mode} picked a model with no web access"


def test_translate_sits_below_longform_on_the_capability_ladder():
    """The whole reason translate is its own lane: the gap between models is
    small there, so it should not inherit long-form's floor."""
    assert lanes.floor(Lane.TRANSLATE) < lanes.floor(Lane.LONGFORM)


def test_every_lane_is_ordered_by_demand():
    """ORDER drives the under-routing guard. A lane missing from it silently
    ranks as the most demanding of all, because the lookup falls off the end."""
    text_lanes = {n for n, spec in lanes.LANES.items()
                  if spec.get("kind", "chat") == "chat"
                  and not spec["needs"]} | {Lane.WEB_SEARCH}
    missing = text_lanes - set(lanes.ORDER)
    assert not missing, f"not ranked for demand: {missing}"

    floors = [lanes.floor(n) for n in lanes.ORDER]
    assert floors == sorted(floors), (
        f"ORDER disagrees with the capability floors: "
        f"{list(zip(lanes.ORDER, floors))}")


def test_expected_output_is_set_for_every_lane():
    """Cost estimates multiply by this. A lane missing from the table would be
    silently priced at the default and report the wrong saving."""
    for name in lanes.LANES:
        assert name in lanes.EXPECTED_OUTPUT, f"{name} has no output estimate"
