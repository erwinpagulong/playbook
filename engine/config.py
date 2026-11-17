"""Config load/save and validation for the Crypto Playbook plugin.

Config file: ``$XDG_CONFIG_HOME/crypto-playbook/config.json``
(default ``~/.config/crypto-playbook/config.json``).
Data dir:    ``$XDG_DATA_HOME/crypto-playbook/``
(default ``~/.local/share/crypto-playbook/``).
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path

COIN_PATTERN = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$")

DEFAULT_CONFIG: dict = {
    "coins": ["BTC/USDT", "ETH/USDT"],
    "interval_minutes": 60,
    "llm": {
        "provider": "openai",
        "fallback_provider": None,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "timeout_s": 60,
    },
}


def config_path() -> Path:
    """Return ``$XDG_CONFIG_HOME/crypto-playbook/config.json`` (XDG default)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "crypto-playbook" / "config.json"


def data_path() -> Path:
    """Return ``$XDG_DATA_HOME/crypto-playbook/`` (XDG default)."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "crypto-playbook"


def _deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config(path: Path | None = None) -> dict:
    """Load config JSON at ``path`` (or the default path), deep-merged over defaults.

    Missing file yields pure defaults. The returned dict is a fresh copy.
    """
    cfg_path = Path(path) if path is not None else config_path()
    data: dict = {}
    if cfg_path.exists():
        loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    return _deep_merge(DEFAULT_CONFIG, data)


def save_config(config: dict, path: Path | None = None) -> None:
    """Write ``config`` as pretty JSON to ``path`` (or the default path), atomically."""
    cfg_path = Path(path) if path is not None else config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=cfg_path.parent, prefix=".config-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, cfg_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def validate_config(config: dict) -> list[str]:
    """Return a list of human-readable problems; empty means the config is valid."""
    errors: list[str] = []

    coins = config.get("coins")
    if not isinstance(coins, list) or not coins:
        errors.append("coins: must be a non-empty list")
    else:
        for coin in coins:
            if not isinstance(coin, str) or not COIN_PATTERN.match(coin):
                errors.append(
                    f"coin {coin!r} is invalid; expected BASE/QUOTE like 'BTC/USDT'"
                )

    interval = config.get("interval_minutes")
    if isinstance(interval, bool) or not isinstance(interval, int) or interval < 5:
        errors.append(
            f"interval_minutes must be an integer >= 5, got {interval!r}"
        )

    llm = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    base_url = llm.get("base_url")
    if not isinstance(base_url, str) or not base_url.startswith(
        ("http://", "https://")
    ):
        errors.append(f"base_url must be an http(s) URL, got {base_url!r}")

    model = llm.get("model")
    if not isinstance(model, str) or not model.strip():
        errors.append("model must be a non-empty string")

    # Lazy import: engine.providers imports engine.keys, which imports this
    # module — importing at module top would create an import cycle.
    from engine.providers import PRESETS, is_valid_provider

    provider = llm.get("provider")
    if not is_valid_provider(provider):
        errors.append(
            f"provider must be one of {sorted(PRESETS)}, got {provider!r}"
        )

    fallback = llm.get("fallback_provider")
    if fallback is not None and not is_valid_provider(fallback):
        errors.append(
            f"fallback_provider must be one of {sorted(PRESETS)} or null, "
            f"got {fallback!r}"
        )
    elif (
        fallback is not None
        and isinstance(provider, str)
        and fallback == provider
    ):
        errors.append(
            f"fallback_provider must differ from provider, both are {provider!r}"
        )

    return errors
