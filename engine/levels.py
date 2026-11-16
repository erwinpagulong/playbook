"""Entry/exit level assembly.

Turns the per-timeframe indicator payload into the playbook's entry/exit map:
key support/resistance levels plus one position row per playbook trade
(intraday bounce/fade, short-term oversold/sell-rally, long-term confirmed
long, value tranche, trend short).

Every emitted price is selected from the computed payload — Bollinger bands,
EMA/SMA values and timeframe prices — rounded to whole dollars. No invented
numbers: each entry/TP/stop is one of the key levels below.
"""

from __future__ import annotations

LEVELS_PER_SIDE = 5

# (timeframe, direction, label, entry, tp1, tp2, stop). Each level reference
# is ("S", index) into the support list or ("R", index) into the resistance
# list; indices are clamped so a short list degrades gracefully instead of
# raising. Support is sorted nearest-first (descending), resistance nearest-
# first (ascending), so index 0 is the level closest to price.
_POSITION_SPECS: tuple[tuple[str, str, str, tuple[str, int], tuple[str, int], tuple[str, int], tuple[str, int]], ...] = (
    ("15m", "LONG", "bounce", ("S", 0), ("R", 0), ("R", 1), ("S", 1)),
    ("15m", "SHORT", "fade", ("R", 0), ("S", 0), ("S", 1), ("R", 1)),
    ("4h", "LONG", "oversold", ("S", 1), ("R", 1), ("R", 2), ("S", 2)),
    ("4h", "SHORT", "sell rally", ("R", 1), ("S", 1), ("S", 2), ("R", 2)),
    ("1D", "LONG", "confirmed", ("R", 1), ("R", 2), ("R", 3), ("R", 0)),
    ("1D", "LONG", "value tranche", ("S", 2), ("R", 0), ("R", 1), ("S", 3)),
    ("1D", "SHORT", "trend", ("R", 2), ("S", 0), ("S", 1), ("R", 3)),
)


def rr(entry: float, target: float, stop: float) -> float:
    """Reward:risk — distance to target over distance to stop, 2 decimals."""
    risk = abs(entry - stop)
    if risk == 0:
        return 0.0
    return round(abs(target - entry) / risk, 2)


def _payload_levels(analysis: dict[str, dict]) -> list[float]:
    """Whole-dollar prices from every timeframe's bands, averages and price."""
    values: set[float] = set()
    for payload in analysis.values():
        if not isinstance(payload, dict):
            continue
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
        for value in raw:
            if isinstance(value, (int, float)) and value > 0:
                values.add(float(round(value)))
    return sorted(values)


def _key_levels(analysis: dict[str, dict], price: float) -> tuple[list[float], list[float]]:
    """Support below price (descending) and resistance above (ascending),
    deduplicated to whole dollars and limited to the nearest few."""
    values = _payload_levels(analysis)
    support = [v for v in values if v < price]
    support.reverse()  # nearest to price first
    resistance = [v for v in values if v > price]  # already ascending
    return support[:LEVELS_PER_SIDE], resistance[:LEVELS_PER_SIDE]


def _resolve(ref: tuple[str, int], support: list[float], resistance: list[float]) -> float | None:
    """Map a level reference to its value, clamped to the available list."""
    levels = support if ref[0] == "S" else resistance
    if not levels:
        return None
    return levels[min(ref[1], len(levels) - 1)]


def _zone(ref: tuple[str, int], entry: float, support: list[float], resistance: list[float]) -> str:
    """Entry band from the entry level outward to the next level on the same
    side (farther from price), rendered as a whole-dollar range."""
    levels = support if ref[0] == "S" else resistance
    neighbor = levels[min(ref[1] + 1, len(levels) - 1)]
    lo, hi = sorted((entry, neighbor))
    return f"{int(lo)}-{int(hi)}"


def _positions(
    analysis: dict[str, dict], support: list[float], resistance: list[float]
) -> list[dict]:
    positions: list[dict] = []
    for timeframe, direction, label, entry_ref, tp1_ref, tp2_ref, stop_ref in _POSITION_SPECS:
        if timeframe not in analysis:
            continue
        resolved = [
            _resolve(ref, support, resistance)
            for ref in (entry_ref, tp1_ref, tp2_ref, stop_ref)
        ]
        if any(value is None for value in resolved):
            continue  # not enough levels on one side to place the trade
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
                "zone": _zone(entry_ref, entry, support, resistance),
            }
        )
    return positions


def build_levels(analysis: dict[str, dict], price: float) -> dict:
    """Assemble key levels and the entry/exit position map.

    `analysis` maps timeframe -> `analyze_timeframe` payload; `price` is the
    reference price that splits support from resistance.
    """
    support, resistance = _key_levels(analysis, price)
    return {
        "key_levels": {"support": support, "resistance": resistance},
        "positions": _positions(analysis, support, resistance),
    }
