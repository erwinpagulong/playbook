"""Thin JSON CLI helper: talk to the playbook daemon over loopback.

Every command performs exactly one HTTP call against `engine.daemon` and
prints the JSON response to stdout in compact form (no spaces), so QML
can hand the output straight to ``JSON.parse``. Errors — daemon
unreachable, an HTTP 4xx/5xx answer, or a malformed ``set-config``
argument — print ``{"error": ...}`` and exit non-zero.

``-addr`` (default ``127.0.0.1:8099``) may appear before or after the
command:

    playbook coins [-addr HOST:PORT]
    playbook latest|reports [COIN]
    playbook report <id>
    playbook status | coins | config | delete-reports
    playbook regenerate <coin>
    playbook set-config '<json>'
    playbook export [dest_dir]
    playbook providers
    playbook set-key <provider>          # key is read from stdin, never argv
    playbook clear-key <provider>

Before sending the private bearer token published in
`$XDG_DATA_HOME/crypto-playbook/daemon.token` — and before sending a provider
key — every call makes the listener prove it holds that token: the CLI sends a
fresh nonce to `GET /api/hello` and checks the HMAC answer on the same
connection. A stale token file left behind by a daemon that exited abnormally
therefore cannot be used to hand secrets to a replacement listener. Loopback
calls never consult proxy environment variables.
"""

from __future__ import annotations

import argparse
import hmac
import http.client
import json
import secrets
import sys
import urllib.parse

from engine import auth

DEFAULT_ADDR = "127.0.0.1:8099"
TIMEOUT_S = 60
#: A provider key is one line; guard against unbounded stdin on a stuck caller.
MAX_KEY_CHARS = 8192


class DaemonUnreachable(RuntimeError):
    """The daemon could not be contacted at all (refused, timed out...)."""


class DaemonUnverified(RuntimeError):
    """The listener did not prove it holds the daemon's live token."""


def _compact(payload) -> str:
    """Serialize ``payload`` as compact JSON (no spaces)."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _path(base: str, params: dict | None = None) -> str:
    if not params:
        return base
    return base + "?" + urllib.parse.urlencode(params)


def _split_addr(addr: str) -> tuple[str, int]:
    """Split ``HOST:PORT`` (``[v6]:port`` allowed) for ``http.client``."""
    host, sep, port_text = addr.rpartition(":")
    if not sep or not host or not port_text.isdigit():
        raise ValueError(f"invalid daemon address: {addr}")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host, int(port_text)


def _verify_daemon(conn: http.client.HTTPConnection, token: str) -> None:
    """Make the listener prove it holds ``token`` before sending it anything.

    The nonce request carries no credential. Only a process that read the
    daemon's 0600 token file can return the matching HMAC, so a listener
    squatting on the port after an abnormal daemon exit cannot pass. The
    caller keeps this connection for the real request, so the verified peer
    is also the peer that receives it; a response that closes the socket is
    rejected instead of letting the client reconnect to someone else.
    """
    nonce = secrets.token_hex(32)
    conn.request("GET", f"/api/hello?nonce={nonce}")
    response = conn.getresponse()
    raw = response.read()
    supplied = ""
    if response.status == 200:
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("proof"), str):
            supplied = payload["proof"]
    # ``will_close`` matters: the bearer token and body must follow on this
    # very socket, not on a reconnection http.client would make to a listener
    # that took the port after the proof.
    if response.will_close or not hmac.compare_digest(
        supplied, auth.proof(token, nonce)
    ):
        raise DaemonUnverified(
            "daemon identity could not be verified; restart the daemon"
        )


def _request(
    addr: str, method: str, path: str, payload=None, token: str = ""
) -> tuple[int, bytes]:
    """One verified HTTP call; returns ``(status, raw body)``.

    The listener proves it holds ``token`` on the same connection before the
    Authorization header or request body is sent. HTTP error responses are
    returned like any other answer (they carry a JSON body too); only a
    failure to reach or verify the daemon raises.
    """
    try:
        host, port = _split_addr(addr)
    except ValueError as error:
        raise DaemonUnreachable(str(error)) from error
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if method == "POST":
        data = _compact(payload if payload is not None else {}).encode("utf-8")
        headers["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection(host, port, timeout=TIMEOUT_S)
    try:
        _verify_daemon(conn, token)
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    except (http.client.HTTPException, OSError) as error:
        raise DaemonUnreachable(
            f"cannot reach playbook daemon at {addr}: {error}"
        ) from error
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="playbook",
        description="Query the Crypto Playbook daemon; prints compact JSON.",
    )
    parser.add_argument(
        "-addr",
        default=DEFAULT_ADDR,
        help=f"daemon host:port (default {DEFAULT_ADDR})",
    )
    # Shared parent so `-addr` also works after the command; SUPPRESS keeps
    # the subparser from clobbering a value parsed before the command.
    addr_parent = argparse.ArgumentParser(add_help=False)
    addr_parent.add_argument("-addr", default=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", required=True)

    latest = sub.add_parser("latest", parents=[addr_parent])
    latest.add_argument("coin", nargs="?", help="BASE/QUOTE filter (optional)")
    reports = sub.add_parser("reports", parents=[addr_parent])
    reports.add_argument("coin", nargs="?", help="BASE/QUOTE filter (optional)")
    one = sub.add_parser("report", parents=[addr_parent])
    one.add_argument("report_id", metavar="id")
    sub.add_parser("status", parents=[addr_parent])
    sub.add_parser("coins", parents=[addr_parent])
    sub.add_parser("providers", parents=[addr_parent])
    set_key = sub.add_parser(
        "set-key",
        parents=[addr_parent],
        help="store a provider key read from stdin (never from argv)",
    )
    set_key.add_argument("provider")
    clear_key_cmd = sub.add_parser("clear-key", parents=[addr_parent])
    clear_key_cmd.add_argument("provider")
    regenerate = sub.add_parser("regenerate", parents=[addr_parent])
    regenerate.add_argument("coin", help="BASE/QUOTE like BTC/USDT")
    sub.add_parser("config", parents=[addr_parent])
    set_config = sub.add_parser("set-config", parents=[addr_parent])
    set_config.add_argument("json_text", metavar="json")
    export = sub.add_parser("export", parents=[addr_parent])
    export.add_argument("dest_dir", nargs="?", help="target directory (optional)")
    sub.add_parser("delete-reports", parents=[addr_parent])
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    token = auth.read_token()
    if not token:
        print(_compact({"error": "daemon token is missing; restart the daemon"}))
        return 1
    method, path, payload = "GET", "/", None

    if args.command == "latest":
        path = _path("/api/latest", {"coin": args.coin} if args.coin else None)
    elif args.command == "reports":
        path = _path("/api/reports", {"coin": args.coin} if args.coin else None)
    elif args.command == "report":
        path = _path("/api/report", {"id": args.report_id})
    elif args.command == "status":
        path = "/api/status"
    elif args.command == "coins":
        path = "/api/coins"
    elif args.command == "providers":
        path = "/api/providers"
    elif args.command == "set-key":
        # The key arrives on stdin, never in argv (which other accounts can
        # read) and never in CLI output: only the daemon's {"ok": true} answer
        # is printed. It travels to the daemon in the request body.
        raw_key = sys.stdin.read(MAX_KEY_CHARS + 1)
        if len(raw_key) > MAX_KEY_CHARS:
            print(_compact({"error": "key is too long"}))
            return 1
        key = raw_key.strip()
        if not key:
            print(_compact({"error": "paste a key on stdin"}))
            return 1
        method, path, payload = (
            "POST",
            "/api/providers/key",
            {"provider": args.provider, "key": key},
        )
    elif args.command == "clear-key":
        method, path, payload = (
            "POST",
            "/api/providers/clear-key",
            {"provider": args.provider},
        )
    elif args.command == "regenerate":
        method, path, payload = "POST", "/api/regenerate", {"coin": args.coin}
    elif args.command == "config":
        path = "/api/config"
    elif args.command == "set-config":
        try:
            payload = json.loads(args.json_text)
        except ValueError as error:
            print(_compact({"error": f"invalid JSON argument: {error}"}))
            return 1
        if not isinstance(payload, dict):
            print(_compact({"error": "set-config expects a JSON object"}))
            return 1
        method, path = "POST", "/api/config"
    elif args.command == "export":
        path = _path("/api/export", {"dest": args.dest_dir} if args.dest_dir else None)
    elif args.command == "delete-reports":
        method, path, payload = "POST", "/api/delete-reports", {}

    try:
        status, raw = _request(args.addr, method, path, payload, token)
    except (DaemonUnreachable, DaemonUnverified) as error:
        print(_compact({"error": str(error)}))
        return 1
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {"error": f"daemon returned a non-JSON response (HTTP {status})"}
    print(_compact(body))
    return 0 if status < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
