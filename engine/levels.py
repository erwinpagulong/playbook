"""Entry/exit level assembly.

Turns the per-timeframe indicator payload into the playbook's entry/exit map:
key support/resistance levels plus one position row per playbook trade
(intraday bounce/fade, short-term oversold/sell-rally, long-term confirmed
long, value tranche, trend short).

Levels are derived **per timeframe**: each timeframe's support/resistance
comes only from that timeframe's own Bollinger bands, EMA/SMA values and its
own price, and its positions resolve against those levels — a 15m position
never references a 4h or 1D level. `key_levels` is the pooled (deduplicated)
union of the per-timeframe lists for display. Every emitted price is one of
those payload-derived levels rounded to whole dollars: no invented numbers.
"""

from __future__ import annotations

LEVELS_PER_SIDE = 5

# (timeframe, direction, label, entry, tp1, tp2, stop). Each level reference
# is ("S", index) into that timeframe's support list or ("R", index) into its
# resistance list; indices are clamped so a short list degrades gracefully
# instead of raising. Support is sorted nearest-first (descending),
# resistance nearest-first (ascending), so index 0 is nearest to price.
_POSITION_SPECS: tuple[tuple[str, str, str, tuple[str, int], tuple[str, int], tuple[str, int], tuple[str, int]], ...] = (
    ("15m", "LONG", "bounce", ("S", 0), ("R", 0), ("R", 1), ("S", 1)),
    ("15m", "SHORT", "fade", ("R", 0), ("S", 0), ("S", 1), ("R", 1)),
    ("4h", "LONG", "oversold", ("S", 1), ("R", 1), ("R", 2), ("S", 2)),
    ("4h", "SHORT", "sell rally", ("R", 1), ("S", 1), ("S", 2), ("R", 2)),
    ("1D", "LONG", "confirmed", ("R", 1), ("R", 2), ("R", 3), ("R", 0)),
    ("1D", "LONG", "value tranche", ("S", 0), ("R", 0), ("R", 1), ("S", 1)),
    ("1D", "SHORT", "trend", ("R", 2), ("S", 0), ("S", 1), ("R", 3)),
)


def rr(entry: float, target: float, stop: float) -> float:
    """Reward:risk — distance to target over distance to stop, 2 decimals."""
    risk = abs(entry - stop)
    if risk == 0:
        return 0.0
    return round(abs(target - entry) / risk, 2)


def _payload_levels(payload: dict) -> list[float]:
    """Whole-dollar prices from one timeframe's bands, averages and price."""
    bands = payload.get("bollinger") or {}
    averages = payload.get("moving_averages") or {}
    raw = (
        bands.get("lower"),
        bands.get("mid"),
        bands.get("upper"),
        averages.get("ema12"),
        averages.get("ema26"),
        averages.get("sma20"),
        averages.get("sma50"),
        averages.get("sma200"),
        payload.get("price"),
    )
    values = {
        float(round(value))
        for value in raw
        if isinstance(value, (int, float)) and value > 0
    }
    return sorted(values)


def _reference_price(payload: dict, price: float) -> float:
    """This timeframe's own price, falling back to the caller's reference."""
    own = payload.get("price")
    if isinstance(own, (int, float)) and own > 0:
        return float(own)
    return price


def _key_levels(payload: dict, ref_price: float) -> tuple[list[float], list[float]]:
    """One timeframe's support (descending) and resistance (ascending),
    deduplicated to whole dollars and limited to the nearest few."""
    values = _payload_levels(payload)
    support = [v for v in values if v < ref_price]
    support.reverse()  # nearest to price first
    resistance = [v for v in values if v > ref_price]  # already ascending
    return support[:LEVELS_PER_SIDE], resistance[:LEVELS_PER_SIDE]


def _resolve(
    ref: tuple[str, int], levels: tuple[list[float], list[float]]
) -> float | None:
    """Map a level reference to its value in this timeframe's lists,
    clamped to the available levels."""
    side = levels[0] if ref[0] == "S" else levels[1]
    if not side:
        return None
    return side[min(ref[1], len(side) - 1)]


def _zone(
    ref: tuple[str, int], entry: float, levels: tuple[list[float], list[float]]
) -> str:
    """Entry band from the entry level outward to the next level on the same
    side (farther from price), rendered as a whole-dollar range."""
    side = levels[0] if ref[0] == "S" else levels[1]
    neighbor = side[min(ref[1] + 1, len(side) - 1)]
    lo, hi = sorted((entry, neighbor))
    return f"{int(lo)}-{int(hi)}"


def _positions(
    analysis: dict[str, dict],
    levels_by_timeframe: dict[str, tuple[list[float], list[float]]],
) -> list[dict]:
    positions: list[dict] = []
    for timeframe, direction, label, entry_ref, tp1_ref, tp2_ref, stop_ref in _POSITION_SPECS:
        if timeframe not in levels_by_timeframe:
            continue
        levels = levels_by_timeframe[timeframe]
        resolved = [
            _resolve(ref, levels)
            for ref in (entry_ref, tp1_ref, tp2_ref, stop_ref)
        ]
        if any(value is None for value in resolved):
            continue  # this timeframe lacks one side of the market entirely
        entry, tp1, tp2, stop = resolved
        positions.append(
            {
                "timeframe": timeframe,
                "direction": direction,
                "label": label,
                "entry": entry,
                "tp1": tp1,
                "tp2": tp2,
                "stop": stop,
                "rr": rr(entry, tp1, stop),
                "zone": _zone(entry_ref, entry, levels),
            }
        )
    return positions


def build_levels(analysis: dict[str, dict], price: float) -> dict:
    """Assemble key levels and the entry/exit position map.

    `analysis` maps timeframe -> `analyze_timeframe` payload; `price` is the
    reference price used when a payload carries none. Each timeframe's levels
    are derived from its own payload against its own price; `key_levels` is
    the deduplicated union of those per-timeframe lists.
    """
    levels_by_timeframe = {
        timeframe: _key_levels(payload, _reference_price(payload, price))
        for timeframe, payload in analysis.items()
        if isinstance(payload, dict)
    }
    support = sorted(
        {value for side, _ in levels_by_timeframe.values() for value in side},
        reverse=True,
    )
    resistance = sorted(
        {value for _, side in levels_by_timeframe.values() for value in side}
    )
    return {
        "key_levels": {"support": support, "resistance": resistance},
        "positions": _positions(analysis, levels_by_timeframe),
    }
