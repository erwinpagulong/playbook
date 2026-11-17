"""Private storage for provider API keys.

Keys file: ``$XDG_DATA_HOME/crypto-playbook/keys.json``
(default ``~/.local/share/crypto-playbook/keys.json``), mode ``600``.

The file is shaped ``{"providers": {provider_id: key}}``. Key values are
never logged, printed or included in reports. Writes are atomic
(temp file in the target directory + ``os.replace``) and the file is
chmod'ed ``0o600`` after every write, including creation.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from engine.config import data_path


def keys_path(path: Path | None = None) -> Path:
    """Return the keys file path (``path`` override wins, else the default)."""
    if path is not None:
        return Path(path)
    return data_path() / "keys.json"


def load_keys(path: Path | None = None) -> dict:
    """Load the keys file at ``path`` (or the default path).

    Missing or corrupt file behaves as empty: ``{"providers": {}}``.
    """
    kpath = keys_path(path)
    empty = {"providers": {}}
    if not kpath.exists():
        return empty
    try:
        loaded = json.loads(kpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(loaded, dict):
        return empty
    providers = loaded.get("providers")
    if not isinstance(providers, dict):
        return empty
    return {
        "providers": {
            str(k): v
            for k, v in providers.items()
            if isinstance(v, str) and v
        }
    }


def _write_keys(data: dict, path: Path | None = None) -> None:
    kpath = keys_path(path)
    kpath.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=kpath.parent, prefix=".keys-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, kpath)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    os.chmod(kpath, 0o600)


def set_key(provider: str, key: str, path: Path | None = None) -> None:
    """Store ``key`` for ``provider``, preserving other providers."""
    data = load_keys(path)
    data["providers"][provider] = key
    _write_keys(data, path)


def clear_key(provider: str, path: Path | None = None) -> None:
    """Remove the key for ``provider``; other providers are untouched."""
    data = load_keys(path)
    data["providers"].pop(provider, None)
    _write_keys(data, path)


def mask(key: str) -> str:
    """Return a non-reversible hint for ``key`` safe to display.

    Never returns the full key: at most a prefix plus the last 4 chars.
    """
    if key.startswith("sk-"):
        prefix = "sk-…"
    else:
        prefix = "••••"
    if len(key) >= 5:
        return prefix + key[-4:]
    return prefix


def stored_key(provider: str, path: Path | None = None) -> str:
    """Return ONLY the key stored in ``keys.json`` for ``provider``.

    Never falls back to the environment; missing/corrupt files yield ``""``.
    """
    return load_keys(path)["providers"].get(provider, "")


def key_for(provider: str, config: dict, path: Path | None = None) -> str:
    """Return the key for ``provider``.

    Prefers a non-empty key stored in the keys file; falls back to the
    environment variable named by ``config["llm"]["api_key_env"]``;
    otherwise ``""``. Kept as the low-level legacy resolver; UI and the
    generation path use ``resolved_key`` below.
    """
    stored = stored_key(provider, path)
    if stored:
        return stored
    env_name = (config.get("llm") or {}).get("api_key_env") or ""
    if not env_name:
        return ""
    return os.environ.get(env_name, "")


def resolved_key(
    provider: str,
    config: dict,
    llm_config: dict,
    path: Path | None = None,
) -> str:
    """Return the effective key for ``provider`` in priority order.

    1. the key stored in ``keys.json`` for this provider;
    2. the env var named by the *effective* LLM config
       (``llm_config["api_key_env"]``) — the config override for the active
       provider, the preset's own variable for any other provider;
    3. the global legacy ``config["llm"]["api_key_env"]`` env var — a final
       fallback, applied only for the active provider (the provider the
       config actually describes), so a single global key can never mark
       unrelated providers as configured.

    No key value is logged or echoed. ``provider_list`` and the generation
    path both call this helper, so what the UI reports and what a call uses
    agree. ``llm_config`` is the already-resolved config from
    ``provider_llm_config``; passing it in avoids an import cycle.
    """
    stored = stored_key(provider, path)
    if stored:
        return stored
    llm = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    global_env = llm.get("api_key_env")
    candidates = [(llm_config or {}).get("api_key_env")]
    if provider == llm.get("provider"):
        candidates.append(global_env)
    for env_name in candidates:
        if not isinstance(env_name, str) or not env_name:
            continue
        value = os.environ.get(env_name, "")
        if value:
            return value
    return ""
