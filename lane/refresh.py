"""
refresh.py — let the catalog learn the facts instead of being told them.

Most of what LANE knows about a model is a fact somebody publishes: what it
costs, how big its window is, whether it reads images, whether it makes them,
whether it takes tools. Those were hand-typed into models.json, which means
they were stale the day after and wrong wherever I guessed. Every savings
figure in this product rests on them.

OpenRouter publishes all of it for several hundred models, free and without a
key, and the shape maps almost one-to-one onto the catalog:

    pricing.prompt / .completion        in_price / out_price
    context_length                      context
    top_provider.max_completion_tokens  max_output
    architecture.input_modalities       vision   (can it READ an image)
    architecture.output_modalities      image_out (can it MAKE one)
    supported_parameters                tools, and whether it reasons
    pricing.web_search                  web

WHAT THIS DOES NOT FETCH IS `tier`.

Nobody publishes a machine-readable quality ranking that is free to consume.
LMArena and Artificial Analysis both have the numbers and neither offers an
API; scraping a leaderboard to decide which model a user should pay for is a
dependency on somebody else's HTML, and a quiet one — the day it breaks, the
routing quietly gets worse rather than loudly failing. So tier stays a
judgement, written down in one place, arguable, and unchanged by this.

That split is worth being clear about, because it is the difference between the
two halves of the product. Which model is CHEAPEST is a fact, and facts should
be fetched. Which model is BEST is an opinion, and an opinion should be
somebody's, in writing, where it can be disagreed with.
"""

from __future__ import annotations

import json

import httpx

from . import catalog, config

ENDPOINT = "https://openrouter.ai/api/v1/models"

#: Fields refresh is allowed to touch. Anything not listed here — tier,
#: strengths, display, notes — is a judgement and survives a refresh untouched.
FACTS = ("in_price", "out_price", "context", "max_output", "vision", "tools",
         "image_out", "kind", "web", "per_image")


async def fetch(timeout: float = 30.0) -> list[dict]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(ENDPOINT)
        r.raise_for_status()
        return r.json().get("data") or []


def _tail(model_id: str) -> str:
    return model_id.rsplit("/", 1)[-1]


def match(model_id: str, live: list[dict]) -> dict | None:
    """Find the OpenRouter record for one of our ids.

    Matching is on the tail because the two namespaces disagree about
    prefixes: LANE calls it `claude-sonnet-5` and OpenRouter calls it
    `anthropic/claude-sonnet-5`, while Groq's `openai/gpt-oss-120b` carries a
    prefix that is part of the name rather than the vendor. Comparing tails
    handles both without a table of special cases to maintain.
    """
    want = _tail(model_id).lower()
    exact = [m for m in live if m.get("id", "").lower() == model_id.lower()]
    if exact:
        return exact[0]
    tails = [m for m in live if _tail(m.get("id", "")).lower() == want]
    if len(tails) == 1:
        return tails[0]
    # More than one vendor serving the same name is ambiguous, and guessing
    # would silently price a model from the wrong one.
    return None


def facts_from(record: dict) -> dict:
    """Read the catalog fields out of an OpenRouter record."""
    pricing = record.get("pricing") or {}
    arch = record.get("architecture") or {}
    top = record.get("top_provider") or {}
    params = set(record.get("supported_parameters") or [])

    def price(key: str) -> float | None:
        try:
            # OpenRouter quotes per token; the catalog is per million.
            return round(float(pricing[key]) * 1_000_000, 6)
        except (KeyError, TypeError, ValueError):
            return None

    out: dict = {}
    for field, key in (("in_price", "prompt"), ("out_price", "completion")):
        value = price(key)
        if value is not None:
            out[field] = value

    if record.get("context_length"):
        out["context"] = int(record["context_length"])
    if top.get("max_completion_tokens"):
        out["max_output"] = int(top["max_completion_tokens"])

    inputs = set(arch.get("input_modalities") or [])
    outputs = set(arch.get("output_modalities") or [])
    if inputs:
        out["vision"] = "image" in inputs
    if outputs:
        makes_images = "image" in outputs
        out["image_out"] = makes_images
        out["kind"] = "image" if makes_images and "text" not in outputs \
            else "chat"

    if params:
        out["tools"] = "tools" in params
    # A model billed for web search is a model that can do web search.
    out["web"] = "web_search" in pricing
    return out


def diff(model, record: dict) -> dict:
    """What would change, and from what. Only genuine differences."""
    changes = {}
    for field, new in facts_from(record).items():
        old = getattr(model, field, None)
        if isinstance(new, float) and isinstance(old, (int, float)):
            if abs(float(old) - new) < 1e-9:
                continue
        elif old == new:
            continue
        changes[field] = (old, new)
    return changes


def plan(live: list[dict]) -> tuple[list, list, list]:
    """(updates, unmatched, extra_count) without writing anything.

    Separated from applying it because a refresh that silently rewrites the
    prices the savings figures are built on is a refresh nobody will run
    twice.
    """
    updates, unmatched = [], []
    known_tails = {_tail(m.id).lower() for m in catalog.all_models()}
    for model in catalog.all_models():
        record = match(model.id, live)
        if record is None:
            unmatched.append(model)
            continue
        changes = diff(model, record)
        if changes:
            updates.append((model, record, changes))
    extra = [m for m in live
             if _tail(m.get("id", "")).lower() not in known_tails]
    return updates, unmatched, extra


def apply(updates: list) -> int:
    """Write the facts into the USER's overrides file, never the shipped one.

    models.local.json is theirs and survives an upgrade; models.json ships with
    the package and gets replaced by one. Writing refreshed prices into the
    package file would mean losing them on the next `pip install -U`, which is
    exactly when somebody would stop trusting the numbers.
    """
    path = config.LOCAL_MODELS
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() \
            else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    rows = {r.get("id"): dict(r) for r in data.get("models", [])
            if isinstance(r, dict) and r.get("id")}

    for model, _record, changes in updates:
        row = rows.setdefault(model.id, {"id": model.id})
        for field, (_old, new) in changes.items():
            row[field] = new

    data["schema"] = data.get("schema", 1)
    data["models"] = list(rows.values())
    verified = dict(data.get("pricing_verified") or {})
    for model, _r, _c in updates:
        # Prices that came from a published source are no longer guesses, and
        # the rest of the product stops calling them estimates.
        verified[model.provider] = "openrouter"
    data["pricing_verified"] = verified

    config.HOME.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    catalog.reload()
    return len(updates)
