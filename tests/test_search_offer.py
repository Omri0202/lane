"""
Tests for the search offer, which is mostly a test of when it shuts up.

A card on every Google search is adware and gets the extension uninstalled
inside a day. The value is entirely in the restraint: the offer has to appear
for the handful of searches a model genuinely answers better and stay invisible
for the very many it does not.

The gate itself is JavaScript, so what is asserted here is the classification
underneath it — the same Python classifier the extension is generated from —
plus the structural promises of the content script. The gate was driven in a
browser over the queries below: eight silent, four offered.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from lane import classify
from lane.lanes import Lane

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"


def lane_of(text: str) -> str:
    return classify.classify([{"role": "user", "content": text}])["lane"]


def would_offer(q: str) -> bool:
    """The gate from search.js, in Python, over the same classifier."""
    import re
    words = [w for w in q.split() if w]
    if len(words) < 4:
        return False
    if re.match(r"^\w+://", q) or re.match(
            r"^[\w-]+\.(com|org|net|io|ai|co\.uk)\b", q, re.I):
        return False
    lane = lane_of(q)
    if lane == Lane.WEB_SEARCH:
        return False
    if lane == Lane.TRIVIAL:
        return False
    if lane == Lane.SIMPLE and len(words) < 9:
        return False
    return True


# ── it must stay quiet ───────────────────────────────────────────────────────

@pytest.mark.parametrize("query,why", [
    ("facebook", "navigation"),
    ("weather", "navigation"),
    ("npm install react", "short, and they want the docs"),
    ("stackoverflow.com", "a domain, not a question"),
    ("https://example.com/docs", "a URL"),
    ("thanks", "nothing to answer"),
    ("capital of peru", "Google puts this in a box at the top"),
    ("bbc news", "navigation"),
])
def test_it_says_nothing(query, why):
    assert not would_offer(query), f"{query!r} should be silent - {why}"


@pytest.mark.parametrize("query", [
    "what is the latest news about the election",
    "current price of bitcoin",
    "todays exchange rate for the shekel",
    "who won the match last night",
])
def test_it_never_competes_with_the_search_engine_on_live_information(query):
    """The one case where the engine is right and a model is wrong.

    A model would answer these from a stale memory while the real answer sits
    on the page behind the card. Offering here would not merely be noise, it
    would be advice to get a worse answer.
    """
    assert lane_of(query) == Lane.WEB_SEARCH
    assert not would_offer(query)


# ── and speak when it should ────────────────────────────────────────────────

@pytest.mark.parametrize("query,expected", [
    ("why does my docker container exit immediately on startup", Lane.REASONING),
    ("draft an email to my landlord about the broken heating", Lane.LONGFORM),
    ("translate this paragraph into spanish for me", Lane.TRANSLATE),
    ("explain how compound interest works with an example", Lane.GENERAL),
    ("create a picture of a dog on a beach please", Lane.IMAGE_GEN),
])
def test_it_offers_where_a_model_is_genuinely_better(query, expected):
    assert lane_of(query) == expected
    assert would_offer(query), f"{query!r} should have been offered"


# ── the script's promises ───────────────────────────────────────────────────

def read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_the_query_comes_from_the_url_not_the_page():
    """Reading ?q= needs no access to the results and survives every redesign
    of them. Scraping the DOM would be a standing bet on Google's markup."""
    src = read("search.js")
    assert "URLSearchParams(location.search)" in src
    assert "querySelector" not in src.split("function render")[0]


def test_it_can_be_turned_off_permanently():
    """Somebody who does not want this must be able to say so once."""
    src = read("search.js")
    assert "Never on searches" in src
    assert "dismissed.off" in src


def test_it_is_a_separate_content_script_with_narrow_matches():
    """The panel has no business loading on a search page, and this has none
    on claude.ai. Narrow matches are also the first thing a store reviewer
    reads."""
    manifest = json.loads(read("manifest.json"))
    scripts = manifest["content_scripts"]
    search = [cs for cs in scripts if "search.js" in cs["js"]]
    panel = [cs for cs in scripts if "advisor.js" in cs["js"]]
    assert len(search) == 1 and len(panel) == 1
    assert search[0] is not panel[0]
    for m in search[0]["matches"]:
        assert "search" in m or "duckduckgo" in m, m
    assert not any("claude.ai" in m for m in search[0]["matches"])


def test_it_does_not_claim_a_prefill_it_cannot_do():
    """Claude and ChatGPT accept ?q=; Gemini has no documented equivalent, so
    the query is copied and the card says so rather than dropping it."""
    src = read("search.js")
    assert "PREFILLS" in src
    assert "gemini: false" in src
    assert "copied" in src


def test_it_never_sends_the_query_anywhere():
    """It reads what somebody typed into a search box. That must not leave the
    machine, and the only network call in the file should be opening a tab."""
    src = read("search.js")
    assert "fetch(" not in src
    assert "XMLHttpRequest" not in src
