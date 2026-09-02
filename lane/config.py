"""
config.py — where LANE keeps its state, and the handful of settings it has.

Everything lives under ~/.lane so that an uninstall is one directory delete and
so that nothing LANE writes ever lands inside a user's project tree. The
package directory itself is treated as read-only: models.json ships with the
package, models.local.json is the user's, and the two are merged at load.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

PKG = Path(__file__).parent
HOME = Path(os.environ.get("LANE_HOME") or (Path.home() / ".lane"))

CONFIG_FILE = HOME / "config.json"
LEDGER_FILE = HOME / "ledger.jsonl"
LOCAL_MODELS = HOME / "models.local.json"
UNAVAILABLE = HOME / "unavailable.json"

#: The three routing modes. `mode` picks how a lane is turned into a model.
MODE_SAVE = "save"
MODE_BALANCED = "balanced"
MODE_PERFORMANCE = "performance"
MODES = (MODE_SAVE, MODE_BALANCED, MODE_PERFORMANCE)

DEFAULTS = {
    #: Which mode a bare `model: "auto"` request uses.
    "mode": MODE_BALANCED,
    "host": "127.0.0.1",
    "port": 8080,
    #: Model the ledger compares against when computing what routing saved.
    #: This is what the user would plausibly have used for everything if LANE
    #: did not exist — it is the honest denominator for a savings claim, and it
    #: is a setting rather than a constant because that assumption is personal.
    "baseline_model": "claude-opus-5",
    #: Announce the routing decision as a header on every response.
    "report_headers": True,
    #: Never route to these providers even if a key is present.
    "disabled_providers": [],
    #: Never route to these model ids.
    "disabled_models": [],
    #: The models this person can actually reach — the ones in their plan's
    #: dropdown, or the ones their key is entitled to. Empty means "assume the
    #: whole catalog", which is the only sensible default before anyone has
    #: said otherwise.
    #:
    #: This is the difference between advice and trivia. Telling somebody on a
    #: plan without Opus to use Opus is not a recommendation, it is a chore
    #: with an extra step.
    "enabled_models": [],
    #: Refuse to serve a request whose estimated cost exceeds this, in USD.
    #: 0 disables the guard.
    "max_cost_per_request": 0.0,
    #: Fraction of proxy requests to answer TWICE — once routed, once on the
    #: baseline — so the two can be compared. 0 is off. 0.02 costs about 2%
    #: extra and buys a defensible answer to "will quality drop?", which is
    #: the question that decides whether anyone adopts cost routing.
    "audit_sample_rate": 0.0,
    #: Which model grades the pairs. Empty means the baseline, i.e. the
    #: expensive model marks its own replacement — a bias AGAINST the result
    #: being claimed, which is the right direction.
    "audit_judge_model": "",
}

_lock = threading.Lock()
_cache: dict | None = None


def _read_file() -> dict:
    """Defaults plus whatever is actually saved on disk. No environment.

    Kept separate from `_read` because writing must never persist an
    environment override. `set()` used to read the merged view and write the
    whole thing back, so running `lane config <anything>` while LANE_PORT
    happened to be exported baked that port into the file permanently — and the
    symptom appeared later, as a server binding a port nobody asked for.
    """
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_FILE.is_file():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except Exception:
        pass  # a corrupt config must not stop the proxy from serving
    return cfg


def _read() -> dict:
    """What LANE should actually use: the file, with the environment on top."""
    cfg = _read_file()
    env_host, env_port = os.environ.get("LANE_HOST"), os.environ.get("LANE_PORT")
    if env_host:
        cfg["host"] = env_host
    if env_port and env_port.isdigit():
        cfg["port"] = int(env_port)
    return cfg


def all() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _read()
        return dict(_cache)


def get(key: str, default=None):
    return all().get(key, DEFAULTS.get(key, default))


def set(key: str, value) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting {key!r}; known: {', '.join(DEFAULTS)}")
    global _cache
    with _lock:
        # _read_file, never _read: an environment variable is a temporary
        # override for one run, not a preference anybody chose to save.
        cfg = _read_file()
        cfg[key] = value
        HOME.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        _cache = None       # the effective view still includes the environment


def reload() -> None:
    global _cache
    with _lock:
        _cache = None


def coerce(key: str, raw: str):
    """Turn a CLI string into the type the setting actually holds."""
    cur = DEFAULTS.get(key)
    if isinstance(cur, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(cur, int) and not isinstance(cur, bool):
        return int(raw)
    if isinstance(cur, float):
        return float(raw)
    if isinstance(cur, list):
        return [p.strip() for p in raw.split(",") if p.strip()]
    return raw
