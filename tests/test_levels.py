import math

from engine.indicators import analyze_timeframe
from engine.levels import build_levels, rr
from engine.models import Candle

PRICE = 64053


def _candles(closes: list[float]) -> list[Candle]:
    return [Candle(i, c, c + 50.0, c - 50.0, c, 10.0) for i, c in enumerate(closes)]


def sample_analysis() -> dict:
    """Synthetic 15m / 4h / 1D payloads built with `analyze_timeframe`.

    Shapes are chosen so derived levels straddle the reference price: the
    daily declines into 64,053 (resistance stack above), the 4h dips to
    61,000 and recovers (support stack below), the 15m oscillates around it.
    """
    daily = [PRICE + (209 - i) * 60.0 for i in range(210)]

    def close_4h(i: int) -> float:
        if i <= 104:
            return 70000.0 - i * (9000.0 / 104.0)
        return 61000.0 + (i - 104) * (3053.0 / 105.0)

    intraday = [
        PRICE
        + 900.0 * math.sin(2 * math.pi * (209 - i) / 29)
        + 300.0 * math.sin(2 * math.pi * (209 - i) / 11)
        for i in range(210)
    ]
    return {
        "15m": analyze_timeframe(_candles(intraday)),
        "4h": analyze_timeframe(_candles([close_4h(i) for i in range(210)])),
        "1D": analyze_timeframe(_candles(daily)),
    }


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


def test_key_levels_are_sorted_deduped_and_nearest_five():
    levels = build_levels(sample_analysis(), 64053)
    support = levels["key_levels"]["support"]
    resistance = levels["key_levels"]["resistance"]
    assert 0 < len(support) <= 5
    assert 0 < len(resistance) <= 5
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


def test_empty_analysis_returns_empty_map():
    assert build_levels({}, 64053) == {
        "key_levels": {"support": [], "resistance": []},
        "positions": [],
    }
