"""
ledger.py — what every request cost, and what it would have cost otherwise.

The second half of that sentence is the whole product. "You spent $4.10 this
week" is an accounting fact and tells nobody anything. "You spent $4.10 where
Opus 5 for everything would have cost $31.80" is the reason to keep LANE
installed, and it is only computable because the router knows, for every single
request, both what it chose and what the user would otherwise have used.

Two things are done carefully here, because a savings number is exactly the
kind of number a tool is tempted to flatter itself with:

  * The baseline is a SETTING, not a constant. It defaults to the configured
    baseline_model and means "what I would have used for everything". A user
    who would really have used a cheap model for everything can say so and
    watch the savings shrink to nothing. A number you can argue with is worth
    more than one you cannot.

  * A request whose model has unverified pricing is counted, but flagged. The
    totals carry `estimated: true` so no report can quietly present a guessed
    price as a measured one.

Storage is append-only JSONL. It survives a crash mid-write losing at most the
final line, needs no schema migration when a field is added, and can be read by
anything.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from . import catalog, config

_lock = threading.Lock()


def record(*, lane: str, mode: str, model: str, provider: str,
           in_tokens: int, out_tokens: int, latency_ms: int = 0,
           tier: str = "", margin: float = 0.0, ok: bool = True,
           error: str = "", baseline: str | None = None,
           streamed: bool = False, source: str = "proxy",
           team: str | None = None) -> dict:
    """Append one request to the ledger. Never raises — a failure to write
    accounting must not fail a request the user already paid for."""
    m = catalog.by_id(model)
    cost = m.cost(in_tokens, out_tokens) if m else 0.0

    base_id = baseline or config.get("baseline_model")
    bm = catalog.by_id(base_id)
    base_cost = bm.cost(in_tokens, out_tokens) if bm else 0.0

    estimated = bool(
        (m and not catalog.pricing_verified(m.provider))
        or (bm and not catalog.pricing_verified(bm.provider)))

    row = {
        "t": time.time(),
        "iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lane": lane, "mode": mode,
        "model": model, "provider": provider,
        "in": int(in_tokens), "out": int(out_tokens),
        "cost": round(cost, 8),
        "baseline": base_id, "baseline_cost": round(base_cost, 8),
        "saved": round(base_cost - cost, 8),
        "estimated": estimated,
        "tier": tier, "margin": margin,
        "ms": int(latency_ms), "ok": bool(ok), "streamed": bool(streamed),
        #: "proxy" — LANE made this call and this money was really spent.
        #: "advisor" — LANE only gave advice; the numbers are what following
        #: it WOULD have saved. The two must never be added together, and the
        #: field exists so that they cannot be by accident.
        "source": source,
        #: Which team's budget this came out of. None on a single-user
        #: install, where the question does not arise.
        "team": team,
    }
    if error:
        row["error"] = error[:400]

    try:
        with _lock:
            config.HOME.mkdir(parents=True, exist_ok=True)
            with config.LEDGER_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return row


def read(days: float | None = None, limit: int | None = None) -> list[dict]:
    """Rows, oldest first. `days` filters by age; `limit` keeps the newest."""
    rows: list[dict] = []
    try:
        if not config.LEDGER_FILE.is_file():
            return []
        cutoff = time.time() - days * 86400 if days else 0
        with config.LEDGER_FILE.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue  # a torn final line is expected, not an error
                if row.get("t", 0) >= cutoff:
                    rows.append(row)
    except Exception:
        return rows
    return rows[-limit:] if limit else rows


def stats(days: float | None = None, source: str = "proxy",
          team: str | None = None) -> dict:
    """Aggregate the ledger into something worth printing.

    `source` matters more than it looks. Proxy rows are money that left the
    account; advisor rows are money that would have been saved had the advice
    been taken, which nobody can verify. Summing them would produce a single
    impressive number that means nothing, so the split is enforced here rather
    than left to the caller to remember.
    """
    rows = [r for r in read(days)
            if r.get("ok", True)
            and r.get("source", "proxy") == source
            and (team is None or r.get("team") == team)]
    total = {
        "requests": len(rows),
        "in_tokens": sum(r.get("in", 0) for r in rows),
        "out_tokens": sum(r.get("out", 0) for r in rows),
        "cost": sum(r.get("cost", 0.0) for r in rows),
        "baseline_cost": sum(r.get("baseline_cost", 0.0) for r in rows),
        "estimated": any(r.get("estimated") for r in rows),
        "days": days,
    }
    total["saved"] = total["baseline_cost"] - total["cost"]
    total["saved_pct"] = (
        total["saved"] / total["baseline_cost"] * 100
        if total["baseline_cost"] else 0.0)

    def group(key: str) -> dict:
        out: dict[str, dict] = defaultdict(
            lambda: {"requests": 0, "cost": 0.0, "saved": 0.0,
                     "in": 0, "out": 0})
        for r in rows:
            b = out[r.get(key) or "?"]
            b["requests"] += 1
            b["cost"] += r.get("cost", 0.0)
            b["saved"] += r.get("saved", 0.0)
            b["in"] += r.get("in", 0)
            b["out"] += r.get("out", 0)
        return dict(out)

    errors = [r for r in read(days) if not r.get("ok", True)]
    return {
        "total": total,
        "by_lane": group("lane"),
        "by_model": group("model"),
        "by_provider": group("provider"),
        "by_team": group("team"),
        "errors": len(errors),
    }


def advice(*, lane: str, site: str, recommended: str, top: str,
           rec_cost: float, top_cost: float, in_tokens: int,
           out_tokens: int) -> dict:
    """Record one recommendation the advisor made.

    This is the product's own scoreboard: over a week it answers "what is this
    thing doing for me" with a number instead of a feeling. It is deliberately
    filed as POTENTIAL saving — LANE cannot see which model you actually
    picked, and a tool that quietly counts advice as if it were always taken is
    lying to the person paying for it.
    """
    row = {
        "t": time.time(),
        "iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lane": lane, "mode": "advice", "site": site,
        "model": recommended, "provider": site,
        "in": int(in_tokens), "out": int(out_tokens),
        "cost": round(rec_cost, 8),
        "baseline": top, "baseline_cost": round(top_cost, 8),
        "saved": round(top_cost - rec_cost, 8),
        "estimated": True, "ok": True, "source": "advisor",
    }
    try:
        with _lock:
            config.HOME.mkdir(parents=True, exist_ok=True)
            with config.LEDGER_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return row


def clear() -> None:
    with _lock:
        if config.LEDGER_FILE.is_file():
            config.LEDGER_FILE.unlink()


def money(x: float) -> str:
    """Format a dollar amount without pretending to precision it lacks, and
    without collapsing a real-but-small amount to $0.00."""
    if x == 0:
        return "$0"
    if abs(x) < 0.01:
        return f"${x:.4f}"
    if abs(x) < 1:
        return f"${x:.3f}"
    return f"${x:,.2f}"
