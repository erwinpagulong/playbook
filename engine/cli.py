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
    playbook set-key <provider> <key>
    playbook clear-key <provider>

Loopback calls never consult proxy environment variables.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ADDR = "127.0.0.1:8099"
TIMEOUT_S = 60

#: Loopback-only opener: the daemon must never be reached via http_proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class DaemonUnreachable(RuntimeError):
    """The daemon could not be contacted at all (refused, timed out...)."""


def _compact(payload) -> str:
    """Serialize ``payload`` as compact JSON (no spaces)."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _path(base: str, params: dict | None = None) -> str:
    if not params:
        return base
    return base + "?" + urllib.parse.urlencode(params)


def _request(addr: str, method: str, path: str, payload=None) -> tuple[int, bytes]:
    """One HTTP call; returns ``(status, raw body)``.

    HTTP error responses are returned like any other answer (they carry a
    JSON body too); only a failure to reach the daemon raises.
    """
    url = f"http://{addr}{path}"
    data = None
    headers = {}
    if method == "POST":
        data = _compact(payload if payload is not None else {}).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(request, timeout=TIMEOUT_S) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:  # subclass of URLError: catch first
        return error.code, error.read()
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", None) or error
        raise DaemonUnreachable(
            f"cannot reach playbook daemon at {addr}: {reason}"
        ) from error


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
    set_key = sub.add_parser("set-key", parents=[addr_parent])
    set_key.add_argument("provider")
    set_key.add_argument("key")
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
        # The key travels in the request body only; the daemon's {"ok": true}
        # answer is printed as-is, so the key never appears in CLI output.
        method, path, payload = (
            "POST",
            "/api/providers/key",
            {"provider": args.provider, "key": args.key},
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
        status, raw = _request(args.addr, method, path, payload)
    except DaemonUnreachable as error:
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
