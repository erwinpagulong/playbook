from engine.indicators import analyze_timeframe
from engine.levels import build_levels, rr
from engine.models import Candle

PRICE = 64053


def _candles(closes: list[float]) -> list[Candle]:
    return [Candle(i, c, c + 50.0, c - 50.0, c, 10.0) for i, c in enumerate(closes)]


def _rally_fade(start: float, mid: float, peak: float, end: float) -> list[float]:
    """Gradual rise, sharp rally, fade into `end` at bar 209.

    The rally/fade window straddles the end price so the derived levels land
    on both sides of it: support from the long-window averages below, and
    resistance from the recent peak above.
    """
    closes = []
    for i in range(210):
        if i <= 174:
            closes.append(start + (mid - start) * i / 174)
        elif i <= 189:
            closes.append(mid + (peak - mid) * (i - 174) / 15)
        else:
            closes.append(peak + (end - peak) * (i - 189) / 20)
    return closes


def sample_analysis() -> dict:
    """Synthetic 15m / 4h / 1D payloads built with `analyze_timeframe`.

    Each timeframe uses its own rally/fade series so its derived levels
    straddle its own price (64,053), with values distinct across timeframes.
    """
    return {
        "15m": analyze_timeframe(_candles(_rally_fade(63300, 63700, 64600, PRICE))),
        "4h": analyze_timeframe(_candles(_rally_fade(58000, 62000, 65000, PRICE))),
        "1D": analyze_timeframe(_candles(_rally_fade(60000, 63000, 65500, PRICE))),
    }


def _payload_candidates(payload: dict) -> set[float]:
    """Re-derive a timeframe's whole-dollar level candidates from its payload."""
    bands = payload["bollinger"]
    averages = payload["moving_averages"]
    raw = [
        bands["lower"], bands["mid"], bands["upper"],
        averages["ema12"], averages["ema26"],
        averages["sma20"], averages["sma50"], averages["sma200"],
        payload["price"],
    ]
    return {float(round(value)) for value in raw}


def test_rr_formula():
    assert rr(63950, 64945, 63700) == round(995 / 250, 2)


def test_positions_include_daily_long_tranche_and_short():
    analysis = sample_analysis()  # {"15m": ..., "4h": ..., "1D": ...} via analyze_timeframe
    levels = build_levels(analysis, price=64053)
    daily = [p for p in levels["positions"] if p["timeframe"] == "1D"]
    assert {p["direction"] for p in daily} == {"LONG", "SHORT"}
    assert len([p for p in daily if p["direction"] == "LONG"]) == 2


def test_every_position_has_required_fields():
    levels = build_levels(sample_analysis(), 64053)
    for p in levels["positions"]:
        assert set(("timeframe", "direction", "label", "entry", "tp1", "tp2", "stop", "rr", "zone")) <= p.keys()


def test_key_levels_are_sorted_deduped_and_whole_dollars():
    analysis = sample_analysis()
    levels = build_levels(analysis, 64053)
    support = levels["key_levels"]["support"]
    resistance = levels["key_levels"]["resistance"]
    # Pooled union of per-timeframe lists, each capped at the nearest 5.
    assert 0 < len(support) <= 5 * len(analysis)
    assert 0 < len(resistance) <= 5 * len(analysis)
    assert support == sorted(support, reverse=True)  # nearest to price first
    assert resistance == sorted(resistance)  # nearest to price first
    assert all(v < 64053 for v in support)
    assert all(v > 64053 for v in resistance)
    assert len(set(support)) == len(support)  # deduplicated
    assert len(set(resistance)) == len(resistance)
    assert all(v == int(v) for v in support + resistance)  # whole dollars


def test_every_position_price_traces_to_payload():
    levels = build_levels(sample_analysis(), 64053)
    allowed = set(levels["key_levels"]["support"]) | set(levels["key_levels"]["resistance"])
    assert allowed  # the payload actually produced levels
    for p in levels["positions"]:
        for field in ("entry", "tp1", "tp2", "stop"):
            assert p[field] in allowed, (p, field)


def test_positions_never_cross_timeframes():
    # 15m trades near 64k, 1D near 100k: the payloads' level values are disjoint.
    analysis = {
        "15m": analyze_timeframe(_candles(_rally_fade(63300, 63700, 64600, PRICE))),
        "1D": analyze_timeframe(_candles(_rally_fade(94000, 98500, 101500, 100000))),
    }
    candidates = {tf: _payload_candidates(payload) for tf, payload in analysis.items()}
    assert candidates["15m"] & candidates["1D"] == set()  # fixture sanity: disjoint

    levels = build_levels(analysis, price=PRICE)
    for timeframe in ("15m", "1D"):
        rows = [p for p in levels["positions"] if p["timeframe"] == timeframe]
        assert rows, timeframe
        other = candidates["1D" if timeframe == "15m" else "15m"]
        for p in rows:
            for field in ("entry", "tp1", "tp2", "stop"):
                assert p[field] in candidates[timeframe], (p, field)  # own payload only
                assert p[field] not in other, (p, field)  # never another timeframe's level


def test_empty_analysis_returns_empty_map():
    assert build_levels({}, 64053) == {
        "key_levels": {"support": [], "resistance": []},
        "positions": [],
    }
