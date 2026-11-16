from dataclasses import dataclass


@dataclass
class Candle:
    """A single OHLCV candle."""

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
