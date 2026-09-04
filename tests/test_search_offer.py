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
import re

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


def test_the_query_is_read_from_typing_and_the_url_never_scraped():
    """Two sources, neither of them the results markup.

    While somebody types, the query comes from the input event itself; on a
    page they arrived at already, from ?q=. Scraping the DOM for it would be a
    standing bet on Google's markup, and the card would break silently the week
    they change it.
    """
    src = read("search.js")
    assert "URLSearchParams(location.search)" in src
    assert 'document.addEventListener("input"' in src
    # The only DOM queries are inside the card's own shadow root.
    for line in src.splitlines():
        if "querySelector" in line:
            assert "root." in line, f"queries the host page: {line.strip()}"


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

    # Homepages are included on purpose: the card appears WHILE the query is
    # typed, and on Google that typing starts on the front page. What matters
    # is that the two scripts never overlap.
    engines = ("//www.google.", "//www.bing.com", "//duckduckgo.com",
               "//search.brave.com", "//www.ecosia.org")
    for m in search[0]["matches"]:
        assert any(e in m for e in engines), m

    # The two must not overlap. Note that gemini.google.com is a CHAT site the
    # panel owns — matching engines on the substring "google." would have
    # claimed it, which is the bug this pins down.
    chat = ("claude.ai", "chatgpt.com", "chat.openai.com", "gemini.google.com")
    assert not any(c in m for c in chat for m in search[0]["matches"])
    assert not any(e in m for e in engines for m in panel[0]["matches"])


def test_gemini_is_a_chat_site_not_a_search_engine():
    """gemini.google.com contains "google." and is not Google. The host check
    is anchored so the search card can never appear over the chat panel."""
    src = read("search.js")
    assert "ENGINE_HOSTS" in src
    assert 'includes("google."' not in src
    assert "^(www\\.)?google" in src


def test_it_does_not_claim_a_prefill_it_cannot_do():
    """Claude and ChatGPT accept ?q=; Gemini has no documented equivalent, so
    the query is copied and the card says so rather than dropping it."""
    src = read("search.js")
    assert "PREFILLS" in src
    assert "gemini: false" in src
    # The row itself has to say so. Arriving at an empty box wondering where
    # your question went is worse than being told to paste it.
    assert "copied" in src and "paste it in" in src


def test_it_never_sends_the_query_anywhere():
    """It reads what somebody typed into a search box. That must not leave the
    machine, and the only network call in the file should be opening a tab."""
    src = read("search.js")
    assert "fetch(" not in src
    assert "XMLHttpRequest" not in src


def test_the_card_is_looked_at_while_typing_continues():
    """A trailing debounce alone never fires before Enter.

    It resets on every keystroke, so it only runs once typing STOPS - and
    nobody stops before pressing Enter. The card would therefore only ever be
    seen on the results page, which is exactly the moment it is useless: the
    search has been run and the choice already made. There has to be a
    ceiling on the wait as well as a delay after it.
    """
    src = (EXT / "search.js").read_text(encoding="utf-8")
    assert "MAX_WAIT_MS" in src, "no ceiling on the debounce"
    assert "now - lastLook >= MAX_WAIT_MS" in src
    ceiling = int(re.search(r"MAX_WAIT_MS = (\d+)", src).group(1))
    delay = int(re.search(r"DEBOUNCE_MS = (\d+)", src).group(1))
    # Long enough not to run on every keystroke, short enough that a card
    # appears while there are still words left to type.
    assert delay < ceiling <= 800, (delay, ceiling)


def test_the_card_says_enter_still_searches():
    """The reason a card like this gets dismissed unread is the fear that it
    has taken the keyboard away. Saying so costs one line."""
    src = (EXT / "search.js").read_text(encoding="utf-8")
    assert "still searches" in src
    assert "<kbd>Enter</kbd>" in src
