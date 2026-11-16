"""Candle and quote fetching with layered fallback.

Primary source is Binance's public klines REST endpoint (no API key). On any
failure the fetcher falls back to yfinance, then to a local JSON cache under
`cache_dir`, and only then raises `DataUnavailable`. Quotes are best-effort:
each public source (Binance, CoinGecko, Coinbase) is tried independently and
failures are skipped, so a partial or empty snapshot is preferred over an
error. No credentials are used or logged anywhere in this module.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

from engine.models import Candle

TIMEFRAMES = ("15m", "4h", "1D")

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

# Public timeframe -> exchange interval for each source. yfinance has no "4h"
# interval, so 4h candles are resampled from hourly downloads.
_BINANCE_INTERVALS = {"15m": "15m", "4h": "4h", "1D": "1d"}
_YF_INTERVALS = {"15m": "15m", "4h": "1h", "1D": "1d"}
_YF_PERIODS = {"15m": "5d", "4h": "3mo", "1D": "1y"}

_COINGECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum"}


class DataUnavailable(Exception):
    """Every candle source and the local cache failed."""


# --------------------------------------------------------------------------
# Symbol / interval normalization
# --------------------------------------------------------------------------

def _binance_symbol(symbol: str) -> str:
    """`BTC/USDT` -> `BTCUSDT` (also tolerates `BTC-USDT` and `BTCUSDT`)."""
    return symbol.replace("/", "").replace("-", "").upper()


def _yf_ticker(symbol: str) -> str:
    """`BTC/USDT` -> `BTC-USD`; other quotes map straight through."""
    base, _, quote = symbol.replace("-", "/").partition("/")
    quote = quote or "USDT"
    if quote.upper() in ("USDT", "USDC", "USD"):
        quote = "USD"
    return f"{base.upper()}-{quote.upper()}"


def _interval(mapping: dict[str, str], timeframe: str) -> str:
    try:
        return mapping[timeframe]
    except KeyError as exc:
        raise RuntimeError(f"unsupported timeframe: {timeframe}") from exc


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

def _get_json(url: str, params: dict | None = None) -> object:
    """GET `url` and parse JSON; raise RuntimeError on any transport failure."""
    try:
        response = requests.get(url, params=params, timeout=10)
    except requests.RequestException as exc:
        raise RuntimeError(f"request failed: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code} from {url}")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"invalid JSON from {url}") from exc


# --------------------------------------------------------------------------
# Candles: Binance -> yfinance -> cache
# --------------------------------------------------------------------------

def _binance_get(symbol: str, timeframe: str, limit: int) -> list:
    """Raw klines rows from Binance; RuntimeError on any failure."""
    payload = _get_json(
        BINANCE_KLINES_URL,
        {
            "symbol": _binance_symbol(symbol),
            "interval": _interval(_BINANCE_INTERVALS, timeframe),
            "limit": limit,
        },
    )
    if not isinstance(payload, list):
        raise RuntimeError("unexpected klines payload")
    return payload


def _parse_klines(rows: list) -> list[Candle]:
    """Kline rows -> candles (timestamp, open, high, low, close, volume)."""
    return [
        Candle(
            int(row[0]),
            float(row[1]),
            float(row[2]),
            float(row[3]),
            float(row[4]),
            float(row[5]),
        )
        for row in rows
    ]


def _yfinance_candles(symbol: str, timeframe: str, limit: int) -> list[Candle]:
    """Candles via `yfinance.download` with `BTC-USD`-style tickers.

    yfinance has no 4h interval, so the 4h timeframe is resampled from the
    hourly series; other timeframes download directly.
    """
    import pandas as pd
    import yfinance as yf

    ticker = _yf_ticker(symbol)
    frame = yf.download(
        ticker,
        period=_YF_PERIODS[timeframe],
        interval=_interval(_YF_INTERVALS, timeframe),
        progress=False,
        auto_adjust=True,
    )
    if frame is None or frame.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    if timeframe == "4h":
        frame = (
            frame.resample("4h")
            .agg(
                {
                    "Open": "first",
                    "High": "max",
                    "Low": "min",
                    "Close": "last",
                    "Volume": "sum",
                }
            )
            .dropna(subset=["Close"])
        )
    return [
        Candle(
            int(ts.timestamp() * 1000),
            float(row["Open"]),
            float(row["High"]),
            float(row["Low"]),
            float(row["Close"]),
            float(row["Volume"]),
        )
        for ts, row in frame.iterrows()
    ][: -limit or None]


def _cache_path(symbol: str, timeframe: str, cache_dir: Path | None) -> Path | None:
    if cache_dir is None:
        return None
    name = f"{symbol.replace('/', '_').replace('-', '_')}_{timeframe}.json"
    return Path(cache_dir) / name


def _save_cache(
    candles: list[Candle], symbol: str, timeframe: str, cache_dir: Path | None
) -> None:
    """Persist candles as JSON; cache writes are best-effort."""
    path = _cache_path(symbol, timeframe, cache_dir)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
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
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def _load_cache(
    symbol: str, timeframe: str, cache_dir: Path | None
) -> list[Candle] | None:
    """Read cached candles; None when missing or unreadable."""
    path = _cache_path(symbol, timeframe, cache_dir)
    if path is None:
        return None
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        candles = [
            Candle(
                int(record["timestamp"]),
                float(record["open"]),
                float(record["high"]),
                float(record["low"]),
                float(record["close"]),
                float(record["volume"]),
            )
            for record in records
        ]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return candles or None


def fetch_candles(
    symbol: str,
    timeframe: str,
    limit: int = 200,
    cache_dir: Path | None = None,
) -> list[Candle]:
    """Candles for `symbol`/`timeframe`: Binance, then yfinance, then cache.

    A successful network fetch is written to `cache_dir` for the next outage.
    Raises `DataUnavailable` only when every source and the cache fail.
    """
    errors: list[str] = []

    candles: list[Candle] | None = None
    try:
        candles = _parse_klines(_binance_get(symbol, timeframe, limit))
        if not candles:
            raise RuntimeError("binance returned no candles")
    except Exception as exc:  # noqa: BLE001 - fall through to the next source
        errors.append(f"binance: {exc}")
        candles = None

    if candles is None:
        try:
            candles = _yfinance_candles(symbol, timeframe, limit)
            if not candles:
                raise RuntimeError("yfinance returned no candles")
        except Exception as exc:  # noqa: BLE001 - fall through to the cache
            errors.append(f"yfinance: {exc}")
            candles = None

    if candles is None:
        candles = _load_cache(symbol, timeframe, cache_dir)
        if candles is None:
            detail = "; ".join(errors) or "no sources attempted"
            raise DataUnavailable(f"no candle data for {symbol} {timeframe}: {detail}")
        return candles  # cache hit: keep the stored copy untouched

    _save_cache(candles, symbol, timeframe, cache_dir)
    return candles


# --------------------------------------------------------------------------
# Quotes: best-effort multi-source snapshot
# --------------------------------------------------------------------------

def _binance_quote(symbol: str) -> tuple[float, float]:
    payload = _get_json(
        "https://api.binance.com/api/v3/ticker/24hr",
        {"symbol": _binance_symbol(symbol)},
    )
    return float(payload["lastPrice"]), float(payload["priceChangePercent"])


def _coingecko_quote(symbol: str) -> tuple[float, float]:
    base = symbol.replace("-", "/").split("/")[0].upper()
    coin_id = _COINGECKO_IDS.get(base, base.lower())
    payload = _get_json(
        "https://api.coingecko.com/api/v3/simple/price",
        {"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"},
    )
    entry = payload[coin_id]
    return float(entry["usd"]), float(entry.get("usd_24h_change") or 0.0)


def _coinbase_quote(symbol: str) -> tuple[float, float]:
    base = symbol.replace("-", "/").split("/")[0].upper()
    payload = _get_json(
        f"https://api.exchange.coinbase.com/products/{base}-USD/stats"
    )
    last = float(payload["last"])
    open_ = float(payload["open"])
    change = (last - open_) / open_ * 100 if open_ else 0.0
    return last, change


def _quote_sources(symbol: str) -> list[tuple[str, float, float]]:
    """Successful `(source, price, change_pct)` entries; failures are skipped.

    Kept as a separate injectable function so tests can patch it wholesale.
    """
    results: list[tuple[str, float, float]] = []
    for source, fetcher in (
        ("Binance", _binance_quote),
        ("CoinGecko", _coingecko_quote),
        ("Coinbase", _coinbase_quote),
    ):
        try:
            price, change_pct = fetcher(symbol)
            results.append((source, float(price), float(change_pct)))
        except Exception:  # noqa: BLE001 - best-effort: skip this source
            continue
    return results


def fetch_quotes(symbol: str) -> list[dict]:
    """Best-effort `{"source", "price", "change_pct"}` snapshot; may be empty."""
    try:
        entries = _quote_sources(symbol)
    except Exception:  # noqa: BLE001 - quotes never break the caller
        return []
    return [
        {"source": source, "price": price, "change_pct": change_pct}
        for source, price, change_pct in entries
    ]
