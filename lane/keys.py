"""
keys.py — where provider API keys come from, in priority order.

The keyring is tried first and the environment second, deliberately. A user who
has run `lane keys set` has expressed an intent to store the key properly; an
environment variable left over from another tool should not silently override
it. The reverse order would make `lane keys set` look broken.

LANE never writes a key to its own config file. If the keyring is unavailable
(headless Linux with no Secret Service, most commonly) the fallback is the
environment, and `lane doctor` says so rather than quietly inventing a
plaintext store the user did not ask for.
"""

from __future__ import annotations

import os

SERVICE = "lane-router"

#: provider -> (env var, human name, where to get one)
PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "env": "ANTHROPIC_API_KEY",
        "name": "Anthropic",
        "console": "https://console.anthropic.com/settings/keys",
        "prefix": "sk-ant-",
    },
    "openai": {
        "env": "OPENAI_API_KEY",
        "name": "OpenAI",
        "console": "https://platform.openai.com/api-keys",
        "prefix": "sk-",
    },
    "google": {
        "env": "GOOGLE_API_KEY",
        "name": "Google Gemini",
        "console": "https://aistudio.google.com/apikey",
        "prefix": "",
    },
}


def _keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def keyring_available() -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:  # a backend can import and still refuse to operate
        kr.get_password(SERVICE, "__probe__")
        return True
    except Exception:
        return False


def get(provider: str) -> str | None:
    provider = provider.lower().strip()
    if provider not in PROVIDERS:
        return None
    kr = _keyring()
    if kr is not None:
        try:
            val = kr.get_password(SERVICE, provider)
            if val:
                return val.strip()
        except Exception:
            pass
    val = os.environ.get(PROVIDERS[provider]["env"])
    return val.strip() if val else None


def set(provider: str, key: str) -> str:
    """Store a key. Returns where it landed, for the caller to report."""
    provider = provider.lower().strip()
    if provider not in PROVIDERS:
        raise KeyError(f"unknown provider {provider!r}; "
                       f"known: {', '.join(PROVIDERS)}")
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, provider, key.strip())
            return "system keyring"
        except Exception:
            pass
    raise RuntimeError(
        "no usable keyring on this machine — export "
        f"{PROVIDERS[provider]['env']} in your environment instead")


def delete(provider: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, provider.lower().strip())
        return True
    except Exception:
        return False


def source(provider: str) -> str | None:
    """Which store answered for this provider — for `lane doctor`."""
    kr = _keyring()
    if kr is not None:
        try:
            if kr.get_password(SERVICE, provider):
                return "keyring"
        except Exception:
            pass
    if os.environ.get(PROVIDERS.get(provider, {}).get("env", "")):
        return "environment"
    return None


def present() -> list[str]:
    """Providers LANE can actually call right now."""
    return [p for p in PROVIDERS if get(p)]


def mask(key: str | None) -> str:
    if not key:
        return "—"
    return f"{key[:7]}…{key[-4:]}" if len(key) > 14 else "…" * 6
