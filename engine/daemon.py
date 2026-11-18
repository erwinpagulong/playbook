"""Loopback JSON daemon: HTTP API, generation scheduler, CLI target.

`build_server` binds a `ThreadingHTTPServer` on 127.0.0.1 and routes a
small JSON API that the QML panel consumes through `engine.cli`. Every
request must carry the private token published by `engine.auth`; loopback
alone is not access control on a shared machine:

    GET  /api/health          liveness probe -> {"status": "ok"}
    GET  /api/status          coins, interval, report count, run state
    GET  /api/coins           configured coins (bare JSON array)
    GET  /api/latest[?coin=]  newest report, or {"available": false}
    GET  /api/reports[?coin=] stored reports, newest first
    GET  /api/report?id=      one report by id
    GET  /api/config          effective config (defaults merged)
    POST /api/config          validate + atomically save; returns saved config
    GET  /api/providers       one row per preset (masked key state only)
    POST /api/providers/key   {"provider","key"} -> validate + store; {"ok":true}
    POST /api/providers/clear-key  {"provider"} -> remove stored key
    GET  /api/export?dest=    copy the reports dir to dest (default
                              ~/Documents/crypto-playbook-export); returns path
    POST /api/delete-reports  remove generated (non-sample) reports; count
    POST /api/regenerate      {"coin": ...} -> background run, {"started": true}

`main()` seeds sample reports into an empty store, loads the config,
kicks off one generation per configured coin when the active provider has
an effective key (stored or env), starts the interval scheduler (every
``interval_minutes``, default 60), and serves until interrupted. All
binds are loopback-only and every request is answered with JSON —
handlers catch their own errors instead of dropping the connection.
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import shutil
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from engine import auth, generate, report
from engine.config import (
    COIN_PATTERN,
    data_path,
    load_config,
    save_config,
    validate_config,
)
from engine.keys import clear_key, resolved_key, set_key
from engine.providers import is_valid_provider, provider_list, provider_llm_config

log = logging.getLogger(__name__)

#: The only address the daemon ever binds (design: loopback IPC).
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8099

#: Where `GET /api/export` writes when the caller gives no ``dest``.
def default_export_dir() -> Path:
    """``~/Documents/crypto-playbook-export`` (resolved at call time)."""
    return Path.home() / "Documents" / "crypto-playbook-export"

_GET_ROUTES = frozenset(
    {
        "/api/health",
        "/api/status",
        "/api/coins",
        "/api/latest",
        "/api/reports",
        "/api/report",
        "/api/config",
        "/api/export",
        "/api/providers",
    }
)
_POST_ROUTES = frozenset(
    {
        "/api/regenerate",
        "/api/config",
        "/api/delete-reports",
        "/api/providers/key",
        "/api/providers/clear-key",
    }
)


def _first(query: dict, key: str) -> str | None:
    """First value of ``key`` in a parsed query string, or None."""
    values = query.get(key)
    return values[0] if values else None


def _active_key_present(config: dict) -> bool:
    """Whether the active provider has an effective key (stored or env).

    Uses the same resolution as generation and ``/api/providers`` — a stored
    key for the active provider, its effective env var, or the legacy global
    variable — so the status banner and the startup-generation gate agree
    with what generation can actually use. Returns a boolean only; the key
    value is never read into state, logs or responses here.
    """
    llm = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    active = llm.get("provider")
    if not is_valid_provider(active):
        return False
    effective = provider_llm_config(str(active), config)
    return bool(resolved_key(str(active), config, effective))


# --------------------------------------------------------------------------
# Server state
# --------------------------------------------------------------------------

class PlaybookServer(ThreadingHTTPServer):
    """`ThreadingHTTPServer` carrying the daemon's live state.

    ``config`` is the effective config (defaults merged with the file);
    ``POST /api/config`` replaces it wholesale, and the scheduler reads it
    fresh each tick so changes land without a restart. ``stop_event`` stops
    the scheduler; ``generating`` (guarded by ``state_lock``) lists coins
    with a run in flight for ``GET /api/status``.
    """

    def __init__(self, server_address, handler_class, config, data_dir, token):
        super().__init__(server_address, handler_class)
        self.config = config
        self.data_dir = Path(data_dir)
        # Per-process secret for loopback callers; only the same account can
        # read the file the CLI uses to learn it (see engine.auth).
        self.auth_token = token
        self.stop_event = threading.Event()
        self.state_lock = threading.Lock()
        self.generating: set[str] = set()


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

def _generate(server: PlaybookServer, coin: str) -> dict:
    """Run one generation for ``coin``, tracked in ``server.generating``."""
    with server.state_lock:
        server.generating.add(coin)
    try:
        result = generate.generate_report(coin, server.config, server.data_dir)
    except Exception:  # noqa: BLE001 - a bad run must not kill the caller thread
        log.exception("generation failed for %s", coin)
        return {"report": None, "error": "generation failed; see daemon log"}
    finally:
        with server.state_lock:
            server.generating.discard(coin)
    if isinstance(result, dict):
        log.info(
            "generation for %s: report=%s error=%s",
            coin,
            result.get("report") is not None,
            result.get("error"),
        )
    return result


def regenerate_all(server: PlaybookServer) -> list[dict]:
    """Generate every configured coin once, in config order."""
    coins = server.config.get("coins")
    if not isinstance(coins, list):
        return []
    return [_generate(server, coin) for coin in coins]


def scheduler_loop(
    server: PlaybookServer,
    stop_event: threading.Event,
    wait=None,
) -> None:
    """Regenerate all coins every ``interval_minutes`` until stopped.

    ``wait(seconds) -> bool`` defaults to ``stop_event.wait`` and returns
    True when the loop should exit; tests inject a fake to drive ticks
    without sleeping. The interval is re-read from ``server.config`` on
    every cycle, so a ``POST /api/config`` lands on the next tick.
    """
    wait = stop_event.wait if wait is None else wait
    while True:
        minutes = server.config.get("interval_minutes", 60)
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            minutes = 60
        if wait(max(1, minutes) * 60):
            return
        coins = server.config.get("coins")
        log.info(
            "scheduler tick: regenerating %s",
            ", ".join(coins) if isinstance(coins, list) and coins else "no coins",
        )
        regenerate_all(server)


def start_scheduler(
    server: PlaybookServer,
) -> tuple[threading.Thread | None, threading.Thread]:
    """Start the scheduler, plus one immediate run when an LLM key is set.

    Returns ``(startup_thread | None, scheduler_thread)``. The startup
    thread regenerates every configured coin exactly once when the active
    provider has an effective key (stored, env or legacy — see
    ``_active_key_present``); the key's *value* is never read into logs or
    state. The scheduler thread waits a full interval before its first tick,
    so startup runs are never duplicated.
    """
    startup: threading.Thread | None = None
    if _active_key_present(server.config):
        startup = threading.Thread(
            target=regenerate_all,
            args=(server,),
            name="playbookd-startup",
            daemon=True,
        )
        startup.start()
    scheduler = threading.Thread(
        target=scheduler_loop,
        args=(server, server.stop_event),
        name="playbookd-scheduler",
        daemon=True,
    )
    scheduler.start()
    return startup, scheduler


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------

class PlaybookHandler(BaseHTTPRequestHandler):
    """Routes ``/api/*`` to the engine helpers; one thread per connection."""

    server_version = "playbookd"

    def log_message(self, fmt: str, *args) -> None:
        log.debug("%s %s", self.address_string(), fmt % args)

    def _send(self, status: int, payload, *, send_body: bool = True) -> None:
        """Answer with a compact JSON body (suppressed for HEAD requests)."""
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def _authorized(self) -> bool:
        """Whether the caller presented this daemon's private bearer token."""
        supplied = self.headers.get("Authorization", "")
        token = getattr(self.server, "auth_token", "")
        return bool(token) and hmac.compare_digest(supplied, f"Bearer {token}")

    def _reject_unauthorized(self) -> bool:
        """Answer 401 and return True when the caller has no valid token."""
        if self._authorized():
            return False
        self._send(401, {"error": "unauthorized"})
        return True

    def _json_body(self):
        """Parsed request body; a dict, or None when empty/invalid/non-object."""
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None

    # -- GET ---------------------------------------------------------------

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        route = parts.path
        query = parse_qs(parts.query)
        if self._reject_unauthorized():
            return
        try:
            if route == "/api/health":
                self._send(200, {"status": "ok"})
            elif route == "/api/status":
                self._send(200, self._status_payload())
            elif route == "/api/coins":
                self._send(200, list(self.server.config.get("coins") or []))
            elif route == "/api/latest":
                self._send(200, self._latest_payload(_first(query, "coin")))
            elif route == "/api/reports":
                self._send(
                    200,
                    report.list_reports(
                        self.server.data_dir, _first(query, "coin")
                    ),
                )
            elif route == "/api/report":
                self._send_report(_first(query, "id"))
            elif route == "/api/config":
                self._send(200, self.server.config)
            elif route == "/api/providers":
                self._send(200, provider_list(self.server.config))
            elif route == "/api/export":
                self._send(200, self._export_to(_first(query, "dest")))
            elif route in _POST_ROUTES:
                self._send(405, {"error": f"{route} only accepts POST"})
            else:
                self._send(404, {"error": f"unknown endpoint {route}"})
        except Exception as exc:  # noqa: BLE001 - answer JSON, never crash the socket
            log.exception("GET %s failed", route)
            self._send(500, {"error": str(exc)})

    def _status_payload(self) -> dict:
        llm_config = self.server.config.get("llm")
        llm_config = llm_config if isinstance(llm_config, dict) else {}
        key_env = llm_config.get("api_key_env")
        with self.server.state_lock:
            generating = sorted(self.server.generating)
        return {
            "status": "ok",
            "coins": list(self.server.config.get("coins") or []),
            "interval_minutes": self.server.config.get("interval_minutes"),
            "report_count": len(report.list_reports(self.server.data_dir)),
            "generating": generating,
            "llm_key_env": key_env,
            "llm_key_present": _active_key_present(self.server.config),
            "provider": llm_config.get("provider"),
            "fallback_provider": llm_config.get("fallback_provider"),
            "data_dir": str(self.server.data_dir),
        }

    def _latest_payload(self, coin: str | None) -> dict:
        """Newest report as ``{"available": True, "report": ...}``, or the
        bare placeholder ``{"available": False}`` when the store (or the
        coin filter) matches nothing."""
        reports = report.list_reports(self.server.data_dir, coin)
        if not reports:
            return {"available": False}
        return {"available": True, "report": reports[0]}

    def _send_report(self, report_id: str | None) -> None:
        if not report_id:
            self._send(400, {"error": "missing required query parameter: id"})
            return
        try:
            payload = report.load_report(self.server.data_dir, report_id)
        except FileNotFoundError:
            self._send(404, {"error": f"report not found: {report_id}"})
            return
        except ValueError as exc:
            self._send(500, {"error": str(exc)})
            return
        self._send(200, payload)

    def _export_to(self, dest_raw: str | None) -> dict:
        """Copy the reports directory into ``dest`` (or the default) and
        return its path plus the number of files copied."""
        dest = Path(dest_raw).expanduser() if dest_raw else default_export_dir()
        src = self.server.data_dir / "reports"
        dest.mkdir(parents=True, exist_ok=True)
        files = (
            [
                path
                for path in sorted(src.iterdir())
                if path.is_file() and path.suffix in (".json", ".md")
            ]
            if src.is_dir()
            else []
        )
        if dest.resolve() != src.resolve():
            for path in files:
                shutil.copy2(path, dest / path.name)
        return {"path": str(dest), "files": len(files)}

    # -- POST ---------------------------------------------------------------

    def do_POST(self) -> None:
        parts = urlsplit(self.path)
        route = parts.path
        if self._reject_unauthorized():
            return
        try:
            if route == "/api/regenerate":
                body = self._json_body()
                if body is None:
                    self._send(400, {"error": "body must be a JSON object"})
                    return
                coin = body.get("coin")
                if not isinstance(coin, str) or not COIN_PATTERN.match(coin):
                    self._send(
                        400,
                        {"error": "coin is required, BASE/QUOTE like 'BTC/USDT'"},
                    )
                    return
                threading.Thread(
                    target=_generate,
                    args=(self.server, coin),
                    name=f"playbookd-gen-{coin}",
                    daemon=True,
                ).start()
                self._send(200, {"started": True, "coin": coin})
            elif route == "/api/config":
                body = self._json_body()
                if body is None:
                    self._send(400, {"error": "body must be a JSON object"})
                    return
                errors = validate_config(body)
                if errors:
                    self._send(400, {"errors": errors})
                    return
                save_config(body)  # atomic write to the XDG config path
                # Re-merge over defaults so partial-but-valid bodies still
                # serve a complete config to GET and to the scheduler.
                self.server.config = load_config()
                self._send(200, self.server.config)
            elif route == "/api/delete-reports":
                self._send(200, {"deleted": self._delete_reports()})
            elif route == "/api/providers/key":
                body = self._json_body()
                if body is None:
                    self._send(400, {"error": "body must be a JSON object"})
                    return
                provider = body.get("provider")
                if not is_valid_provider(provider):
                    self._send(400, {"error": "unknown provider"})
                    return
                key = body.get("key")
                if not isinstance(key, str) or not key.strip():
                    self._send(400, {"error": "key must be a non-empty string"})
                    return
                set_key(provider, key)
                # The key itself is never echoed back.
                self._send(200, {"ok": True})
            elif route == "/api/providers/clear-key":
                body = self._json_body()
                if body is None:
                    self._send(400, {"error": "body must be a JSON object"})
                    return
                provider = body.get("provider")
                if not is_valid_provider(provider):
                    self._send(400, {"error": "unknown provider"})
                    return
                clear_key(provider)
                self._send(200, {"ok": True})
            elif route in _GET_ROUTES:
                self._send(405, {"error": f"{route} only accepts GET"})
            else:
                self._send(404, {"error": f"unknown endpoint {route}"})
        except Exception as exc:  # noqa: BLE001 - answer JSON, never crash the socket
            log.exception("POST %s failed", route)
            self._send(500, {"error": str(exc)})

    def _delete_reports(self) -> int:
        """Remove generated report files (JSON + markdown), keeping samples.

        Returns the number of reports removed; sample reports (``sample:
        true``) and anything unreadable are left untouched.
        """
        reports_dir = self.server.data_dir / "reports"
        deleted = 0
        if not reports_dir.is_dir():
            return deleted
        for json_path in sorted(reports_dir.glob("*.json")):
            try:
                entry = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(entry, dict) or entry.get("sample"):
                continue
            for path in (json_path, json_path.with_suffix(".md")):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            deleted += 1
        return deleted

    # -- unsupported verbs --------------------------------------------------

    def _method_not_allowed(self, *, send_body: bool = True) -> None:
        """Shared JSON 405 for verbs this API does not implement."""
        self._send(405, {"error": "method not allowed"}, send_body=send_body)

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def do_HEAD(self) -> None:
        # HEAD answers the same JSON 405 but carries no body (HTTP
        # semantics: headers only, Content-Length still declared).
        self._method_not_allowed(send_body=False)

    def send_error(self, code, message=None, explain=None) -> None:
        """Protocol-level errors answer JSON, never the stock HTML page.

        Covers everything that bypasses ``do_*``: unknown verbs (``TRACE``,
        custom methods), bad request lines, and unsupported HTTP versions —
        so every request gets JSON in/out, per the catch-all contract.
        """
        try:
            default = HTTPStatus(code).phrase
        except ValueError:
            default = "error"
        if message is None:
            message = default
        self.log_error("code %d, message %s", code, message)
        self.send_response(code, message)
        body = json.dumps(
            {"error": message}, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        # ``command`` is None until the request line parses; only a real
        # HEAD must omit the body.
        if getattr(self, "command", None) != "HEAD":
            self.wfile.write(body)


# --------------------------------------------------------------------------
# Server construction and main()
# --------------------------------------------------------------------------

def build_server(
    config: dict, data_dir, port: int = DEFAULT_PORT
) -> PlaybookServer:
    """Bind a loopback `ThreadingHTTPServer` serving ``config``/``data_dir``.

    The server is created and bound (always on 127.0.0.1) but not served:
    callers run ``serve_forever`` themselves. Tests pass ``port=0`` to get
    an ephemeral port; ``main`` uses ``DEFAULT_PORT``. A fresh bearer token
    is published for the CLI before the socket starts accepting requests.
    """
    token = auth.issue_token()
    return PlaybookServer(
        (DEFAULT_HOST, port), PlaybookHandler, config, data_dir, token
    )


def main(argv=None) -> int:
    """Seed samples, start generation + scheduler, serve on loopback."""
    parser = argparse.ArgumentParser(
        prog="playbookd", description="Crypto Playbook loopback daemon"
    )
    parser.add_argument(
        "-port",
        type=int,
        default=DEFAULT_PORT,
        help=(
            f"TCP port on {DEFAULT_HOST} (default {DEFAULT_PORT}; "
            "0 picks a free port)"
        ),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config()
    data_dir = data_path()
    report.seed_samples(data_dir)  # no-op when the store already has reports
    server = build_server(config, data_dir, port=args.port)
    start_scheduler(server)
    host, port = server.server_address[:2]
    print(f"playbookd listening on {host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop_event.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
