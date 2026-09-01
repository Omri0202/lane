"""
Tests for key handling.

The shape check exists because of a real failure: `getpass` on Windows
PowerShell swallowed a paste, a two-character key was stored, and `lane keys
set` reported success. Every later symptom pointed somewhere else — the proxy,
the model, the network — because the one broken component was the one claiming
to be fine.
"""

from __future__ import annotations

import pytest

from lane import keys

REAL_SHAPED = "gsk_" + "x" * 52


@pytest.mark.parametrize("value,reason", [
    ("", "empty"),
    ("gs", "the two-character key that actually got stored"),
    ("sk-ant-short", "plausible prefix, far too short"),
    ("gsk_abc def456ghi789jkl012mno345", "whitespace from a torn paste"),
])
def test_rejects_keys_that_cannot_be_real(value, reason):
    ok, problem = keys.looks_valid("groq", value)
    assert not ok, f"should have rejected: {reason}"
    assert problem, "a rejection must say why"


def test_accepts_a_real_shaped_key_silently():
    ok, problem = keys.looks_valid("groq", REAL_SHAPED)
    assert ok and not problem


def test_surrounding_whitespace_is_tolerated():
    """Copying from a .env file often brings a trailing newline."""
    ok, _ = keys.looks_valid("groq", f"  {REAL_SHAPED}\n")
    assert ok


def test_an_unexpected_prefix_warns_but_still_stores():
    """Prefixes change over time. A warning is right; a refusal would lock
    people out of a provider whose format moved on."""
    ok, problem = keys.looks_valid("anthropic", "sk-proj-" + "y" * 40)
    assert ok, "must not block a key just because the prefix is unfamiliar"
    assert "warning" in problem.lower()


def test_every_provider_has_what_the_cli_prints():
    for name, meta in keys.PROVIDERS.items():
        assert meta.get("env"), f"{name} needs an env var name"
        assert meta.get("name"), f"{name} needs a display name"
        assert meta.get("console", "").startswith("https://"), (
            f"{name} needs a console URL for `lane keys` to point at")


def test_masking_never_reveals_a_usable_key():
    masked = keys.mask(REAL_SHAPED)
    assert REAL_SHAPED not in masked
    assert len(masked) < len(REAL_SHAPED)
    assert keys.mask(None) == "—"
    assert "secret" not in keys.mask("secret").lower()
