"""
audit.py — proving the cheap route was good enough, on your own traffic.

Every cost router makes the same claim and none of them proves it: that the
smaller model it picked answered as well as the expensive one would have. The
claim is unfalsifiable in normal use, because the expensive answer never
existed. So the objection that kills the sale — "will quality drop?" — can only
be met with assurances, and assurances are worth nothing to somebody signing
off a budget.

This measures it instead. On a small, configurable fraction of requests LANE
answers TWICE: once with the model it routed to, once with the baseline it is
being compared against. Both answers are kept, and a judge is asked a narrow
question about the pair. The output is a number about YOUR traffic:

    over 412 sampled requests, the routed model was as good or better
    on 94% of them, and cost 8.1x less

Three things are deliberate.

SAMPLED, not universal. Auditing every request would double the bill to prove
the bill is too high, which is self-defeating. At 2% the audit costs about 2%
extra and the estimate is already tight enough to argue with.

THE USER'S ANSWER IS NEVER THE EXPERIMENT. The routed answer is what gets
returned, always, exactly as it would have been. The baseline call happens
afterwards and only for the record — nobody is served a worse answer, or a
slower one, because an audit was running.

THE JUDGE IS THE STRONG MODEL. Asking a cheap model whether a cheap model did
well is not evidence. The judge defaults to the baseline, so the expensive
model is grading its own replacement — which biases AGAINST the result being
sold, and that is the right direction for a number meant to survive scrutiny.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import datetime, timezone

from . import catalog, config

_lock = threading.Lock()

#: The verdicts a judge may return. Deliberately three, not a score out of ten:
#: a number invites averaging noise into a headline, while these collapse to
#: the only question a buyer actually asks — was the cheaper answer good
#: enough?
BETTER = "better"
SAME = "same"
WORSE = "worse"
VERDICTS = (BETTER, SAME, WORSE)

_JUDGE_PROMPT = """\
Two assistants answered the same request. Say which answer serves the person \
who asked it better.

Judge only on whether the answer does the job: correct, complete, and \
responsive to what was asked. Ignore length, tone, formatting and which \
assistant sounds more confident. A shorter answer that fully answers is not \
worse. If they are equally useful, say SAME — that is the expected outcome and \
not a cop-out.

REQUEST:
{request}

ANSWER A:
{a}

ANSWER B:
{b}

Reply with exactly one word: A, B, or SAME."""


def rate() -> float:
    """Fraction of proxy requests to audit. 0 disables it entirely."""
    try:
        return max(0.0, min(1.0, float(config.get("audit_sample_rate") or 0)))
    except (TypeError, ValueError):
        return 0.0


def should_sample(key: str) -> bool:
    """Deterministic sampling, from a hash of the request rather than a random
    draw.

    Two reasons. The same request audited twice would be counted twice and
    inflate the sample. And a reproducible decision means a disputed report can
    be re-derived later — "why was this one audited" has an answer.
    """
    r = rate()
    if r <= 0:
        return False
    if r >= 1:
        return True
    digest = hashlib.sha256(key.encode("utf-8", "replace")).digest()
    bucket = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return bucket < r


def record(*, request: str, lane: str, routed_model: str, routed_text: str,
           routed_cost: float, base_model: str, base_text: str,
           base_cost: float, routed_tokens: tuple = (0, 0),
           base_tokens: tuple = (0, 0)) -> dict:
    """Store one audited pair, unjudged. Never raises."""
    row = {
        "t": time.time(),
        "iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lane": lane,
        "request": (request or "")[:4000],
        "routed": {"model": routed_model, "text": (routed_text or "")[:8000],
                   "cost": round(routed_cost, 8),
                   "in": routed_tokens[0], "out": routed_tokens[1]},
        "base": {"model": base_model, "text": (base_text or "")[:8000],
                 "cost": round(base_cost, 8),
                 "in": base_tokens[0], "out": base_tokens[1]},
        "verdict": None,
        "judge": None,
    }
    _append(row)
    return row


def _append(row: dict) -> None:
    try:
        with _lock:
            config.HOME.mkdir(parents=True, exist_ok=True)
            with _file().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _file():
    return config.HOME / "audit.jsonl"


def read(limit: int | None = None, unjudged_only: bool = False) -> list[dict]:
    rows = []
    try:
        path = _file()
        if not path.is_file():
            return []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue          # a torn final line is expected
                if unjudged_only and row.get("verdict"):
                    continue
                rows.append(row)
    except Exception:
        return rows
    return rows[-limit:] if limit else rows


def rewrite(rows: list[dict]) -> None:
    """Replace the log wholesale — used after judging fills verdicts in."""
    try:
        with _lock:
            config.HOME.mkdir(parents=True, exist_ok=True)
            tmp = _file().with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            tmp.replace(_file())
    except Exception:
        pass


def judge_prompt(row: dict, swapped: bool) -> str:
    """Build the comparison. `swapped` puts the routed answer second.

    Position matters: judges favour whichever answer they read first, by a
    wide enough margin to manufacture the result being sold here. Which side
    the routed answer sits on is decided per row and recorded, so the bias
    cancels across the sample instead of accumulating into the headline.
    """
    a, b = row["base"]["text"], row["routed"]["text"]
    if swapped:
        a, b = b, a
    return _JUDGE_PROMPT.format(request=row.get("request", ""), a=a, b=b)


#: A standalone verdict token. Anchored on word boundaries because "A" and "B"
#: occur constantly inside ordinary prose, and a substring match would read a
#: verdict out of "Answer A said..." while the model was still explaining
#: itself.
_VERDICT_TOKEN = re.compile(r"\b(SAME|A|B)\b")


def read_verdict(reply: str, swapped: bool) -> str | None:
    """Turn the judge's word back into a verdict about the ROUTED answer.

    The reply is scanned rather than merely prefix-matched, and the LAST token
    wins. Reasoning models narrate before they conclude — "A is more complete,
    but B answers the question, so B" — and taking the first token would score
    the opposite of what was decided. The last standalone token is the verdict
    in every shape observed.
    """
    if not reply:
        return None
    found = _VERDICT_TOKEN.findall(reply.strip().upper())
    if not found:
        return None
    word = found[-1]
    if word == "SAME":
        return SAME
    routed_letter = "A" if swapped else "B"
    return BETTER if word == routed_letter else WORSE


def summary(rows: list[dict] | None = None) -> dict:
    """The number a buyer asks for, and the ones that qualify it."""
    rows = read() if rows is None else rows
    judged = [r for r in rows if r.get("verdict") in VERDICTS]
    counts = {v: sum(1 for r in judged if r["verdict"] == v) for v in VERDICTS}
    n = len(judged)

    routed_cost = sum(r["routed"]["cost"] for r in rows)
    base_cost = sum(r["base"]["cost"] for r in rows)

    by_lane: dict[str, dict] = {}
    for r in judged:
        b = by_lane.setdefault(r.get("lane", "?"),
                               {"n": 0, BETTER: 0, SAME: 0, WORSE: 0})
        b["n"] += 1
        b[r["verdict"]] += 1

    return {
        "sampled": len(rows),
        "judged": n,
        "counts": counts,
        # "Good enough" is better-or-same. A router does not need to WIN; it
        # needs to not lose, at a fraction of the price.
        "acceptable": (counts[BETTER] + counts[SAME]) / n if n else 0.0,
        "worse_rate": counts[WORSE] / n if n else 0.0,
        "routed_cost": routed_cost,
        "base_cost": base_cost,
        "factor": (base_cost / routed_cost) if routed_cost else 0.0,
        "by_lane": by_lane,
        "rate": rate(),
    }


def headline(s: dict | None = None) -> str:
    """One sentence, with every qualifier a sceptic would demand."""
    s = summary() if s is None else s
    if not s["judged"]:
        return ("nothing judged yet — run `lane audit --judge` once some "
                "sampled requests have accumulated")
    base = catalog.by_id(s.get("base_model") or "") if s.get("base_model") else None
    return (f"over {s['judged']} judged requests, the routed model was as good "
            f"or better {s['acceptable']:.0%} of the time"
            + (f" and cost {s['factor']:.1f}x less" if s["factor"] > 1 else "")
            + (f" (sampled at {s['rate']:.0%})" if s["rate"] else ""))
