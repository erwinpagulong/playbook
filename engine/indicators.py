"""Deterministic technical indicators (pure Python, no TA-Lib).

All indicators are seeded from the first available data points and smoothed
with the classic formulas:

- RSI: Wilder smoothing (default period 14)
- MACD: EMA(12) - EMA(26), signal = EMA(9) of the MACD line
- Bollinger: 20-period SMA with 2 population standard deviations
- ATR: Wilder smoothing of true range (default period 14)
- Moving averages: EMA(12), EMA(26), SMA(20), SMA(50), SMA(200)

Public helpers round every returned float to 2 decimals.
"""

from __future__ import annotations

import statistics
from typing import Sequence

from .models import Candle

RSI_PERIOD = 14
ATR_PERIOD = 14


def _r(value: float) -> float:
    return round(float(value), 2)


def _sma(values: Sequence[float], period: int) -> float:
    """Simple moving average over the last `period` values."""
    if not values:
        return 0.0
    window = list(values[-period:])
    return sum(window) / len(window)


def _ema(values: Sequence[float], period: int) -> float:
    """Exponential moving average seeded with the SMA of the first `period` values."""
    if not values:
        return 0.0
    if len(values) < period:
        period = len(values)
    seed = sum(values[:period]) / period
    if len(values) == period:
        return seed
    multiplier = 2.0 / (period + 1)
    ema = seed
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
    return ema


def rsi(closes: list[float], period: int = RSI_PERIOD) -> float:
    """Wilder's Relative Strength Index."""
    if len(closes) < 2:
        return 50.0
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]

    if len(gains) < period:
        period = len(gains)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0  # no movement: neutral
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    rs = avg_gain / avg_loss
    return _r(100.0 - 100.0 / (1.0 + rs))


def macd(closes: list[float]) -> dict:
    """EMA-based MACD (12/26/9)."""
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    # MACD line per index: build the series so the signal is an EMA of it.
    line_series: list[float] = []
    if len(closes) >= 2:
        fast = _ema_series(closes, 12)
        slow = _ema_series(closes, 26)
        line_series = [f - s for f, s in zip(fast, slow)]
    line = ema12 - ema26 if closes else 0.0
    signal = _ema(line_series, 9) if line_series else 0.0
    hist = line - signal
    return {"line": _r(line), "signal": _r(signal), "hist": _r(hist)}


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    """Full EMA series, seeded with the SMA of the first `period` values."""
    if not values:
        return []
    if len(values) <= period:
        # Not enough data to start the recursion: flat at the seed.
        return [sum(values) / len(values)] * len(values)
    seed = sum(values[:period]) / period
    series = [seed] * period
    multiplier = 2.0 / (period + 1)
    ema = seed
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
        series.append(ema)
    return series


def bollinger(closes: list[float]) -> dict:
    """20-period Bollinger bands with 2 population standard deviations."""
    window = list(closes[-20:])
    if not window:
        return {"lower": 0.0, "mid": 0.0, "upper": 0.0}
    mid = sum(window) / len(window)
    stdev = statistics.pstdev(window) if len(window) > 1 else 0.0
    return {"lower": _r(mid - 2 * stdev), "mid": _r(mid), "upper": _r(mid + 2 * stdev)}


def atr(candles: list[Candle], period: int = ATR_PERIOD) -> float:
    """Wilder's Average True Range."""
    if len(candles) < 2:
        return 0.0
    true_ranges = []
    for prev, cur in zip(candles, candles[1:]):
        true_ranges.append(
            max(
                cur.high - cur.low,
                abs(cur.high - prev.close),
                abs(cur.low - prev.close),
            )
        )
    if len(true_ranges) < period:
        period = len(true_ranges)
    value = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        value = (value * (period - 1) + tr) / period
    return _r(max(value, 0.0))


def moving_averages(closes: list[float]) -> dict:
    """EMA12/EMA26 and SMA20/50/200."""
    return {
        "ema12": _r(_ema(closes, 12)),
        "ema26": _r(_ema(closes, 26)),
        "sma20": _r(_sma(closes, 20)),
        "sma50": _r(_sma(closes, 50)),
        "sma200": _r(_sma(closes, 200)),
    }


def analyze_timeframe(candles: list[Candle]) -> dict:
    """Combine all indicators for a list of candles into one report dict."""
    closes = [c.close for c in candles]
    ma = moving_averages(closes)
    price = _r(closes[-1]) if closes else 0.0

    if price > ma["sma20"] > ma["sma50"]:
        trend = "bullish"
    elif price < ma["sma20"] < ma["sma50"]:
        trend = "bearish"
    else:
        trend = "flat"

    return {
        "rsi": rsi(closes),
        "macd": macd(closes),
        "bollinger": bollinger(closes),
        "atr": atr(candles),
        "moving_averages": ma,
        "trend": trend,
        "price": price,
    }
