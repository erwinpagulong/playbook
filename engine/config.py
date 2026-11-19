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
from urllib.parse import urlsplit

COIN_PATTERN = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$")

#: Hosts where plaintext http is allowed for a local test endpoint.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

DEFAULT_CONFIG: dict = {
    "coins": ["BTC/USDT", "ETH/USDT"],
    "interval_minutes": 60,
    "llm": {
        "provider": "openai",
        "fallback_provider": None,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        # The Custom destination lives in its own fields. The generic
        # base_url/model belong to the active provider and may still hold the
        # previous provider's values when Custom is selected, so they are
        # never reused for the Custom endpoint.
        "custom_base_url": "",
        "custom_model": "",
        "api_key_env": "OPENAI_API_KEY",
        "timeout_s": 60,
    },
}


def base_url_problem(base_url: object) -> str | None:
    """Return why ``base_url`` is unsafe for a bearer key, or None when safe.

    Remote endpoints must use https: a plaintext http endpoint would expose
    the provider key in transit. Loopback http stays allowed for local test
    servers. Shared by save-time validation and send-time enforcement, so a
    hand-edited config cannot bypass the rule.

    ``urlsplit`` is more lenient than requests/urllib3, so a URL that parses
    as loopback here could still send the key elsewhere. Reject the inputs
    where the two disagree: a backslash in the authority (requests treats it
    as a path separator), whitespace/control characters, an empty host and
    an unusable port.
    """
    if not isinstance(base_url, str) or not base_url:
        return f"base_url must be an http(s) URL, got {base_url!r}"
    # requests/urllib3 read '\' as a path separator, so urlsplit and the HTTP
    # client can disagree on which host receives the bearer key. Whitespace
    # and control characters are likewise stripped or reinterpreted by
    # requests. Neither belongs in an endpoint URL.
    if "\\" in base_url:
        return "base_url must not contain a backslash"
    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in base_url):
        return "base_url must not contain whitespace or control characters"
    try:
        parts = urlsplit(base_url)
        scheme = parts.scheme
        netloc = parts.netloc
        host = (parts.hostname or "").lower()
        # Reading .port forces urlsplit to validate it (e.g. ":8o80" raises).
        port = parts.port
    except ValueError:
        return f"base_url must be an http(s) URL, got {base_url!r}"
    if scheme not in ("http", "https") or not netloc or not host:
        return f"base_url must be an http(s) URL, got {base_url!r}"
    if port is not None and not 0 < port <= 65535:
        return f"base_url must be an http(s) URL, got {base_url!r}"
    if scheme == "http" and host not in LOOPBACK_HOSTS:
        return (
            "base_url must use https for a remote endpoint; "
            "http is only allowed on loopback"
        )
    return None


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
    problem = base_url_problem(base_url)
    if problem is not None:
        errors.append(problem)

    custom_base_url = llm.get("custom_base_url")
    if custom_base_url is not None and not isinstance(custom_base_url, str):
        errors.append(
            f"custom_base_url must be an http(s) URL, got {custom_base_url!r}"
        )
    elif custom_base_url:
        problem = base_url_problem(custom_base_url)
        if problem is not None:
            errors.append(f"custom_base_url: {problem}")

    custom_model = llm.get("custom_model")
    if custom_model is not None and not isinstance(custom_model, str):
        errors.append(
            f"custom_model must be a non-empty string, got {custom_model!r}"
        )

    model = llm.get("model")
    if not isinstance(model, str) or not model.strip():
        errors.append("model must be a non-empty string")

    # Lazy import: engine.providers imports engine.keys, which imports this
    # module — importing at module top would create an import cycle.
    from engine.providers import PRESETS, is_valid_provider

    def require_custom_destination(which: str) -> None:
        """A Custom provider/fallback needs its own endpoint and model."""
        if not (isinstance(custom_base_url, str) and custom_base_url.strip()):
            errors.append(f"custom_base_url must be set when {which} is 'custom'")
        if not (isinstance(custom_model, str) and custom_model.strip()):
            errors.append(
                f"custom_model must be a non-empty string when {which} is 'custom'"
            )

    provider = llm.get("provider")
    if not is_valid_provider(provider):
        errors.append(
            f"provider must be one of {sorted(PRESETS)}, got {provider!r}"
        )
    elif provider == "custom":
        # Custom has no public preset endpoint, so selecting it without its
        # own destination would otherwise reuse whatever URL was active
        # before — and send the Custom key there.
        require_custom_destination("provider")

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
    elif fallback == "custom":
        # The same Custom key must not be sent to a stale URL when it is
        # reached as the fallback of a failing primary provider.
        require_custom_destination("fallback_provider")

    return errors
