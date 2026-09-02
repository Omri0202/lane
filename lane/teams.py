"""
teams.py — who spent it, and the point at which they stop.

The single change that turns a personal tool into something a company can sign
for. Three things happen here, and the third is the one procurement actually
asks about.

ATTRIBUTION. Every request arrives with a LANE-issued key rather than a
provider key, so every dollar has a team's name on it. "We spent $47k on
models last month" is a fact nobody can act on; "support spent $900 of it and
engineering spent $31k, 78% of that on reasoning" is a conversation.

ENFORCEMENT. A budget that only warns is a report. A hard budget refuses the
request before the money is spent, and says who to talk to. Companies do not
buy dashboards that watch overspending happen.

KEY ISOLATION. This is the part security teams care about and the reason the
other two are possible. The provider keys live in one place — the machine
running LANE, in its OS credential store. Developers never hold one. What they
hold is a LANE key that is scoped to their team, revocable in one command
without rotating anything upstream, and useless to anyone outside the network
LANE is on. Today a leaked provider key means an emergency rotation and every
team's integration breaking at once.

Keys are stored as SHA-256 digests, never in the clear. A stolen teams.json is
a list of team names and budgets, not a set of working credentials, and LANE
itself cannot show you a key after the moment it was created.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()

#: Recognisable in a log or a leaked config, so a key that ends up somewhere it
#: should not be can be identified as LANE's and revoked, rather than mistaken
#: for a provider key and left alone.
PREFIX = "lane-sk-"

#: Budget windows. "total" is a lifetime cap, useful for a trial or a
#: contractor engagement with a fixed ceiling.
MONTHLY, DAILY, TOTAL = "monthly", "daily", "total"
PERIODS = (MONTHLY, DAILY, TOTAL)

#: Three roles, because three is what the question actually has.
#:
#:   member  may send requests. The default, and what almost every key is.
#:   viewer  may read spend and reports and may NOT send requests. For a
#:           finance owner or a manager who needs the numbers without being
#:           able to run up the bill they are reviewing.
#:   admin   may do both, and may manage teams over HTTP.
#:
#: Resisting a longer list is deliberate. Every extra role is a decision
#: somebody has to make at provisioning time, and a role nobody can explain in
#: one sentence gets assigned by guesswork.
MEMBER, VIEWER, ADMIN = "member", "viewer", "admin"
ROLES = (MEMBER, VIEWER, ADMIN)

#: What each role is allowed to do. Checked by name so a new capability is one
#: entry here rather than a condition scattered across the server.
_CAN = {
    MEMBER: {"infer"},
    VIEWER: {"read"},
    ADMIN: {"infer", "read", "manage"},
}


def can(team: dict | None, capability: str) -> bool:
    if not team or team.get("disabled"):
        return False
    return capability in _CAN.get(team.get("role", MEMBER), set())


def _file():
    return config.HOME / "teams.json"


def _load() -> dict:
    try:
        if _file().is_file():
            data = json.loads(_file().read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("teams"), list):
                return data
    except Exception:
        pass
    return {"teams": []}


def _save(data: dict) -> None:
    config.HOME.mkdir(parents=True, exist_ok=True)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_file())


def _hash(key: str) -> str:
    return hashlib.sha256((key or "").strip().encode("utf-8")).hexdigest()


def all_teams() -> list[dict]:
    return _load()["teams"]


def get(team_id: str) -> dict | None:
    return next((t for t in all_teams() if t["id"] == team_id), None)


def enabled() -> bool:
    """Whether LANE is in multi-team mode at all.

    Creating the first team is what switches authentication on. Before that
    LANE is a personal tool on a laptop and demanding a key would be friction
    for nobody's benefit; after it, an unauthenticated request must be refused,
    or every budget in the system can be sidestepped by omitting a header.
    """
    return bool(all_teams())


def slug(name: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in (name or "").lower())
    return "-".join(p for p in out.split("-") if p)[:40] or "team"


def create(name: str, *, budget: float = 0.0, period: str = MONTHLY,
           hard: bool = True, role: str = MEMBER,
           allowed_models: list | None = None) -> tuple[dict, str]:
    """Make a team and mint its key. The key is returned ONCE and never stored.

    Returns (team, key). If the caller loses the key the only route back is
    rotation — which is the property that makes the stored file safe to back
    up, and the reason this returns a tuple instead of just the team.
    """
    data = _load()
    team_id = slug(name)
    if any(t["id"] == team_id for t in data["teams"]):
        raise ValueError(f"a team called {team_id!r} already exists")
    if period not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}")
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")

    key = PREFIX + secrets.token_urlsafe(32)
    team = {
        "id": team_id,
        "name": name,
        "key_hash": _hash(key),
        "budget": float(budget or 0.0),
        "period": period,
        #: hard budgets refuse; soft budgets mark the response and let it
        #: through. Both are useful — a team that must never be interrupted
        #: still benefits from someone being told it went over.
        "hard": bool(hard),
        "role": role,
        #: Models this team may use. Empty means "whatever LANE can route to",
        #: which is the right default — a restriction nobody asked for is a
        #: support ticket waiting to happen. Set it when a team genuinely must
        #: not reach the frontier models.
        "allowed_models": list(allowed_models or []),
        "disabled": False,
        "created": time.time(),
        "created_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    data["teams"].append(team)
    _save(data)
    return team, key


def rotate(team_id: str) -> str:
    """Issue a new key and invalidate the old one immediately.

    No grace period on purpose. Rotation happens because a key leaked, and a
    window in which the leaked key still works is the window the leak is used
    in.
    """
    with _lock:
        data = _load()
        team = next((t for t in data["teams"] if t["id"] == team_id), None)
        if team is None:
            raise KeyError(team_id)
        key = PREFIX + secrets.token_urlsafe(32)
        team["key_hash"] = _hash(key)
        team["rotated"] = time.time()
        _save(data)
        return key


def set_budget(team_id: str, *, budget: float | None = None,
               period: str | None = None, hard: bool | None = None) -> dict:
    with _lock:
        data = _load()
        team = next((t for t in data["teams"] if t["id"] == team_id), None)
        if team is None:
            raise KeyError(team_id)
        if budget is not None:
            team["budget"] = max(0.0, float(budget))
        if period is not None:
            if period not in PERIODS:
                raise ValueError(f"period must be one of {', '.join(PERIODS)}")
            team["period"] = period
        if hard is not None:
            team["hard"] = bool(hard)
        _save(data)
        return dict(team)


def set_role(team_id: str, role: str) -> dict:
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    with _lock:
        data = _load()
        team = next((t for t in data["teams"] if t["id"] == team_id), None)
        if team is None:
            raise KeyError(team_id)
        team["role"] = role
        _save(data)
        return dict(team)


def set_allowed_models(team_id: str, models: list) -> dict:
    with _lock:
        data = _load()
        team = next((t for t in data["teams"] if t["id"] == team_id), None)
        if team is None:
            raise KeyError(team_id)
        team["allowed_models"] = list(models or [])
        _save(data)
        return dict(team)


def permitted(team: dict | None, models: list) -> list:
    """Filter a candidate pool down to what this team may use.

    Applied BEFORE the router chooses, not after, so a restricted team gets
    the best model it is allowed rather than a refusal for the one it is not.
    A policy that produces errors instead of alternatives gets switched off.
    """
    if not team:
        return models
    allowed = set(team.get("allowed_models") or [])
    if not allowed:
        return models
    return [m for m in models if m.id in allowed]


def set_disabled(team_id: str, off: bool) -> dict:
    with _lock:
        data = _load()
        team = next((t for t in data["teams"] if t["id"] == team_id), None)
        if team is None:
            raise KeyError(team_id)
        team["disabled"] = bool(off)
        _save(data)
        return dict(team)


def remove(team_id: str) -> bool:
    with _lock:
        data = _load()
        before = len(data["teams"])
        data["teams"] = [t for t in data["teams"] if t["id"] != team_id]
        if len(data["teams"]) == before:
            return False
        _save(data)
        return True


def authenticate(presented: str | None) -> dict | None:
    """Resolve a bearer token to a team, or None.

    Compared with hmac.compare_digest over the digests. The keys here are 256
    bits of entropy and a timing attack on them is not a realistic threat, but
    a constant-time compare costs nothing and removes the need for anyone
    reviewing this to think about it.
    """
    if not presented:
        return None
    token = presented.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token.startswith(PREFIX):
        return None
    digest = _hash(token)
    for team in all_teams():
        if hmac.compare_digest(team.get("key_hash", ""), digest):
            return None if team.get("disabled") else team
    return None


def period_start(period: str, now: float | None = None) -> float:
    now = time.time() if now is None else now
    if period == TOTAL:
        return 0.0
    dt = datetime.fromtimestamp(now, tz=timezone.utc)
    if period == DAILY:
        dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        dt = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return dt.timestamp()


def spent(team_id: str, period: str | None = None) -> float:
    """Real money this team has spent in the current window.

    Counts proxy traffic AND audit shadow calls, because both are billed to
    the same account. Advisor rows are excluded: those are potential savings
    on advice nobody can prove was taken, and letting a hypothetical number
    consume a real budget would be indefensible.
    """
    from . import ledger
    team = get(team_id)
    period = period or (team or {}).get("period", MONTHLY)
    since = period_start(period)
    total = 0.0
    for row in ledger.read():
        if row.get("team") != team_id:
            continue
        if row.get("source", "proxy") not in ("proxy", "audit"):
            continue
        if row.get("t", 0) < since:
            continue
        total += row.get("cost", 0.0)
    return total


def status(team_id: str) -> dict:
    team = get(team_id)
    if team is None:
        return {}
    used = spent(team_id)
    budget = float(team.get("budget") or 0.0)
    return {
        "id": team_id, "name": team.get("name", team_id),
        "budget": budget, "period": team.get("period", MONTHLY),
        "hard": bool(team.get("hard", True)),
        "role": team.get("role", MEMBER),
        "allowed_models": list(team.get("allowed_models") or []),
        "disabled": bool(team.get("disabled")),
        "spent": used,
        "remaining": max(0.0, budget - used) if budget else None,
        "fraction": (used / budget) if budget else 0.0,
        "over": bool(budget and used >= budget),
    }


def check(team: dict, estimated_cost: float = 0.0) -> tuple[bool, str]:
    """May this request proceed? Returns (allowed, message).

    The estimate is added before the comparison so a team cannot step over its
    ceiling with one very large request — the budget is a ceiling, not a line
    it is allowed to cross once per period.
    """
    if team.get("disabled"):
        return False, f"the {team.get('name', team['id'])} key has been disabled"

    budget = float(team.get("budget") or 0.0)
    if budget <= 0:
        return True, ""

    used = spent(team["id"])
    if used + max(0.0, estimated_cost) < budget:
        return True, ""

    window = {MONTHLY: "this month", DAILY: "today",
              TOTAL: "in total"}.get(team.get("period", MONTHLY), "this period")
    # Formatted with the ledger's own helper rather than :,.2f. A budget of a
    # fraction of a cent rendered as "used $0.00 of its $0.00 budget", which
    # reads as a bug rather than a limit — and is exactly the message somebody
    # sees the first time they try a small test budget.
    from .ledger import money
    detail = (f"{team.get('name', team['id'])} has used "
              f"{money(used)} of its {money(budget)} budget {window}")
    if team.get("hard"):
        return False, (f"{detail}. Raise it with "
                       f"`lane team budget {team['id']} <amount>` or wait for "
                       f"the window to reset.")
    return True, detail + " (soft limit — allowed, but over)"
