import json
import os

import pytest

from engine import data
from engine.models import Candle


def test_binance_parses_klines(monkeypatch, tmp_path):
    rows = [[1, "100", "102", "99", "101", "10", 1, 1, "0", 0, 0, "0"]]
    monkeypatch.setattr(data, "_binance_get", lambda *a, **k: rows)
    candles = data.fetch_candles("BTC/USDT", "15m", cache_dir=tmp_path)
    assert candles[0] == Candle(1, 100.0, 102.0, 99.0, 101.0, 10.0)


def test_binance_failure_falls_back_to_yfinance(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "_binance_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(data, "_yfinance_candles", lambda *a, **k: [Candle(1, 1, 2, 0.5, 1.5, 1)])
    assert data.fetch_candles("BTC/USDT", "15m", cache_dir=tmp_path)[0].close == 1.5


def test_cached_candles_used_when_both_sources_fail(monkeypatch, tmp_path):
    cache = tmp_path / "BTC_USDT_15m.json"
    cache.write_text('[{"timestamp":1,"open":1,"high":2,"low":0.5,"close":1.5,"volume":1}]')
    monkeypatch.setattr(data, "_binance_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(data, "_yfinance_candles", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    assert data.fetch_candles("BTC/USDT", "15m", cache_dir=tmp_path)[0].close == 1.5


def test_successful_binance_fetch_persists_cache_contents(monkeypatch, tmp_path):
    """A successful fetch writes `cache_dir/<SYMBOL>_<TF>.json` verbatim."""
    rows = [
        [1, "100", "102", "99", "101", "10", 1, 1, "0", 0, 0, "0"],
        [2, "101", "103", "100", "102", "11", 2, 2, "0", 0, 0, "0"],
    ]
    monkeypatch.setattr(data, "_binance_get", lambda *a, **k: rows)
    candles = data.fetch_candles("BTC/USDT", "15m", cache_dir=tmp_path)

    cache = tmp_path / "BTC_USDT_15m.json"
    assert cache.exists()
    stored = json.loads(cache.read_text(encoding="utf-8"))
    assert stored == [
        {
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in candles
    ]


def test_cache_hit_does_not_rewrite_cache(monkeypatch, tmp_path):
    """A cache-hit fetch returns the stored candles and leaves the file alone."""
    rows = [[1, "100", "102", "99", "101", "10", 1, 1, "0", 0, 0, "0"]]
    monkeypatch.setattr(data, "_binance_get", lambda *a, **k: rows)
    data.fetch_candles("BTC/USDT", "15m", cache_dir=tmp_path)

    cache = tmp_path / "BTC_USDT_15m.json"
    before_bytes = cache.read_bytes()
    # Pin mtime in the past so any rewrite is detectable regardless of
    # filesystem timestamp granularity.
    pinned = 1_000_000_000
    os.utime(cache, (pinned, pinned))

    monkeypatch.setattr(data, "_binance_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(data, "_yfinance_candles", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    candles = data.fetch_candles("BTC/USDT", "15m", cache_dir=tmp_path)

    assert candles[0].close == 101.0  # served from the cache
    assert cache.read_bytes() == before_bytes  # content untouched
    assert cache.stat().st_mtime_ns == pinned * 1_000_000_000  # never rewritten


def test_fetch_quotes_best_effort(monkeypatch):
    monkeypatch.setattr(data, "_quote_sources", lambda s: [("Binance", 64000.0, -2.1)])
    assert data.fetch_quotes("BTC/USDT")[0]["source"] == "Binance"


def test_timeframes_constant():
    assert data.TIMEFRAMES == ("15m", "4h", "1D")


def test_all_sources_and_cache_fail_raise_data_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "_binance_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no binance")))
    monkeypatch.setattr(data, "_yfinance_candles", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no yfinance")))
    with pytest.raises(data.DataUnavailable):
        data.fetch_candles("BTC/USDT", "15m", cache_dir=tmp_path)


def test_yfinance_candles_keeps_most_recent_and_resamples_4h(monkeypatch):
    """The 4h fallback must return the newest buckets, oldest data dropped."""
    import pandas as pd
    import yfinance as yf

    index = pd.date_range("2026-01-01", periods=8, freq="1h")
    frame = pd.DataFrame(
        {
            "Open": [float(i) for i in range(8)],
            "High": [float(i) + 1 for i in range(8)],
            "Low": [float(i) for i in range(8)],
            "Close": [float(i) for i in range(8)],
            "Volume": [10.0] * 8,
        },
        index=index,
    )
    monkeypatch.setattr(yf, "download", lambda *a, **k: frame)
    # 8 hourly bars -> two 4h buckets (closes 3.0 and 7.0); limit=1 keeps the
    # most recent bucket only.
    candles = data._yfinance_candles("BTC/USDT", "4h", limit=1)
    assert [c.close for c in candles] == [7.0]
