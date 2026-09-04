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
    # The clipboard is a third line of defence now, not the mechanism. What
    # must hold is that the question actually travels.
    assert "handOver(site, q)" in src, "the question is not handed over"
    assert "HANDOFF_KEY" in src


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


# ── the world does not search in English ─────────────────────────────────────

FOREIGN = [
    # language, query, the lane it must land in
    ("hebrew",   "למה הפונקציה "
                 "הרקורסיבית "
                 "שלי איטית", "reasoning"),
    ("hebrew",   "תרגם את זה "
                 "לאנגלית", "translate"),
    ("hebrew",   "כתוב לי מכתב "
                 "מוטיבציה", "longform"),
    ("arabic",   "لماذا الدالة "
                 "بطيئة جدا", "reasoning"),
    ("russian",  "почему моя "
                 "функция такая "
                 "медленная", "reasoning"),
    ("japanese", "再帰関数が遅いのは"
                 "なぜですか", "reasoning"),
    ("chinese",  "为什么我的递归函数"
                 "这么慢", "reasoning"),
    ("korean",   "왜 내 재귀 함수가 "
                 "느린가요", "reasoning"),
    ("greek",    "γιατί η συνάρτηση "
                 "είναι αργή", "reasoning"),
]


@pytest.mark.parametrize("language,query,expected", FOREIGN,
                         ids=[f"{a}-{c}" for a, _, c in FOREIGN])
def test_it_is_not_silent_outside_the_latin_alphabet(language, query, expected):
    """The tokenizer is [a-z']+, and an empty feature vector does not abstain.

    It lands on the sparsest centroid, which is trivial, so every request in
    Hebrew, Arabic, Cyrillic, Greek, Devanagari, Thai, Kana, Han or Hangul was
    classified as a one-word lookup and the offer suppressed. Half the world
    got a product that was silent by construction and looked merely broken.
    """
    from lane import classify as pyclassify
    got = pyclassify.classify([{"role": "user", "content": query}])
    assert got["lane"] == expected, (language, got["lane"], got["reason"])


def test_a_short_foreign_lookup_still_says_nothing():
    """The fix must not turn into a card on every keystroke in Hebrew.

    Navigation and two-word lookups are the search engine's job in every
    language, and an extension that interrupts all of them gets uninstalled in
    a day.
    """
    from lane import classify as pyclassify
    for query in ("יוטיוב",             # youtube
                  "מזג אוויר"):  # weather
        got = pyclassify.classify([{"role": "user", "content": query}])
        assert got["lane"] in ("trivial", "simple", "web_search"), (query, got)


def test_the_offer_gate_counts_words_the_way_the_brain_does():
    """Japanese and Chinese put no spaces in.

    Splitting on whitespace calls every sentence one word long, so the gate
    rejected them all - the lane was right and the card never appeared anyway.
    """
    src = (EXT / "search.js").read_text(encoding="utf-8")
    assert "LaneCore.foreignLength(q)" in src
    assert r"q.split(/\s+/).filter(Boolean).length" not in src


def test_turning_the_offer_off_can_be_undone():
    """It wrote a flag nothing could clear.

    One click - possibly a mis-click - and the search card was dead for good;
    reinstalling would not fix it, because extension storage survives that,
    and no screen mentioned the setting existed. A switch that only goes one
    way is not a preference.
    """
    popup = ((EXT / "popup.html").read_text(encoding="utf-8")
             + (EXT / "popup.js").read_text(encoding="utf-8"))
    assert "lane.searchOffer" in popup, "the launcher cannot see the flag"
    assert 'id="offers"' in popup
    # And it must write the cleared value, not only the off one.
    assert "on ? {} : { off: true }" in popup



def test_the_tab_is_opened_before_anything_is_awaited():
    """Chrome permits window.open only while a user activation is live.

    Awaiting a promise spends it. Gemini is the only site with no prefill
    parameter, so it was the only one that awaited the clipboard before
    opening - and therefore the only one where the popup was blocked and the
    click did nothing at all. Claude and ChatGPT skipped that await, which is
    exactly why they worked and it did not.
    """
    src = (EXT / "search.js").read_text(encoding="utf-8")
    body = src[src.index('root.querySelectorAll(".pick")'):]
    body = body[:body.index("\n    }")]
    opened = body.index("window.open")
    assert "await" not in body[:opened], (
        "something is awaited before the tab is opened; Chrome will block it")


def test_the_question_arrives_typed_rather_than_pasted():
    """"Copied - paste it in" is not continuing somebody's question.

    There is a content script on all three sites already, so the query is
    handed over through extension storage and typed into the composer on
    arrival - and typed, not assigned, because every one of these composers is
    driven by a framework that tracks its own state. Setting .value behind its
    back leaves the words on screen and the send button disabled.
    """
    src = (EXT / "advisor.js").read_text(encoding="utf-8")
    assert "collectHandoff" in src and "fillComposer" in src
    assert "HTMLTextAreaElement.prototype" in src, "assigns .value directly"
    assert "insertText" in src, "no path for a contenteditable composer"
    assert "HANDOFF_TTL" in src, "a stale question could be picked up"


def test_every_site_you_use_gets_a_row():
    """The card kept only the winners, and one site can hold both.

    ChatGPT does, for anything long: GPT-5 mini is the cheapest thing that
    clears most floors and GPT-5 tops the tier table. So the card showed two
    ChatGPT rows and Claude and Gemini vanished without a word - and somebody
    who uses Gemini reasonably concluded Gemini was broken.
    """
    src = (EXT / "search.js").read_text(encoding="utf-8")
    body = src[src.index("function picks("):src.index("// ── the card")]
    assert "for (const e of perSite) add(e.site, e.cheap, null)" in body, (
        "sites that won nothing are still dropped")
    # And the badges are on picks, not sites: the same site holding both with
    # two different models has to produce two rows, or one of them names a
    # model whose price belongs to the other.
    assert 'add(cheapest.site, cheapest.cheap, "cheapest")' in body
    assert 'add(strongest.site, strongest.best, "best")' in body
    assert 'seen.has(key)' in body, "a pick could be listed twice"


def test_a_row_never_quotes_one_model_and_names_another():
    """Every row carries its own recommendation and its own price."""
    src = (EXT / "search.js").read_text(encoding="utf-8")
    row = src[src.index("const row = (pick)"):]
    row = row[:row.index("};")]
    for field in ("pick.rec.display", "pick.rec.cost", "pick.site"):
        assert field in row, field


def test_every_site_has_a_mark_and_it_is_drawn_not_fetched():
    """A content script cannot load an image from a CDN.

    No network on somebody else's page, and the card has to render with the
    connection down - so the marks are inline SVG. They are simplified on
    purpose: a traced trademark at 17px is no more recognisable than a clean
    glyph in the right colour, and the first attempt at OpenAI's rosette
    collapsed into something that read as a settings cog.
    """
    ui = (EXT / "ui.js").read_text(encoding="utf-8")
    assert "const brands = {" in ui
    for provider in ("anthropic", "openai", "google"):
        assert f"{provider}: {{" in ui, provider
    # Drawn, not linked.
    block = ui[ui.index("const brands = {"):ui.index("/* For ordinary pages")]
    assert "<svg" in block
    assert "http" not in block, "a mark is being fetched from somewhere"
    # And each needs a colour for both grounds: a black mark vanishes on black.
    assert block.count("on:") == 3 and block.count("dark:") == 3


def test_the_row_carries_the_mark_of_the_service_it_opens():
    src = (EXT / "search.js").read_text(encoding="utf-8")
    assert "LaneUI.brands[PROVIDER[pick.site]]" in src
    assert "l-row__brand" in src
    # Every site the card can offer must map to a provider that has one.
    for site in ("claude", "chatgpt", "gemini"):
        assert site in src.split("const PROVIDER =")[1][:160], site
