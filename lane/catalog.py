"""
catalog.py — the model table, and the truth-maintenance around it.

A hard-coded price list starts rotting the day it ships. Model ids change,
prices drop, whole families are retired. So the catalog is built in three
layers, each able to correct the one below it:

  1. models.json          — shipped with the package, editable but replaced on
                            upgrade.
  2. ~/.lane/models.local.json  — the user's own entries and overrides, merged
                            by id, never touched by an upgrade.
  3. ~/.lane/unavailable.json   — ids that the provider's own /v1/models list
                            did not contain the last time `lane models --sync`
                            ran. These are hidden from routing rather than
                            deleted, because a key without access to a model is
                            a fact about the key, not about the model.

The result is that a stale catalog degrades into a smaller catalog rather than
into runtime 404s.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict

from . import config, keys


@dataclass(frozen=True)
class Model:
    id: str
    provider: str
    display: str
    tier: int
    in_price: float          # USD per million input tokens
    out_price: float         # USD per million output tokens
    context: int
    max_output: int
    vision: bool = True
    tools: bool = True
    speed: int = 60          # rough output tokens/sec, tiebreak only
    #: False when the provider REJECTS temperature/top_p for this model with a
    #: 400 rather than ignoring them — true of the Anthropic 4.7+ line. Every
    #: OpenAI-shaped client sends temperature unprompted, so forwarding it
    #: blindly would make those models permanently unroutable.
    sampling: bool = True
    notes: str = ""

    def cost(self, in_tokens: int, out_tokens: int) -> float:
        return (in_tokens * self.in_price + out_tokens * self.out_price) / 1e6

    def blended(self, out_ratio: float = 0.25) -> float:
        """A single price number for ranking, assuming output is `out_ratio` of
        total tokens. Ranking on input price alone would favour models that are
        cheap to prompt and ruinous to generate from, which is the common
        shape."""
        return self.in_price * (1 - out_ratio) + self.out_price * out_ratio

    @property
    def value(self) -> float:
        """Capability per dollar. The quantity balanced mode maximises."""
        return self.tier / max(self.blended(), 1e-6)


_lock = threading.Lock()
_cache: list[Model] | None = None
_meta: dict = {}


def _read_json(path) -> dict:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _build() -> tuple[list[Model], dict]:
    base = _read_json(config.PKG / "models.json")
    local = _read_json(config.LOCAL_MODELS)

    merged: dict[str, dict] = {}
    for row in base.get("models", []):
        if isinstance(row, dict) and row.get("id"):
            merged[row["id"]] = dict(row)
    for row in local.get("models", []):
        if isinstance(row, dict) and row.get("id"):
            merged.setdefault(row["id"], {}).update(row)

    fields = set(Model.__dataclass_fields__)
    models: list[Model] = []
    for row in merged.values():
        try:
            models.append(Model(**{k: v for k, v in row.items() if k in fields}))
        except TypeError:
            continue  # an incomplete row is skipped, not fatal

    verified = dict(base.get("pricing_verified", {}))
    verified.update(local.get("pricing_verified", {}))
    meta = {
        "pricing_verified": verified,
        "unavailable": set(_read_json(config.UNAVAILABLE).get("ids", [])),
    }
    models.sort(key=lambda m: (-m.tier, m.blended()))
    return models, meta


def _ensure():
    global _cache, _meta
    if _cache is None:
        _cache, _meta = _build()


def reload() -> None:
    global _cache, _meta
    with _lock:
        _cache, _meta = None, {}


def all_models() -> list[Model]:
    with _lock:
        _ensure()
        return list(_cache)


def by_id(model_id: str) -> Model | None:
    for m in all_models():
        if m.id == model_id:
            return m
    return None


def pricing_verified(provider: str) -> str | None:
    with _lock:
        _ensure()
        return _meta.get("pricing_verified", {}).get(provider)


def unavailable_ids() -> set:
    with _lock:
        _ensure()
        return set(_meta.get("unavailable", set()))


def usable(providers: list[str] | None = None) -> list[Model]:
    """Every model LANE is allowed to route to right now.

    A model is usable when a key exists for its provider, the user has not
    disabled it, and a sync has not marked it unreachable.
    """
    have = set(providers if providers is not None else keys.present())
    off_p = set(config.get("disabled_providers") or [])
    off_m = set(config.get("disabled_models") or [])
    gone = unavailable_ids()
    return [m for m in all_models()
            if m.provider in have
            and m.provider not in off_p
            and m.id not in off_m
            and m.id not in gone]


def mark_unavailable(ids) -> None:
    ids = sorted(set(ids))
    config.HOME.mkdir(parents=True, exist_ok=True)
    config.UNAVAILABLE.write_text(json.dumps({"ids": ids}, indent=2),
                                  encoding="utf-8")
    reload()


def add_local(model: Model) -> None:
    """Write a user-supplied model into models.local.json."""
    data = _read_json(config.LOCAL_MODELS) or {"schema": 1, "models": []}
    rows = [r for r in data.get("models", []) if r.get("id") != model.id]
    rows.append(asdict(model))
    data["models"] = rows
    config.HOME.mkdir(parents=True, exist_ok=True)
    config.LOCAL_MODELS.write_text(json.dumps(data, indent=2), encoding="utf-8")
    reload()
