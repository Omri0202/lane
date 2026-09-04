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
