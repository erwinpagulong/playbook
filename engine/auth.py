"""Private token for the daemon's loopback API.

Token file: ``$XDG_DATA_HOME/crypto-playbook/daemon.token`` (default
``~/.local/share/crypto-playbook/daemon.token``), mode ``600``.

`playbookd` creates a fresh random token each time it starts and requires it on
every API request. `playbook` reads the same file and sends the token in an
``Authorization: Bearer`` header. Loopback alone is not access control: any
local account can connect to 127.0.0.1, but it cannot read another account's
0600 token file.

The token file can outlive a daemon that exits without cleaning up, so the CLI
does not trust its presence: before sending the token or a provider key it
sends a fresh nonce to the listener and requires an HMAC of that nonce under
the token (`proof`). A replacement listener cannot answer without the token.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import tempfile
from pathlib import Path

from engine.config import data_path


def proof(token: str, nonce: str) -> str:
    """Hex HMAC-SHA256 of ``nonce`` under ``token`` (daemon identity proof).

    Only a process that read the daemon's 0600 token file can produce the
    matching value for a fresh nonce, so it lets the CLI verify the listener
    before sending any secret. The nonce is never secret.
    """
    return hmac.new(
        token.encode("ascii"), nonce.encode("ascii"), hashlib.sha256
    ).hexdigest()


def token_path(path: Path | None = None) -> Path:
    """Return the token file path (``path`` override wins, else the default)."""
    return Path(path) if path is not None else data_path() / "daemon.token"


def issue_token(path: Path | None = None) -> str:
    """Create a fresh token, publish it privately, and return it."""
    token = secrets.token_urlsafe(32)
    target = token_path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(
        dir=target.parent, prefix=".token-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(token + "\n")
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    os.chmod(target, 0o600)
    return token


def read_token(path: Path | None = None) -> str:
    """Return the published token, or ``""`` when it is missing/unreadable."""
    try:
        return token_path(path).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return ""


def clear_token(path: Path | None = None) -> None:
    """Remove a token left behind by a previous daemon (best effort)."""
    try:
        token_path(path).unlink()
    except FileNotFoundError:
        pass
