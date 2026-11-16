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
