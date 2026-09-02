"""
trail.py — the tamper-evident record of who did what.

Distinct from the ledger, which records money, and from the quality audit,
which records answers. This records ACTIONS: a key issued, a budget raised, a
provider key replaced, a team disabled, a request refused for want of
permission. It is the file a compliance reviewer asks for by name.

Two properties make it worth having.

IT NEVER CONTAINS PROMPTS. Only who, when, what and to what. An audit log that
accumulates the text of every question anyone asked is a data-protection
liability that grows without bound, and is the first thing a reviewer will
object to. Requests appear here as "engineering ran a reasoning request on
claude-sonnet-5 for $0.012", never as the question itself.

IT IS HASH-CHAINED. Every entry carries the hash of the one before it, so an
entry edited or removed from the middle breaks every hash after it and
`lane audit --verify` says exactly where. This is not a signature and does not
pretend to be: anyone who can write the file can also append a valid entry, and
truncating the END leaves a chain that still verifies. What it defeats is quiet
revision — someone changing a budget line after the fact, or deleting the entry
that recorded a key being issued. For the rest there is `--seal`, which prints
the current head hash to be recorded somewhere the file's owner does not
control; any later truncation past that point is then provable.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()

GENESIS = "genesis"

# Actions worth a line. Named as past-tense facts rather than intentions,
# because the log records what happened, not what was attempted.
TEAM_CREATED = "team.created"
TEAM_REMOVED = "team.removed"
TEAM_DISABLED = "team.disabled"
TEAM_ENABLED = "team.enabled"
KEY_ROTATED = "key.rotated"
BUDGET_CHANGED = "budget.changed"
ROLE_CHANGED = "role.changed"
MODELS_RESTRICTED = "models.restricted"
PROVIDER_KEY_SET = "provider_key.set"
PROVIDER_KEY_REMOVED = "provider_key.removed"
CONFIG_CHANGED = "config.changed"
REQUEST_SERVED = "request.served"
REQUEST_REFUSED = "request.refused"
AUTH_FAILED = "auth.failed"


def _file():
    return config.HOME / "trail.jsonl"


def _digest(payload: dict) -> str:
    """Hash over a canonical encoding, so key order cannot change the result."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def head() -> tuple[int, str]:
    """(sequence, hash) of the last entry, or (0, GENESIS) when empty."""
    last = None
    for entry in read():
        last = entry
    if last is None:
        return 0, GENESIS
    return int(last.get("seq", 0)), last.get("hash", GENESIS)


def record(action: str, *, actor: str = "cli", target: str = "",
           detail: dict | None = None) -> dict:
    """Append one entry. Never raises — a failure to log must not fail the
    thing being logged, or the log becomes a reason to avoid using the tool.
    """
    try:
        with _lock:
            seq, prev = head()
            body = {
                "seq": seq + 1,
                "t": round(time.time(), 3),
                "iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "actor": actor,
                "action": action,
                "target": target,
                "detail": detail or {},
                "prev": prev,
            }
            body["hash"] = _digest(body)
            config.HOME.mkdir(parents=True, exist_ok=True)
            with _file().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(body, ensure_ascii=False) + "\n")
            return body
    except Exception:
        return {}


def read(limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
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
                    rows.append(json.loads(line))
                except Exception:
                    # A line that will not parse is itself a finding, not
                    # something to skip silently.
                    rows.append({"_corrupt": line[:200]})
    except Exception:
        return rows
    return rows[-limit:] if limit else rows


def verify() -> dict:
    """Walk the chain. Returns where it first breaks, and why.

    Four distinct failures, because "the log is invalid" is not actionable and
    each of these points at a different thing having happened:

      corrupt   a line that is not JSON at all
      hash      an entry whose contents no longer match its own hash — it was
                edited in place
      link      an entry whose prev does not match the previous entry's hash —
                something was removed or inserted before it
      sequence  a gap in the numbering — entries were deleted
    """
    rows = read()
    prev_hash = GENESIS
    expect_seq = 1
    for i, entry in enumerate(rows):
        if "_corrupt" in entry:
            return {"ok": False, "at": i, "reason": "corrupt",
                    "entries": len(rows),
                    "message": f"line {i + 1} is not valid JSON"}

        stored = entry.get("hash")
        body = {k: entry.get(k) for k in
                ("seq", "t", "iso", "actor", "action", "target", "detail",
                 "prev")}
        if _digest(body) != stored:
            return {"ok": False, "at": i, "reason": "hash",
                    "entries": len(rows), "seq": entry.get("seq"),
                    "message": f"entry {entry.get('seq')} was edited after it "
                               f"was written"}
        if entry.get("prev") != prev_hash:
            return {"ok": False, "at": i, "reason": "link",
                    "entries": len(rows), "seq": entry.get("seq"),
                    "message": f"entries were removed or inserted before "
                               f"entry {entry.get('seq')}"}
        if entry.get("seq") != expect_seq:
            return {"ok": False, "at": i, "reason": "sequence",
                    "entries": len(rows), "seq": entry.get("seq"),
                    "message": f"expected entry {expect_seq}, found "
                               f"{entry.get('seq')} — entries were deleted"}
        prev_hash = stored
        expect_seq += 1

    return {"ok": True, "entries": len(rows), "head": prev_hash,
            "message": f"{len(rows)} entries, chain intact"}


def describe(entry: dict) -> str:
    """One human sentence per entry, for the terminal."""
    action = entry.get("action", "?")
    target = entry.get("target", "")
    d = entry.get("detail") or {}

    if action == TEAM_CREATED:
        budget = d.get("budget")
        extra = f", ${budget:,.2f} {d.get('period', '')}" if budget else ""
        return f"created team {target} as {d.get('role', 'member')}{extra}"
    if action == TEAM_REMOVED:
        return f"removed team {target}"
    if action in (TEAM_DISABLED, TEAM_ENABLED):
        return f"{'disabled' if action == TEAM_DISABLED else 'enabled'} {target}"
    if action == KEY_ROTATED:
        return f"rotated the key for {target} — the previous one stopped working"
    if action == BUDGET_CHANGED:
        return (f"set {target} budget to ${d.get('budget', 0):,.2f} "
                f"{d.get('period', '')} ({'hard' if d.get('hard') else 'soft'})")
    if action == ROLE_CHANGED:
        return f"changed {target} role to {d.get('role')}"
    if action == MODELS_RESTRICTED:
        allowed = d.get("allowed") or []
        return (f"restricted {target} to {len(allowed)} model(s)" if allowed
                else f"removed the model restriction on {target}")
    if action == PROVIDER_KEY_SET:
        return f"stored a {target} API key"
    if action == PROVIDER_KEY_REMOVED:
        return f"removed the {target} API key"
    if action == CONFIG_CHANGED:
        return f"set {target} = {d.get('value')!r}"
    if action == REQUEST_SERVED:
        cost = d.get("cost", 0)
        return (f"{d.get('lane', '?')} request served by "
                f"{d.get('model', '?')} (${cost:.5f})")
    if action == REQUEST_REFUSED:
        return f"request refused: {d.get('why', 'no reason recorded')}"
    if action == AUTH_FAILED:
        return f"rejected a request with an invalid or missing key"
    return f"{action} {target}".strip()
