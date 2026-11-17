"""Report schema, markdown rendering, and seeded sample reports.

A report is a plain JSON-serializable dict that snapshots one generation:
the coin, the quote snapshot, the per-timeframe indicator payload, the
entry/exit levels, a prediction block and the risk rules. `save_report`
persists it atomically as ``data_dir/reports/<id>.json`` plus a rendered
``<id>.md`` twin for readers that want plain markdown.

Report ids embed a microsecond-precision UTC timestamp
(``BTC-USDT-20261116T130000123456Z``) so several generations in the same
second — or the same microsecond — never collide; a process-local lock
bumps the clock forward when needed so back-to-back ids stay distinct.

`seed_samples` writes the two bundled documents from ``samples/`` once, so
the dashboard has content on first run; their reports carry the document
text in ``source_markdown`` and render verbatim.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 1

#: Bundled sample documents, relative to the repository root.
SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"

#: (report id, sample filename, generated_at) for the two seeded reports.
SAMPLE_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "sample-playbook-20261116",
        "BTC_USDT_PLAYBOOK_2026-11-16.md",
        "2026-11-16T12:38:00+00:00",
    ),
    (
        "sample-prediction-20261116",
        "BTC_USDT_PREDICTION-2026-11-16.md",
        "2026-11-16T12:50:00+00:00",
    ),
)

DEFAULT_RISK_RULES: tuple[str, ...] = (
    "Risk at most 1% of equity on any single position.",
    "Honor the listed stop; never widen it to avoid a loss.",
    "No pyramiding into a losing position.",
    "Skip any setup whose reward:risk is below 1.5.",
)

# Guards the id clock so two reports generated within the same microsecond
# (or on a coarse-grained clock) still receive distinct timestamps.
_id_lock = threading.Lock()
_last_id_time: datetime | None = None


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

def _now_utc() -> datetime:
    """UTC now, monotonically bumped by ≥1µs from the previous id."""
    global _last_id_time
    with _id_lock:
        now = datetime.now(timezone.utc)
        if _last_id_time is not None and now <= _last_id_time:
            now = _last_id_time + timedelta(microseconds=1)
        _last_id_time = now
        return now


def new_report(coin: str, snapshot: dict, analysis: dict, levels: dict) -> dict:
    """Build a fresh report dict for `coin`.

    `snapshot` is the quote snapshot, `analysis` maps timeframe -> indicator
    payload (stored as `indicators`) and `levels` is the entry/exit map from
    `engine.levels.build_levels`. Prediction and risk rules start at their
    defaults; callers may enrich the dict before saving.
    """
    now = _now_utc()
    report: dict = {
        "schema_version": SCHEMA_VERSION,
        "id": f"{coin.replace('/', '-')}-{now.strftime('%Y%m%dT%H%M%S%f')}Z",
        "coin": coin,
        "generated_at": now.isoformat(),
        "sample": False,
        "snapshot": snapshot,
        "indicators": analysis,
        "levels": levels,
        "prediction": {"available": False},
        "risk_rules": list(DEFAULT_RISK_RULES),
    }
    report["markdown"] = render_markdown(report)
    return report


# --------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------

def _table(headers: list[str], rows: list[list[object]]) -> str:
    """A markdown table; header row plus separator plus one row per entry."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _fmt(value: object) -> str:
    return "—" if value is None else str(value)


def _snapshot_section(snapshot: dict) -> str:
    sources = snapshot.get("sources") if isinstance(snapshot, dict) else None
    if isinstance(sources, list) and sources:
        rows = [
            [
                _fmt(source.get("source")),
                _fmt(source.get("price")),
                _fmt(source.get("change_pct")),
            ]
            for source in sources
            if isinstance(source, dict)
        ]
        if rows:
            return _table(["Source", "Price", "24h change %"], rows)
    return "_No snapshot data._"


def _indicator_section(indicators: dict) -> str:
    if not isinstance(indicators, dict) or not indicators:
        return "_No indicator data._"
    rows: list[list[object]] = []
    for timeframe, payload in indicators.items():
        data = payload if isinstance(payload, dict) else {}
        bands = data.get("bollinger") or {}
        macd = data.get("macd") or {}
        rows.append(
            [
                timeframe,
                _fmt(data.get("price")),
                _fmt(data.get("rsi")),
                _fmt(macd.get("hist")),
                _fmt(data.get("trend")),
                f"{_fmt(bands.get('lower'))} / {_fmt(bands.get('mid'))} / {_fmt(bands.get('upper'))}",
                _fmt(data.get("atr")),
            ]
        )
    return _table(
        ["TF", "Price", "RSI(14)", "MACD hist", "Trend", "BB lower / mid / upper", "ATR(14)"],
        rows,
    )


def _levels_section(levels: dict) -> str:
    data = levels if isinstance(levels, dict) else {}
    key_levels = data.get("key_levels") or {}
    parts: list[str] = []
    support = key_levels.get("support") or []
    resistance = key_levels.get("resistance") or []
    if support or resistance:
        parts.append(
            "- **Support:** "
            + (" · ".join(str(v) for v in support) if support else "—")
        )
        parts.append(
            "- **Resistance:** "
            + (" · ".join(str(v) for v in resistance) if resistance else "—")
        )
    positions = data.get("positions") or []
    if positions:
        rows = [
            [
                _fmt(p.get("timeframe")),
                _fmt(p.get("direction")),
                _fmt(p.get("label")),
                _fmt(p.get("entry")),
                _fmt(p.get("zone")),
                _fmt(p.get("tp1")),
                _fmt(p.get("tp2")),
                _fmt(p.get("stop")),
                _fmt(p.get("rr")),
            ]
            for p in positions
            if isinstance(p, dict)
        ]
        parts.append(
            _table(
                ["TF", "Dir", "Setup", "Entry", "Zone", "TP1", "TP2", "Stop", "R:R"],
                rows,
            )
        )
    else:
        parts.append("_No positions._")
    return "\n\n".join(parts)


def _prediction_section(prediction: dict) -> str:
    data = prediction if isinstance(prediction, dict) else {}
    # Surface which provider actually answered (and whether it was the
    # fallback) when the generation path recorded that metadata.
    answered = ""
    provider = str(data.get("provider") or "").strip()
    if provider:
        model = str(data.get("model") or "").strip()
        label = f"Answered by {provider}"
        if model:
            label += f" / {model}"
        if data.get("fallback_used"):
            label += " (fallback)"
        answered = label + "\n\n"
    if not data.get("available"):
        message = (
            "Prediction: **not available** — no scenario model ran for this "
            "report."
        )
        reason = str(data.get("reason") or "").strip()
        if reason:
            message += f" Reason: {reason}"
        return answered + message
    scenarios = data.get("scenarios") or []
    if not scenarios:
        return answered + "Prediction: available, but no scenarios were recorded."
    headers: list[str] = []
    for scenario in scenarios:
        if isinstance(scenario, dict):
            for key in scenario:
                if key not in headers:
                    headers.append(key)
    rows = [
        [scenario.get(header) for header in headers]
        for scenario in scenarios
        if isinstance(scenario, dict)
    ]
    return answered + _table(headers or ["scenario"], rows)


def _risk_section(risk_rules: object) -> str:
    if not risk_rules:
        return "_No risk rules recorded._"
    lines = []
    for rule in risk_rules:
        if isinstance(rule, dict):
            rendered = " · ".join(f"{key}: {value}" for key, value in rule.items())
        else:
            rendered = str(rule)
        lines.append(f"- {rendered}")
    return "\n".join(lines)


def render_markdown(report: dict) -> str:
    """Render `report` as markdown.

    A report carrying `source_markdown` (the seeded samples) is returned
    verbatim; otherwise the sections are built from the report's fields.
    Always emits the required section headings, even for an empty report.
    """
    source = report.get("source_markdown")
    if isinstance(source, str) and source:
        return source

    coin = report.get("coin", "?")
    header = [
        f"# {coin} Playbook Report",
        "",
        f"> Generated: {report.get('generated_at', '?')}"
        f" · schema v{report.get('schema_version', SCHEMA_VERSION)}"
        + (" · sample" if report.get("sample") else ""),
    ]
    sections = [
        "\n".join(header),
        "## Market snapshot\n\n" + _snapshot_section(report.get("snapshot") or {}),
        "## Indicator dashboard\n\n" + _indicator_section(report.get("indicators") or {}),
        "## ENTRY & EXIT\n\n" + _levels_section(report.get("levels") or {}),
        "## Prediction\n\n" + _prediction_section(report.get("prediction") or {}),
        "## Risk rules\n\n" + _risk_section(report.get("risk_rules")),
    ]
    return "\n\n---\n\n".join(sections) + "\n"


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def _atomic_write(path: Path, text: str) -> None:
    """Write `text` to `path` via a temp file + rename; never half-written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def save_report(data_dir: Path, report: dict) -> Path:
    """Persist `report` under ``data_dir/reports/`` as JSON + rendered .md.

    Both files are written atomically; the stored JSON's `markdown` field
    always matches the rendered `.md` twin. Returns the JSON path.
    """
    reports_dir = Path(data_dir) / "reports"
    markdown = render_markdown(report)
    stored = {**report, "markdown": markdown}
    json_path = reports_dir / f"{stored['id']}.json"
    _atomic_write(
        json_path, json.dumps(stored, indent=2, ensure_ascii=False) + "\n"
    )
    _atomic_write(reports_dir / f"{stored['id']}.md", markdown)
    return json_path


def list_reports(data_dir: Path, coin: str | None = None) -> list[dict]:
    """All stored reports, newest (`generated_at`) first; [] when none.

    Optionally filtered to a single `coin`; unreadable files are skipped.
    """
    reports_dir = Path(data_dir) / "reports"
    if not reports_dir.is_dir():
        return []
    reports: list[dict] = []
    for path in sorted(reports_dir.glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(report, dict):
            continue
        if coin is not None and report.get("coin") != coin:
            continue
        reports.append(report)
    reports.sort(key=lambda r: str(r.get("generated_at") or ""), reverse=True)
    return reports


def load_report(data_dir: Path, report_id: str) -> dict:
    """Load one report by id; raises FileNotFoundError when absent."""
    path = Path(data_dir) / "reports" / f"{report_id}.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError(f"report {report_id!r} is not a JSON object")
    return report


# --------------------------------------------------------------------------
# Seed samples
# --------------------------------------------------------------------------

def seed_samples(data_dir: Path) -> None:
    """Write the two bundled sample reports; no-op when any report exists.

    Each report's `source_markdown` is the corresponding file from
    ``samples/`` read verbatim, so rendering returns the document unchanged.
    """
    reports_dir = Path(data_dir) / "reports"
    if reports_dir.is_dir() and any(reports_dir.glob("*.json")):
        return
    for report_id, filename, generated_at in SAMPLE_SPECS:
        source = (SAMPLES_DIR / filename).read_text(encoding="utf-8")
        report = new_report(
            "BTC/USDT",
            {"sources": []},
            {},
            {"key_levels": {}, "positions": []},
        )
        report["id"] = report_id
        report["generated_at"] = generated_at
        report["sample"] = True
        report["source_markdown"] = source
        report["markdown"] = render_markdown(report)
        save_report(data_dir, report)
