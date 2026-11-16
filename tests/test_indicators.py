from engine.indicators import atr, bollinger, macd, moving_averages, rsi, analyze_timeframe
from engine.models import Candle


def test_rsi_monotonic_rise_is_100():
    assert rsi([float(i) for i in range(1, 40)]) == 100.0


def test_rsi_monotonic_fall_is_0():
    assert rsi([float(i) for i in range(40, 0, -1)]) == 0.0


def test_bollinger_bands_are_ordered():
    b = bollinger([100, 101, 99, 102, 98, 103, 97, 104, 96, 105] * 3)
    assert b["lower"] < b["mid"] < b["upper"]


def test_atr_is_nonnegative():
    candles = [Candle(i, 100 + i, 102 + i, 99 + i, 101 + i, 1) for i in range(30)]
    assert atr(candles) >= 0


def test_analyze_timeframe_keys():
    candles = [Candle(i, 100, 102, 99, 101, 1) for i in range(210)]
    a = analyze_timeframe(candles)
    for key in ("rsi", "macd", "bollinger", "atr", "moving_averages", "trend", "price"):
        assert key in a


def test_macd_keys():
    closes = [100 + (i % 7) for i in range(60)]
    m = macd(closes)
    for key in ("line", "signal", "hist"):
        assert key in m


def test_moving_averages_keys():
    ma = moving_averages([100.0] * 210)
    for key in ("ema12", "ema26", "sma20", "sma50", "sma200"):
        assert key in ma


def test_analyze_timeframe_flat_trend_on_constant_price():
    candles = [Candle(i, 100, 102, 99, 101, 1) for i in range(210)]
    a = analyze_timeframe(candles)
    assert a["trend"] == "flat"
    assert a["price"] == 101.0


def test_analyze_timeframe_bullish_trend():
    candles = [
        Candle(i, 100 + i * 0.5, 101 + i * 0.5, 99.5 + i * 0.5, 100.5 + i * 0.5, 1)
        for i in range(210)
    ]
    a = analyze_timeframe(candles)
    assert a["trend"] == "bullish"


def test_values_are_rounded_to_two_decimals():
    candles = [Candle(i, 100 + i, 102 + i, 99 + i, 101 + i, 1) for i in range(210)]
    a = analyze_timeframe(candles)
    assert a["atr"] == round(a["atr"], 2)
    assert a["macd"]["line"] == round(a["macd"]["line"], 2)
    assert a["bollinger"]["upper"] == round(a["bollinger"]["upper"], 2)
    assert a["moving_averages"]["sma200"] == round(a["moving_averages"]["sma200"], 2)
