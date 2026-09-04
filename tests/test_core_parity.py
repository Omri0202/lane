"""
Guards the generated JavaScript brain against drifting from the Python one.

The extension classifies in the browser so it needs no server, which means a
second copy of the classifier exists. Two copies of anything drift, and advice
that differs depending on which half of the product you asked is worse than
advice that is merely wrong — somebody would see one answer in the panel and a
different one from the proxy and stop believing either.

So the JavaScript is generated, and these tests check the generator: that the
regex flattening it performs is behaviour-preserving, that everything the
browser needs is actually in the file, and that the file on disk matches what
the current Python would produce. The end-to-end check that both brains agree
on every prompt runs in a browser at /dev/parity, which is the only place
JavaScript can actually be executed — it reported 317 of 317 matching.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "extension" / "core" / "lane-core.js"

sys.path.insert(0, str(ROOT / "tools"))
import build_core  # noqa: E402

from lane import catalog, classify, corpus, lanes  # noqa: E402


@pytest.fixture(scope="module")
def core() -> str:
    if not CORE.is_file():
        pytest.skip("run python tools/build_core.py first")
    return CORE.read_text(encoding="utf-8")


# ── the risky part: flattening re.X patterns ────────────────────────────────

VERBOSE = [
    ("CODE_REQ", classify._CODE_REQ),
    ("MATH", classify._MATH),
    ("IMAGE_REQ", classify._IMAGE_REQ),
    ("TRANSLATE_VERB", classify._TRANSLATE_VERB),
    ("LOOKUP", classify._LOOKUP),
    ("CODE_VERB", classify._CODE_VERB),
]


@pytest.mark.parametrize("name,pattern", VERBOSE, ids=[n for n, _ in VERBOSE])
def test_flattening_preserves_behaviour(name, pattern):
    """JavaScript has no verbose-regex flag, so the whitespace and comments
    have to be stripped. A mis-stripped character class would change the
    routing in a way no amount of reading the diff would catch."""
    flat = build_core.flatten_verbose(pattern.pattern)
    rebuilt = re.compile(flat, pattern.flags & ~re.X)
    samples = ([t for t, _ in corpus.TRAIN] + [t for t, _ in corpus.HELDOUT] +
               ["translate this bash script into powershell",
                "create a picture of Germany", "fix my sql join",
                "why does my binary search overflow",
                "```python\nprint(1)\n```",
                "Traceback (most recent call last):"])
    for text in samples:
        assert bool(pattern.search(text)) == bool(rebuilt.search(text)), \
            f"{name} changed behaviour on {text!r}"


def test_flattening_keeps_spaces_inside_character_classes():
    """A space inside [...] is a real character and must survive."""
    assert build_core.flatten_verbose("[a b]+ x") == "[a b]+x"


def test_flattening_keeps_escaped_spaces():
    assert build_core.flatten_verbose(r"a\ b  c") == r"a\ bc"


def test_flattening_drops_comments_outside_classes_only():
    assert build_core.flatten_verbose("ab  # a comment\ncd") == "abcd"
    assert build_core.flatten_verbose("[#a]b") == "[#a]b"


# ── the generated file carries everything the browser needs ─────────────────

def test_every_training_example_is_embedded(core):
    data = json.loads(re.search(r"const D = (\{.*?\});\n", core, re.S).group(1))
    assert len(data["TRAIN"]) == len(corpus.TRAIN)
    assert {l for _, l in data["TRAIN"]} == {l for _, l in corpus.TRAIN}


def test_every_model_is_embedded_with_its_prices(core):
    data = json.loads(re.search(r"const D = (\{.*?\});\n", core, re.S).group(1))
    by_id = {m["id"]: m for m in data["MODELS"]}
    assert set(by_id) == {m.id for m in catalog.all_models()}
    for m in catalog.all_models():
        js = by_id[m.id]
        assert js["in_price"] == m.in_price and js["out_price"] == m.out_price
        assert js["tier"] == m.tier and js["kind"] == m.kind
        assert js["strengths"] == list(m.strengths)


def test_every_lane_is_embedded(core):
    data = json.loads(re.search(r"const D = (\{.*?\});\n", core, re.S).group(1))
    assert set(data["LANES"]) == set(lanes.LANES)
    for name, spec in data["LANES"].items():
        assert spec["floor"] == lanes.floor(name)
        assert spec["needs"] == list(lanes.needs(name))
        assert spec["expected_output"] == lanes.expected_output(name)


def test_the_tuned_constants_travel_with_it(core):
    data = json.loads(re.search(r"const D = (\{.*?\});\n", core, re.S).group(1))
    assert data["CONFIDENT"] == classify.CONFIDENT
    assert data["UPBIAS"] == classify._UPBIAS
    assert data["LADDER"] == list(classify._LADDER)


def test_the_generated_file_is_current(core):
    """Fails when the Python has moved and nobody re-ran the generator.

    This is the whole safety net: without it, a corpus change ships to the
    proxy and not to the extension, and the two quietly start disagreeing.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_core.py")],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert CORE.read_text(encoding="utf-8") == core, (
        "lane-core.js is stale - run: python tools/build_core.py")


def test_it_carries_no_secrets_or_paths(core):
    """It ships to every user's browser. Nothing local belongs in it."""
    for leak in ("sk-ant-", "gsk_", "sk-proj-", "C:\\\\Users", "/home/",
                 "api_key", "Authorization"):
        assert leak not in core, f"{leak!r} found in the shipped core"


def test_the_extension_loads_the_core_before_the_panel():
    manifest = json.loads(
        (ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    js = manifest["content_scripts"][0]["js"]
    assert js.index("core/lane-core.js") < js.index("advisor.js")


def test_the_panel_does_not_require_a_server():
    """The point of the port. A host permission that is required rather than
    optional is a permission prompt standing between somebody and their first
    suggestion."""
    manifest = json.loads(
        (ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    assert "host_permissions" not in manifest
    assert manifest.get("optional_host_permissions")

    advisor = (ROOT / "extension" / "advisor.js").read_text(encoding="utf-8")
    assert "LaneCore.advise(" in advisor, "the panel must classify locally"


def test_design_system_is_mirrored_not_duplicated():
    """extension/ui.js is a copy of lane/web/ui.js, made by the build.

    Two files that must look identical will not stay identical if a person has
    to remember to change both. The panel and the setup page drifting a shade
    apart is exactly the "assembled rather than designed" problem the design
    system was written to end, so it is worth a test rather than a convention.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    canonical = (root / "lane" / "web" / "ui.js").read_text(encoding="utf-8")
    mirrored = (root / "extension" / "ui.js").read_text(encoding="utf-8")
    assert mirrored == canonical, (
        "extension/ui.js is stale - run tools/build_core.py")


def test_no_surface_defines_its_own_palette():
    """Colours are declared once, in ui.js, and nowhere else.

    A grep, because the failure mode is not a broken page - it is six pages
    that each still work and no longer match.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    surfaces = [
        root / "extension" / "advisor.js",
        root / "extension" / "search.js",
        root / "extension" / "popup.html",
        root / "extension" / "onboarding.html",
        root / "lane" / "web" / "chat.html",
        root / "lane" / "web" / "setup.html",
    ]
    offenders = []
    for path in surfaces:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        # Old-style tokens: --accent:, --ink:, --line: and friends, which is
        # what every surface used to carry its own version of.
        stray = re.findall(r"--(?:accent|ink|line|panel|faint|dim|bg|good)\s*:",
                           text)
        if stray:
            offenders.append(f"{path.name}: {len(stray)} local colour tokens")
    assert not offenders, "; ".join(offenders)
