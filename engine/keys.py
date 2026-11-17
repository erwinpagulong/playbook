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


def key_for(provider: str, config: dict, path: Path | None = None) -> str:
    """Return the key for ``provider``.

    Prefers a non-empty key stored in the keys file; falls back to the
    environment variable named by ``config["llm"]["api_key_env"]``;
    otherwise ``""``.
    """
    stored = load_keys(path)["providers"].get(provider, "")
    if stored:
        return stored
    env_name = (config.get("llm") or {}).get("api_key_env") or ""
    if not env_name:
        return ""
    return os.environ.get(env_name, "")
