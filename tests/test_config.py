"""
Tests for settings, and specifically for keeping the environment out of them.

The bug these exist for: `lane config <anything>` read the environment-merged
view of the settings and wrote the whole thing back, so exporting LANE_PORT for
one test permanently saved that port. The symptom arrived much later and looked
nothing like the cause — a server binding a port nobody had asked for, long
after the shell that set it had closed.
"""

from __future__ import annotations

import json

import pytest

from lane import config


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.delenv("LANE_PORT", raising=False)
    monkeypatch.delenv("LANE_HOST", raising=False)
    config.reload()
    yield tmp_path
    config.reload()


def saved(home) -> dict:
    return json.loads((home / "config.json").read_text(encoding="utf-8"))


# ── the bug ──────────────────────────────────────────────────────────────────

def test_an_env_port_is_never_written_to_the_file(home, monkeypatch):
    monkeypatch.setenv("LANE_PORT", "8099")
    config.reload()
    assert config.get("port") == 8099, "the override should apply while set"

    config.set("mode", "save")           # change something unrelated
    assert saved(home)["port"] == config.DEFAULTS["port"], (
        "the environment's port leaked into the saved file")


def test_an_env_host_is_never_written_to_the_file(home, monkeypatch):
    monkeypatch.setenv("LANE_HOST", "0.0.0.0")
    config.reload()
    config.set("mode", "save")
    assert saved(home)["host"] == config.DEFAULTS["host"]


def test_the_override_disappears_when_the_variable_does(home, monkeypatch):
    monkeypatch.setenv("LANE_PORT", "8099")
    config.reload()
    config.set("mode", "save")
    monkeypatch.delenv("LANE_PORT")
    config.reload()
    assert config.get("port") == config.DEFAULTS["port"], (
        "closing the shell should end the override")


def test_a_port_set_deliberately_does_persist(home):
    """The override must not become an excuse to ignore a real choice."""
    config.set("port", 9000)
    assert saved(home)["port"] == 9000
    config.reload()
    assert config.get("port") == 9000


def test_the_environment_still_wins_at_runtime(home, monkeypatch):
    config.set("port", 9000)
    monkeypatch.setenv("LANE_PORT", "8099")
    config.reload()
    assert config.get("port") == 8099
    assert saved(home)["port"] == 9000, "the saved choice is untouched"


# ── ordinary behaviour ───────────────────────────────────────────────────────

def test_settings_round_trip(home):
    config.set("baseline_model", "claude-sonnet-5")
    config.reload()
    assert config.get("baseline_model") == "claude-sonnet-5"


def test_unknown_settings_are_refused(home):
    with pytest.raises(KeyError):
        config.set("favourite_colour", "blue")


def test_a_corrupt_file_falls_back_to_defaults_rather_than_crashing(home):
    (home / "config.json").write_text("{ not json", encoding="utf-8")
    config.reload()
    assert config.get("mode") == config.DEFAULTS["mode"]


def test_unknown_keys_in_the_file_are_ignored(home):
    (home / "config.json").write_text(
        json.dumps({"mode": "save", "leftover": 1}), encoding="utf-8")
    config.reload()
    assert config.get("mode") == "save"
    assert "leftover" not in config.all()


def test_coerce_turns_cli_strings_into_the_right_types():
    assert config.coerce("port", "9000") == 9000
    assert config.coerce("report_headers", "false") is False
    assert config.coerce("report_headers", "yes") is True
    assert config.coerce("audit_sample_rate", "0.02") == pytest.approx(0.02)
    assert config.coerce("disabled_providers", "a, b") == ["a", "b"]
