"""Serialized report generation pipeline.

`generate_report` is the integration point of the engine: it fetches
candles for every playbook timeframe, computes indicators, derives the
entry/exit levels, snapshots quotes, assembles the LLM payload, and asks
the LLM for the narrative prediction — then grounds that prediction
against the computed price levels before storing it.

Every run is serialized by a module-level lock, so concurrent callers
(daemon scheduler, CLI regenerate, dashboard refresh) queue end to end
instead of racing; report ids (microsecond timestamps) stay distinct.

LLM failures — missing key, transport errors, or grounding violations in
the reply — never lose the report: the deterministic part is saved anyway
with ``prediction.available = False`` and a short reason, which is also
returned as ``error``. Reasons are exception messages that never contain
an API key value (see `engine.llm`), and no environment value is ever
logged here.

Candle fetch failures fall back to the local JSON cache via
`engine.data.fetch_candles`; when the fetch layer itself raised, the cache
is read directly before a timeframe is declared missing. Missing
timeframes are skipped and reported in ``error``. When *no* timeframe has
any data, the run returns ``{"report": None, "error": reason}`` — the
function never raises for expected operational failures.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from engine import data, llm
from engine.data import TIMEFRAMES
from engine.indicators import analyze_timeframe
from engine.llm import LLMUnavailable
from engine.levels import build_levels
from engine.report import new_report, render_markdown, save_report

log = logging.getLogger(__name__)

#: Serializes whole generations: concurrent callers wait their turn.
_generation_lock = threading.Lock()

#: Candles requested per timeframe (enough for the SMA200 window).
CANDLE_LIMIT = 200


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

def _candles_for(coin: str, timeframe: str, cache_dir: Path) -> tuple[list | None, str | None]:
    """Candles for one timeframe; ``(candles, None)`` or ``(None, reason)``.

    Fetch failures (and a fetch layer that raised despite a usable cache)
    fall back to a direct cache read before the timeframe is declared
    missing.
    """
    try:
        candles = data.fetch_candles(
            coin, timeframe, limit=CANDLE_LIMIT, cache_dir=cache_dir
        )
    except Exception as exc:  # noqa: BLE001 - fetch errors become report errors
        # `fetch_candles` already tried the cache internally, but a failing
        # caller-side fetch must still honor cached files on disk.
        candles = data._load_cache(coin, timeframe, cache_dir)
        if candles:
            return candles, None
        detail = str(exc).strip() or "all candle sources failed"
        return None, f"{coin} {timeframe}: {detail}"
    if not candles:
        return None, f"{coin} {timeframe}: no candle data"
    return candles, None


def _quotes_for(coin: str) -> list[dict]:
    """Best-effort quote snapshot; ``[]`` when the source fails."""
    try:
        quotes = data.fetch_quotes(coin)
    except Exception:  # noqa: BLE001 - quotes never break generation
        return []
    return quotes if isinstance(quotes, list) else []


# --------------------------------------------------------------------------
# LLM prediction
# --------------------------------------------------------------------------

def _predict(config: dict, payload: dict) -> tuple[dict | None, str | None]:
    """Grounded prediction for `payload`; ``(None, reason)`` on any failure.

    The reason is a short human-readable string. It never carries an API
    key value: `llm.call_llm` keeps key values out of its messages and no
    environment value is read or formatted here.
    """
    llm_config = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    try:
        reply = llm.call_llm(llm_config, llm.build_prompt(payload))
    except LLMUnavailable as exc:
        detail = str(exc).strip() or "LLM unavailable"
        return None, f"prediction unavailable: {detail}"
    except Exception as exc:  # noqa: BLE001 - any LLM error must not lose the report
        detail = str(exc).strip() or exc.__class__.__name__
        return None, f"prediction unavailable: {detail}"
    if not isinstance(reply, dict):
        return None, "prediction unavailable: LLM reply was not a JSON object"
    errors = llm.validate_prediction(reply, llm.allowed_levels(payload))
    if errors:
        joined = "; ".join(str(error) for error in errors[:3])
        return None, f"prediction failed validation: {joined}"
    return reply, None


def _flatten(prediction: dict) -> dict:
    """Regroup horizon-keyed scenarios into the flat list the markdown
    prediction table expects (each row carries its ``horizon``)."""
    scenarios = prediction.get("scenarios")
    if not isinstance(scenarios, dict):
        return prediction
    flat = [
        {"horizon": str(horizon), **item}
        for horizon, items in scenarios.items()
        if isinstance(items, list)
        for item in items
        if isinstance(item, dict)
    ]
    return {**prediction, "scenarios": flat}


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

def _generate(coin: str, config: dict, data_dir: Path) -> dict:
    cache_dir = data_dir / "candles"
    analysis: dict[str, dict] = {}
    problems: list[str] = []

    for timeframe in TIMEFRAMES:
        candles, reason = _candles_for(coin, timeframe, cache_dir)
        if candles is None:
            problems.append(reason or f"{coin} {timeframe}: no candle data")
            continue
        analysis[timeframe] = analyze_timeframe(candles)

    if not analysis:
        reason = f"no candle data for {coin} in any timeframe"
        log.warning("%s", reason)
        return {"report": None, "error": reason}

    quotes = _quotes_for(coin)
    reference = float(next(iter(analysis.values())).get("price") or 0.0)
    levels = build_levels(analysis, reference)
    payload = {
        "coin": coin,
        "indicators": analysis,
        "levels": levels,
        "quotes": quotes,
    }

    prediction, reason = _predict(config, payload)
    if reason:
        log.warning("prediction unavailable for %s: %s", coin, reason)
        problems.append(reason)

    report = new_report(coin, {"sources": quotes}, analysis, levels)
    if prediction is None:
        report["prediction"] = {"available": False, "reason": reason}
    else:
        report["prediction"] = {**_flatten(prediction), "available": True}
    report["markdown"] = render_markdown(report)
    save_report(data_dir, report)

    return {"report": report, "error": "; ".join(problems) or None}


def generate_report(coin: str, config: dict, data_dir: Path) -> dict:
    """Generate, save, and return one report for `coin`.

    Runs are serialized by a module-level lock: concurrent callers queue
    end to end, so report ids stay distinct. Returns
    ``{"report": <dict | None>, "error": <str | None>}`` where ``error`` is
    ``None`` on a clean run and a short reason otherwise (missing
    timeframes, LLM failure, or validation failure); when at least one
    timeframe produced data, the deterministic report is still saved with
    ``prediction.available`` reflecting the LLM outcome.

    Never raises for expected operational failures: when no timeframe has
    any candle data (both the fetch layer and the cache failed
    everywhere), returns ``{"report": None, "error": reason}``.
    """
    with _generation_lock:
        return _generate(coin, config, Path(data_dir))
