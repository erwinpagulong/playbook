"""Tests for the generation pipeline (Task 8).

All tests are offline: the network seams (`data.fetch_candles`,
`data.fetch_quotes`) and the LLM seam (`llm.call_llm`) are monkeypatched —
the autouse `offline_seams` fixture provides defaults that every test
overrides as needed.
"""

import concurrent.futures
import json
import logging
import time

import pytest

from engine import data, llm
from engine.config import load_config
from engine.data import DataUnavailable
from engine.generate import generate_report
from engine.llm import LLMUnavailable
from engine.models import Candle
from engine.report import list_reports

# Flat candles at price 100: every indicator resolves around 100, so the
# allowed price levels are the psychological 10-steps (0..200) around it.
FLAT_CANDLE = Candle(1, 100, 101, 99, 100, 1)


def valid_prediction():
    """An LLM reply that passes `llm.validate_prediction` for flat 100-price data.

    Scenario low/high values sit exactly on allowed levels (psychological
    steps of 10 around the 100 reference price), probabilities sum to 100
    per horizon, confidence is in 0..1, and no banned phrase appears.
    """
    return {
        "highest_conviction": {"text": "Range-bound near 100", "confidence": 0.6},
        "scenarios": {
            "24-48h": [
                {"label": "Hold 100", "low": 90, "high": 110, "probability": 60},
                {"label": "Slip to 80", "low": 80, "high": 90, "probability": 40},
            ],
            "1-2w": [
                {"label": "Grind to 120", "low": 110, "high": 120, "probability": 50},
                {"label": "Fade to 70", "low": 70, "high": 80, "probability": 50},
            ],
        },
        "per_timeframe": {"15m": "flat", "4h": "flat", "1D": "flat"},
        "favored_trade": "wait for a confirmed break",
        "confirmation": "close above 110",
        "invalidation": "close below 70",
        "bottom_line": "Neutral range — educational only, not financial advice.",
    }


@pytest.fixture(autouse=True)
def offline_seams(monkeypatch):
    """Offline defaults: no quotes, no LLM. Tests override both as needed."""
    monkeypatch.setattr(data, "fetch_quotes", lambda *a, **k: [])
    monkeypatch.setattr(
        llm,
        "call_llm",
        lambda *a, **k: (_ for _ in ()).throw(LLMUnavailable("offline test stub")),
    )


# --- brief: pipeline happy path --------------------------------------------

def test_pipeline_produces_prediction(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    monkeypatch.setattr(
        data,
        "fetch_quotes",
        lambda *a, **k: [{"source": "stub", "price": 100.0, "change_pct": 1.5}],
    )
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: valid_prediction())
    result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["error"] is None
    assert result["report"]["prediction"]["available"] is True
    # the quote snapshot and the flattened scenarios land in the report
    assert result["report"]["snapshot"]["sources"][0]["source"] == "stub"
    assert result["report"]["prediction"]["scenarios"][0]["horizon"] == "24-48h"
    assert list_reports(tmp_path)[0]["id"] == result["report"]["id"]


# --- brief: LLM failure -----------------------------------------------------

def test_llm_failure_still_saves_report(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("OPENAI_API_KEY", "sentinel-key-never-logged")
    monkeypatch.setattr(
        llm, "call_llm", lambda *a, **k: (_ for _ in ()).throw(LLMUnavailable())
    )
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    with caplog.at_level(logging.WARNING):
        result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["report"]["prediction"]["available"] is False
    assert result["report"]["prediction"]["reason"]
    assert result["error"]
    assert list_reports(tmp_path)[0]["id"] == result["report"]["id"]
    # the reason is logged and returned, but never an API key value
    assert "sentinel-key-never-logged" not in caplog.text
    assert "sentinel-key-never-logged" not in str(result["error"])


def test_invalid_llm_output_still_saves_report(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: {
        "highest_conviction": {"text": "up", "confidence": 0.5},
        "scenarios": {
            "24-48h": [{"label": "invented", "low": 99999, "high": 100000, "probability": 100}],
        },
    })
    result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["report"]["prediction"]["available"] is False
    assert "99999" in result["report"]["prediction"]["reason"]
    assert list_reports(tmp_path)[0]["id"] == result["report"]["id"]


# --- brief: fetch failure falls back to cache -------------------------------

def test_fetch_failure_uses_cache(monkeypatch, tmp_path):
    cache = tmp_path / "candles" / "BTC_USDT_15m.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps([{"timestamp": 1, "open": 100, "high": 101,
                                   "low": 99, "close": 100, "volume": 1}] * 210))
    monkeypatch.setattr(
        data, "fetch_candles", lambda *a, **k: (_ for _ in ()).throw(DataUnavailable())
    )
    result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["report"]["indicators"]["15m"]["price"] == 100
    # 4h and 1D have no cache: skipped and reported, but the report still saves
    assert "4h" not in result["report"]["indicators"]
    assert result["error"]


# --- brief: serialized generation -------------------------------------------

def test_generate_is_serialized(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: (time.sleep(0.05), valid_prediction())[1])
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _: generate_report("BTC/USDT", load_config(None), tmp_path), range(4)))
    ids = [r["report"]["id"] for r in results]
    assert len(ids) == len(set(ids)) == 4
    assert all(r["report"]["prediction"]["available"] for r in results)
