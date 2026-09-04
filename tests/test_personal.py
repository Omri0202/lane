"""
Tests for the personal layer: the interview, the profile, and the launcher.

These are structural rather than behavioural — the pages are JavaScript and
only a browser can run them, so what is checked here is that the pieces exist,
are wired together, and cannot leak. The behaviour was driven in a browser:
the five questions store a profile, the launcher orders its shortcuts by the
answers, and a request none of the chosen sites can serve names one that can.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))


def read(name: str) -> str:
    """A surface's markup and its behaviour, together.

    MV3 refuses inline <script>, so every page's JS lives in a file beside it.
    These tests are about what a surface does, not which of its two files a
    line ended up in, so they get both.
    """
    text = (EXT / name).read_text(encoding="utf-8")
    if name.endswith(".html"):
        script = EXT / (name[:-5] + ".js")
        if script.is_file():
            text += "\n" + script.read_text(encoding="utf-8")
    return text


def test_no_extension_page_runs_an_inline_script():
    """An extension page runs under `script-src 'self'`.

    A <script> with a body in it is refused, and refused quietly: the markup
    renders, the handlers never attach, and the page looks merely inert. This
    is a grep because the symptom gives no clue as to the cause.
    """
    for page in EXT.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        for chunk in html.split("<script")[1:]:
            head, _, body = chunk.partition(">")
            assert "src=" in head, (
                f"{page.name} has an inline <script>; MV3 will refuse it")
            assert not body.split("</script")[0].strip(), page.name


# ── the interview is reachable, and only when it should be ───────────────────

def test_the_interview_opens_on_install_only(manifest):
    """Reopening a setup page after every version bump is how an extension
    teaches people to uninstall it."""
    bg = read("background.js")
    assert 'details.reason !== "install"' in bg
    assert "onboarding.html" in bg
    assert manifest["background"]["service_worker"] == "background.js"


def test_the_interview_is_also_the_options_page(manifest):
    """Somebody who skipped a question needs a way back that is not a
    reinstall."""
    assert manifest["options_page"] == "onboarding.html"


def test_the_launcher_is_the_toolbar_action(manifest):
    assert manifest["action"]["default_popup"] == "popup.html"


def test_every_page_loads_the_core_and_the_profile():
    for page in ("onboarding.html", "popup.html"):
        html = read(page)
        assert "core/lane-core.js" in html, page
        assert "profile.js" in html, page


def test_the_content_scripts_load_in_dependency_order(manifest):
    js = manifest["content_scripts"][0]["js"]
    assert js.index("core/lane-core.js") < js.index("profile.js") < js.index("advisor.js")


# ── the profile ──────────────────────────────────────────────────────────────

def test_the_profile_has_a_default_for_everything():
    """A missing answer must never leave a field undefined — the panel reads
    these on every keystroke."""
    src = read("profile.js")
    block = re.search(r"const DEFAULT = \{(.*?)\n  \};", src, re.S).group(1)
    for field in ("onboarded", "sites", "models", "favourites", "focus",
                  "variation"):
        assert f"{field}:" in block, field


def test_an_unreadable_profile_does_not_stop_the_panel():
    """Storage can fail, and a tool that breaks when its preferences do is a
    tool that breaks."""
    src = read("profile.js")
    assert "catch" in src
    assert "Object.assign({}, DEFAULT)" in src


def test_empty_models_means_everything_not_nothing():
    """The distinction the panel depends on to say 'assuming you can use every
    Claude model' rather than silently advising over an empty set."""
    src = read("profile.js")
    assert "profile.models.length" in src
    assert "null" in src.split("function allowed")[1][:400]


def test_favourites_drop_out_when_the_model_does():
    """Starring a model and later unticking it must not keep offering it."""
    src = read("profile.js")
    body = src.split("function favourites")[1][:400]
    assert "allowed(profile)" in body and "includes" in body


def test_nothing_is_sent_anywhere():
    """No account, no sync, no telemetry. The whole personal layer is local,
    and that is a promise the code has to keep, not the README."""
    src = read("profile.js")
    assert "fetch(" not in src
    assert "http" not in src.replace("https://", "")


# ── the interview asks what it claims to ─────────────────────────────────────

def test_the_interview_covers_the_five_questions():
    html = read("onboarding.html")
    for marker in ("Which of these do you actually use",
                   "Which models can you pick",
                   "Star the ones you reach for",
                   "What do you mostly do",
                   "cheap or best"):
        assert marker in html, marker


def test_every_question_can_be_skipped():
    """An interview that must be completed is one people abandon, leaving a
    half-configured tool that gives confident wrong advice."""
    assert 'id="skip"' in read("onboarding.html")


def test_ticking_everything_stores_no_restriction():
    """An explicit list identical to the catalog goes stale the next time a
    model is added."""
    html = read("onboarding.html")
    assert "on.length === boxes.length ? [] : on" in html


def test_the_interview_does_not_demand_api_keys():
    """Keys are for the optional proxy. Asking for one before somebody has
    seen a single suggestion is the barrier this whole layer removes."""
    # Collapsed, because whether a promise falls across a line break in the
    # source is not something a test should have an opinion about.
    html = re.sub(r"\s+", " ", read("onboarding.html"))
    assert "no API key" in html
    # And no command either: the last screen used to end by naming one, which
    # reads as a catch however carefully it is hedged.
    assert "lane serve" not in html
    assert "no server" in html


# ── the launcher ─────────────────────────────────────────────────────────────

def test_the_launcher_only_suggests_sites_they_chose():
    src = read("popup.html")
    assert "profile.sites.length ? profile.sites" in src


def test_the_launcher_names_a_site_that_can_when_theirs_cannot():
    src = read("popup.html")
    assert "None of your sites can do this" in src
    assert "elsewhere" in src


def test_the_launcher_orders_shortcuts_by_their_answers():
    src = read("popup.html")
    assert "profile.focus.length ? profile.focus" in src


def test_the_launcher_offers_favourites_as_one_click():
    assert "data-open=" in read("popup.html")


# ── the panel uses the profile ───────────────────────────────────────────────

def test_the_panel_reads_the_profile_before_advising():
    src = read("advisor.js")
    assert "LaneProfile.load()" in src
    assert "LaneProfile.allowed(profile)" in src


def test_the_panel_offers_favourites_regardless_of_the_verdict():
    """The advice is a recommendation, not a ruling. Having to go around the
    panel to disagree with it is how a panel gets dismissed."""
    src = read("advisor.js")
    assert "function favouriteRow" in src
    assert "LaneProfile.favourites(profile)" in src


def test_a_local_server_never_overrides_what_they_answered():
    src = read("advisor.js")
    assert "state.explicit_selection && !allowedModels" in src


# ── the restriction applies only to what was asked about ─────────────────────

def test_a_chat_model_selection_does_not_hide_image_models():
    """The bug this caught: the interview only ever offers chat models, so the
    resulting list said nothing about image generators — yet it was filtering
    them out, and "create a picture" reported that none of their sites could do
    it while listing one of their own sites as the place to go.
    """
    core = (EXT / "core" / "lane-core.js").read_text(encoding="utf-8")
    assert "The restriction applies only to the KIND" in core
    assert "kinds.has(m.kind" in core


def test_a_panel_that_renders_can_also_be_clicked():
    """The host is a fixed box with pointer-events:none. The card undoes it.

    Both content scripts mount into a fixed-position host sized to the card's
    column, and set pointer-events:none on it so it does not swallow clicks
    meant for the page behind it. Something then has to hand clicks back, or
    the result is a panel that renders perfectly, animates, updates as you
    type, and ignores every button on it - which is exactly what shipped when
    a redesign dropped one line from one stylesheet.

    The rule lives in ui.js now so no surface can own it badly; this checks
    the pairing rather than the line.
    """
    ui = (EXT / "ui.js").read_text(encoding="utf-8")
    card = ui[ui.index(".l-card {"):]
    assert "pointer-events: auto" in card[:card.index("}")], (
        ".l-card no longer takes clicks")

    for name in ("advisor.js", "search.js"):
        src = (EXT / name).read_text(encoding="utf-8")
        if "pointer-events:none" not in src.replace(" ", ""):
            continue
        assert "l-card" in src, (
            f"{name} blocks pointer events but mounts no card that restores them")


# ── what a model costs the person in front of it ─────────────────────────────

def test_every_model_says_whether_it_costs_extra():
    """Per-token price answers "which is cheaper".

    It does not answer the question somebody has when a panel says "use Claude
    Fable 5", which is whether they can click that or whether it wants their
    credit card. Those are different facts and the second decides whether the
    advice is usable at all.
    """
    import sys
    sys.path.insert(0, str(ROOT))
    from lane import catalog
    for m in catalog.all_models():
        assert m.plan in ("free", "paid"), (m.id, m.plan)
    free = [m for m in catalog.all_models() if m.plan == "free"]
    assert free, "no model is reachable without paying, which cannot be right"
    # One free chat model per consumer site, or the panel has nothing to say
    # to somebody who has not paid.
    for provider in ("anthropic", "openai", "google"):
        assert any(m.provider == provider and m.kind == "chat"
                   for m in free), provider


def test_a_new_profile_is_offered_only_what_it_can_use():
    """Default off, because the alternative is a panel that confidently tells
    somebody on a free plan to use a model they will meet a paywall behind -
    and the only way to find that out is to click it."""
    src = read("profile.js")
    block = re.search(r"const DEFAULT = \{(.*?)\n  \};", src, re.S).group(1)
    assert re.search(r"paid:\s*false", block), "paid models are on by default"
    # And allowed() has to actually apply it, not just store it.
    body = src.split("function allowed")[1][:700]
    assert "profile.paid" in body and 'plan !== "paid"' in body


def test_the_panel_names_the_paid_model_it_is_holding_back():
    """Filtering paid models out silently turns the panel into a liar by
    omission: it would recommend second best with no hint that a trade was
    made on somebody's behalf."""
    src = read("advisor.js")
    assert "allowedIgnoringCost" in src, "it never works out what it is hiding"
    assert "withPaid" in src
    # The wording follows the reason: a paid model is sometimes stronger and
    # sometimes just cheaper, and calling a nano model a better fit for a
    # recall question is nonsense somebody will notice.
    assert "fit this better" in src and "cost less" in src
    assert 'id="showPaid"' in src, "no way to change your mind"


def test_a_paid_model_is_labelled_wherever_it_is_named():
    for name in ("advisor.js", "search.js", "onboarding.js"):
        src = (EXT / name).read_text(encoding="utf-8")
        assert "costs extra" in src, name


def test_the_page_is_clicked_the_way_a_mouse_clicks_it():
    """el.click() fires one untrusted `click` and nothing else.

    Claude, ChatGPT and Gemini all build their model pickers on headless
    component libraries whose menus open on POINTERDOWN and whose items commit
    on mousedown. None of those handlers ever sees a bare click, so the menu
    never opens and the panel reports the model is "not in this page's list"
    while the list sits there unopened. Reproduced in the dev harness, whose
    picker is pointerdown-driven for exactly this reason.
    """
    src = read("advisor.js")
    for event in ("pointerdown", "mousedown", "pointerup", "mouseup"):
        assert event in src, event
    # And the real sequence must be what applyModel uses.
    assert "realClick(picker.el)" in src
    assert "picker.el.click();" not in src


# ── a model that is offered has to be switchable ─────────────────────────────

def test_a_site_is_not_offered_a_model_its_menu_has_never_had():
    """GPT-5 nano and GPT-4.1 mini are API-only.

    They are real models at real prices that nobody will ever find on
    chatgpt.com, so recommending one there is advice that cannot be taken:
    the panel says use this, the person goes looking, and it is not there.
    """
    import sys
    sys.path.insert(0, str(ROOT))
    from lane import catalog
    api_only = {m.id for m in catalog.all_models() if not m.picker}
    assert "gpt-5-nano" in api_only
    assert "gpt-4.1-mini" in api_only
    assert "gemini-2.5-flash-lite" in api_only
    # An image model IS offered by the site - you ask for a picture and get
    # one - it simply is not in the model menu. Those are different questions.
    for m in catalog.all_models():
        if m.kind == "image":
            assert m.picker, m.id


def test_a_model_is_not_mistaken_for_its_smaller_sibling():
    """"gpt 5" is a substring of "gpt 5 mini".

    Every containment test says one is the other, so a picker sitting on GPT-5
    reported it was already on GPT-5 mini and the panel congratulated itself
    without switching anything. The size qualifiers have to match as a set.
    """
    src = read("advisor.js")
    assert "QUALIFIERS" in src
    for word in ("mini", "nano", "lite", "pro", "flash", "thinking"):
        assert f'"{word}"' in src, word
    # And the containment shortcut that caused it must be gone.
    assert "a.includes(b) || b.includes(a)" not in src


def test_the_button_asks_the_page_before_promising_a_switch():
    """A page with no model menu cannot switch models.

    Finding that out after the click means the panel had already promised.
    """
    src = read("advisor.js")
    use = src[src.index('id="use"') - 400:src.index('id="use"')]
    assert "findPicker()" in use, "the switch is offered without checking"
    assert 'id="copy"' in src, "nothing honest is offered in its place"


def test_a_switch_that_fails_produces_a_suggestion_that_works():
    """The catalog is a good guess about a site's menu and only a guess.

    Menus differ by plan, by region, by whatever is rolling out this week. A
    failure is evidence, so the model is struck off for this page and the
    advice recomputed - the second line is something that works rather than an
    apology.
    """
    src = read("advisor.js")
    assert "missingHere" in src
    assert "withoutMissing" in src
    # Both failure modes, because from where somebody is sitting they are one
    # thing: the panel offered a model and the model did not happen.
    assert "not in this page|did not switch" in src
