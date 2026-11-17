"""LLM narrative call and grounded-output validation.

The LLM writes **narrative only**. Every price it emits must be grounded in
the computed payload (indicators, the assembled entry/exit table, key levels,
quotes), which is serialized into the prompt along with an explicit
``allowed_levels`` list. Validation enforces that grounding:

- every scenario ``low``/``high`` must be within 0.5% of an allowed level
  (tolerance for rounding toward a known level) **and** must lie inside the
  span of the allowed levels — a bound beyond every known level (e.g. 65200
  when the payload tops out at 64945) is an invented price, however close;
- probabilities and confidence are the deliberate exception: subjective
  estimates, labelled as such in the prompt. Probabilities must sum to 100
  per horizon; confidence must be in 0..1;
- the output must not contain "75%" or "guaranteed".

``call_llm`` talks to any OpenAI-compatible ``{base_url}/chat/completions``
endpoint with ``response_format: {"type": "json_object"}``, raises
``LLMUnavailable`` when the configured key env var is missing/empty or the
HTTP call fails, and never logs or stores the key value. Provider-side
failures (HTTP errors, transport/timeouts, quota/rate-limit markers in the
body) raise ``LLMProviderError`` — a subclass of ``LLMUnavailable`` carrying
``status`` and ``marker`` — so callers can distinguish them from invalid
model output via ``is_provider_failure``. An explicit ``api_key`` argument
wins over the environment; the key value never appears in any message.
"""

from __future__ import annotations

import json
import math
import os
import re
import time

import requests

#: Every scenario low/high must be within this fraction (0.5%) of an allowed level.
PRICE_TOLERANCE = 0.005

#: Probabilities per horizon must sum to 100 within this slack (rounding drift).
PROBABILITY_SUM_TOLERANCE = 0.11

#: Phrases the prediction must never contain (the sample debunks "75% win rate").
BANNED_PHRASES = ("75%", "guaranteed")

#: Horizons the prompt asks the model to group scenarios by.
HORIZONS = ("24-48h", "1-2w")

#: Payload keys whose numeric values are price levels (the recursive walk
#: collects numbers under these keys, including list values like support).
PRICE_KEYS = frozenset(
    {
        "price", "entry", "tp1", "tp2", "stop", "support", "resistance",
        "lower", "mid", "upper", "ema12", "ema26", "sma20", "sma50",
        "sma200", "low", "high", "last", "close",
    }
)

#: Psychological round levels: offsets of ±10 steps around the reference price.
PSYCH_OFFSETS = range(-10, 11)

#: Bounded retries for transient transport/timeout/5xx failures only. A missing
#: key (checked before the loop) and an invalid JSON reply (parsed after it)
#: are never retried. The key value is never part of any message or log.
LLM_MAX_RETRIES = 2
LLM_RETRY_BACKOFF_S = 0.25

#: A price-like token in free text: 4+ integer digits, optionally comma-grouped
#: and/or decimal. Used to catch invented prices in the narrative prose, which
#: the scenario low/high check alone does not cover.
PRICE_TOKEN_RE = re.compile(
    r"(?<![0-9A-Za-z_.])(?:\d{1,3}(?:,\d{3})+|\d{4,})(?:\.\d+)?(?![0-9A-Za-z_.])"
)

#: A label just before a number that marks it as an indicator reading (RSI,
#: MACD, ATR) rather than a price.
_INDICATOR_LABEL_RE = re.compile(r"(?i)\b(?:rsi|macd|atr)\b[^0-9]{0,16}$")

#: A unit suffix attached to a number marks a size/flow quantity, not a price
#: (e.g. "1,410.67M" of volume, "3,456.78B" market cap). The word boundary
#: keeps ordinary words beginning with M/B/K from being mistaken for a suffix.
_UNIT_SUFFIX_RE = re.compile(r"(?i)^[MBK]\b")

#: Labels that mark a nearby number as volume/liquidity/funding/market-cap
#: rather than a price. Matched against the text just before the number.
_VOLUME_LABEL_RE = re.compile(
    r"(?i)\b(?:volume|liquidity|funding|market\s*cap(?:italization)?)\b"
)

#: A genuine price word between a volume label and the number means the
#: number is a real price — do not suppress it (e.g. "volume ...; price 6500").
_PRICE_WORD_RE = re.compile(
    r"(?i)\b(?:price|prices|support|resistance|entry|stop|target|low|high|level|levels|band|bands|close|zone)\b"
)


class LLMUnavailable(Exception):
    """No API key available, or the LLM HTTP call failed / reply was invalid."""


class LLMProviderError(LLMUnavailable):
    """The provider failed: HTTP error, transport/timeout, or a quota/rate-limit
    marker in the response body.

    ``status`` is the HTTP status code, or ``None`` for transport/timeout
    failures. ``marker`` is ``insufficient_quota`` or ``rate_limit`` when one
    of those appears in the response body, else ``None``. Never carries the
    API key value.
    """

    def __init__(
        self,
        message: str,
        status: int | None = None,
        marker: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.marker = marker


def is_provider_failure(exc: BaseException) -> bool:
    """True only for provider-side failures (``LLMProviderError``).

    Plain ``LLMUnavailable`` (missing key, invalid JSON/shape) and validation
    errors return False — those are not reasons to fall back to another
    provider/model.
    """
    return isinstance(exc, LLMProviderError)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _resolve_api_key(llm_config: dict, api_key: str | None) -> str:
    """Return the key to use: the explicit ``api_key`` when non-empty, else the
    ``llm_config["api_key_env"]`` environment variable.

    Raises ``LLMUnavailable`` when neither is set. The key value itself is
    never included in the message.
    """
    if api_key is not None and api_key.strip():
        return api_key
    key_env = llm_config.get("api_key_env") or ""
    env_key = os.environ.get(key_env) or ""
    if not env_key.strip():
        raise LLMUnavailable(
            f"API key environment variable {key_env!r} is missing or empty"
        )
    return env_key


#: Error-body markers that identify quota/rate-limit provider failures.
_PROVIDER_MARKERS = ("insufficient_quota", "rate_limit")


def _error_marker(response: object) -> str | None:
    """Extract a quota/rate-limit marker from an error response body, if any."""
    if response is None:
        return None
    body = getattr(response, "text", None)
    if not isinstance(body, str) or not body:
        try:
            body = json.dumps(response.json())
        except Exception:
            body = ""
    for marker in _PROVIDER_MARKERS:
        if marker in body:
            return marker
    return None


def _provider_error_from_http(exc: requests.HTTPError) -> LLMProviderError:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    marker = _error_marker(response)
    detail = f"HTTP {status}" if status is not None else "HTTP error"
    if marker:
        detail += f" ({marker})"
    return LLMProviderError(f"LLM provider error: {detail}", status=status, marker=marker)


def _chat_completion(llm_config: dict, prompt: str, api_key: str | None = None) -> str:
    """POST one chat completion; return the assistant message content text.

    Raises ``LLMUnavailable`` when no key is available (explicit ``api_key``
    argument wins over ``llm_config["api_key_env"]``; both missing/empty
    raises), and ``LLMProviderError`` when the provider HTTP call fails —
    carrying ``status`` and a body ``marker`` (``insufficient_quota`` /
    ``rate_limit``) when present; transport/timeout errors get
    ``status=None``. The key value is only ever placed in the Authorization
    header — never logged, printed, or stored.
    """
    key = _resolve_api_key(llm_config, api_key)
    base_url = str(llm_config.get("base_url") or "").rstrip("/")
    body = {
        "model": llm_config.get("model"),
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            json=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            timeout=llm_config.get("timeout_s", 60),
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise _provider_error_from_http(exc) from exc
    except requests.RequestException as exc:
        # Transport/timeout: no response to inspect.
        raise LLMProviderError(
            "LLM provider request failed (transport/timeout)", status=None
        ) from exc
    payload = response.json()
    return payload["choices"][0]["message"]["content"]


def _is_transient_http(exc: requests.RequestException) -> bool:
    """True for transport/timeouts and 429/5xx; false for other 4xx replies.

    Transport errors carry no response and are treated as transient. HTTP
    errors are inspected by status so a client error (e.g. 401 from a bad key)
    is not needlessly retried.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        return True
    return status == 429 or status >= 500


def _is_transient_provider(exc: LLMProviderError) -> bool:
    """Same transient rule as ``_is_transient_http``, keyed off ``exc.status``."""
    if exc.status is None:
        return True
    return exc.status == 429 or exc.status >= 500


def call_llm(llm_config: dict, prompt: str, api_key: str | None = None) -> dict:
    """Call the configured chat endpoint and return the parsed JSON reply.

    Raises ``LLMUnavailable`` when no API key is available (explicit
    ``api_key`` wins over the ``llm_config["api_key_env"]`` env var), when
    the HTTP call fails, or when the reply is not a JSON object. Provider-side
    failures raise ``LLMProviderError`` (a subclass of ``LLMUnavailable``, so
    it propagates here unchanged) with ``status``/``marker`` set; transient
    transport/timeout/429/5xx failures get bounded retries with short
    backoff. A missing key and invalid JSON are never retried. The key value
    never appears in any exception message.
    """
    _resolve_api_key(llm_config, api_key)  # fail fast; never retried
    raw = None
    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            raw = _chat_completion(llm_config, prompt, api_key=api_key)
            break
        except LLMProviderError as exc:
            if attempt >= LLM_MAX_RETRIES or not _is_transient_provider(exc):
                raise
            # Transport/timeout/429/5xx failures can be transient; wait a
            # little longer each time, with a hard cap on attempts and delay.
            time.sleep(LLM_RETRY_BACKOFF_S * (attempt + 1))
        except LLMUnavailable:
            raise
        except requests.RequestException as exc:
            if attempt >= LLM_MAX_RETRIES or not _is_transient_http(exc):
                raise LLMUnavailable(f"LLM call failed: {exc}") from exc
            time.sleep(LLM_RETRY_BACKOFF_S * (attempt + 1))
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"LLM call failed: {exc}") from exc

    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError) as exc:
        raise LLMUnavailable(f"LLM reply is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMUnavailable("LLM reply is not a JSON object")
    return parsed


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

def build_prompt(payload: dict) -> str:
    """Serialize the computed `payload` into a strict JSON-only instruction.

    The prompt carries the payload (indicators, entry/exit levels, key
    levels, quotes), the derived ``allowed_levels`` list the model must pick
    every scenario price from, the required output shape, and the behavioural
    rules (subjective probabilities summing to 100 per horizon, confidence in
    0..1, no guaranteed/75% claims, educational-only disclaimer).
    """
    levels = allowed_levels(payload)
    data_json = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    levels_json = json.dumps(levels, ensure_ascii=False)
    return f"""You are the analyst behind a crypto playbook report. You write \
narrative only: every price below was computed deterministically from market \
data. Never invent, recompute, or round a price that is not in DATA or in \
ALLOWED_PRICE_LEVELS.

Return JSON only — no markdown fences, no commentary before or after.

REQUIRED SHAPE (every key required):
{{
  "highest_conviction": {{"text": "...", "confidence": 0.0}},
  "scenarios": {{
    "{HORIZONS[0]}": [{{"label": "...", "low": 0, "high": 0, "probability": 0}}],
    "{HORIZONS[1]}": [{{"label": "...", "low": 0, "high": 0, "probability": 0}}]
  }},
  "per_timeframe": {{"15m": "...", "4h": "...", "1D": "..."}},
  "favored_trade": "...",
  "confirmation": "...",
  "invalidation": "...",
  "bottom_line": "..."
}}

RULES:
- Every scenario "low" and "high" MUST be a value copied exactly from \
ALLOWED_PRICE_LEVELS below. No other price may appear anywhere in the JSON.
- "probability" values are SUBJECTIVE ESTIMATES from the chart, not measured \
facts; say so in the text. Probabilities within each horizon group \
("{HORIZONS[0]}" and "{HORIZONS[1]}") must sum to 100.
- "confidence" is your subjective conviction, a number in 0..1.
- Ground the narrative in DATA: the entry/exit table (levels.positions), the \
key support/resistance levels, the indicators and the quotes.
- Never claim a guaranteed outcome or win rate, and never mention "75%".
- "bottom_line" MUST end with an educational-only disclaimer such as \
"Educational only — not financial advice."

DATA (computed payload, JSON):
{data_json}

ALLOWED_PRICE_LEVELS (the only permitted low/high values, JSON):
{levels_json}
"""


# --------------------------------------------------------------------------
# Grounded levels
# --------------------------------------------------------------------------

def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _numbers_under(node: object) -> list[float]:
    """Every finite number nested under `node` (scalars, dicts and lists)."""
    if _is_number(node):
        return [float(node)]
    found: list[float] = []
    if isinstance(node, dict):
        for value in node.values():
            if _is_number(value):
                found.append(float(value))
            else:
                found.extend(_numbers_under(value))
    elif isinstance(node, (list, tuple)):
        for value in node:
            if _is_number(value):
                found.append(float(value))
            else:
                found.extend(_numbers_under(value))
    return found


def _psychological_levels(price: float) -> list[float]:
    """Round levels near `price`: steps of 10^(digits-2), ±10 steps.

    64053 -> 1000-wide steps (64000, 65000, 60000, 70000, ...); 2500 ->
    100-wide steps. Skipped when `price` is not a positive finite number.
    """
    if not math.isfinite(price) or price <= 0:
        return []
    step = 10.0 ** (math.floor(math.log10(price)) - 1)
    base = math.floor(price / step) * step
    return [round(base + offset * step, 10) for offset in PSYCH_OFFSETS]


def allowed_levels(payload: dict) -> list[float]:
    """Sorted, deduplicated floats: every price-like number in `payload`
    plus psychological round levels derived from its reference price.

    The recursive walk only collects numbers stored under price keys
    (price/entry/tp1/tp2/stop/support/resistance/bollinger bands/moving
    averages/quote prices), so indicator readings such as RSI or MACD hist
    never become "allowed prices". The reference price for the psychological
    levels is the median of the ``price`` values in the payload.
    """
    if not isinstance(payload, dict):
        return []
    levels: set[float] = set()
    prices: list[float] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and key.lower() in PRICE_KEYS:
                    numbers = _numbers_under(value)
                    levels.update(numbers)
                    if key.lower() == "price":
                        prices.extend(numbers)
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(payload)
    if prices:
        ordered = sorted(prices)
        reference = ordered[len(ordered) // 2]
        levels.update(_psychological_levels(reference))
    return sorted(levels)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _near(value: float, level: float) -> bool:
    """True when `value` is within PRICE_TOLERANCE of `level`."""
    return abs(value - level) <= PRICE_TOLERANCE * abs(level)


def _iter_scenarios(scenarios: object):
    """Yield ``(horizon, position, scenario)`` from a horizon-keyed dict or
    a flat list (a list groups every horizon-less scenario into "all")."""
    if isinstance(scenarios, dict):
        for horizon, items in scenarios.items():
            if isinstance(items, list):
                for position, scenario in enumerate(items):
                    yield str(horizon), position, scenario
    elif isinstance(scenarios, list):
        for position, scenario in enumerate(scenarios):
            if isinstance(scenario, dict):
                yield str(scenario.get("horizon") or "all"), position, scenario
            else:
                yield "all", position, scenario


def _narrative_strings(node: object):
    """Every string value nested in `node` (dicts and lists), recursively."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _narrative_strings(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _narrative_strings(value)


def _excluded_price_token(text: str, match: re.Match) -> bool:
    """True for a numeric token that is obviously not a price: a percentage,
    a ratio/probability, a plain four-digit year, an indicator reading
    explicitly labelled RSI/MACD/ATR, a number with an M/B/K size-unit suffix,
    or one preceded shortly by a volume/liquidity/funding/market-cap label.
    Ordinary prices are never excluded.
    """
    start, end = match.span()
    literal = match.group(0)
    # "2.6%" / "65%" — a percentage, not a price.
    if end < len(text) and text[end] == "%":
        return True
    # "2.6:1" / "60:40" — a ratio or odds, not a price.
    if (
        end < len(text)
        and text[end] == ":"
        and end + 1 < len(text)
        and text[end + 1].isdigit()
    ):
        return True
    # A bare four-digit year such as 2026.
    if "," not in literal and "." not in literal and len(literal) == 4:
        if 1900 <= int(literal) <= 2099:
            return True
    # An indicator value named just before the number: "RSI 4321", "ATR 2100".
    before = text[max(0, start - 32):start]
    if _INDICATOR_LABEL_RE.search(before):
        return True
    # "1,410.67M" / "3,456.78B" — an explicit size-unit suffix, not a price.
    if _UNIT_SUFFIX_RE.match(text[end:end + 2]):
        return True
    # A volume/liquidity/funding/market-cap label just before the number marks
    # it as a size measure. Skip that label when a genuine price word sits
    # between it and the number, so real prices are never suppressed.
    for label in _VOLUME_LABEL_RE.finditer(before):
        if _PRICE_WORD_RE.search(before[label.end():]):
            continue
        return True
    return False


def _narrative_price_errors(prediction: dict, levels: list[float]) -> list[str]:
    """Reject price-like numbers in prose that are not near an allowed level.

    The scenario low/high check only covers those two fields; the prompt also
    forbids any other invented price anywhere in the JSON. Numeric fields are
    left to their own checks — this scans only string (narrative) values.
    """
    errors: list[str] = []
    seen: set[str] = set()
    for prose in _narrative_strings(prediction):
        for match in PRICE_TOKEN_RE.finditer(prose):
            if _excluded_price_token(prose, match):
                continue
            value = float(match.group(0).replace(",", ""))
            if any(_near(value, level) for level in levels):
                continue
            token = match.group(0)
            if token in seen:
                continue
            seen.add(token)
            errors.append(
                f"narrative price {token} is not within 0.5% of any allowed level"
            )
    return errors


def validate_prediction(prediction: dict, allowed: list[float]) -> list[str]:
    """Return a list of grounding problems with `prediction`; empty = valid.

    Checks: every scenario low/high within 0.5% of an allowed level and
    inside the allowed span, every price-like token in narrative prose within
    0.5% of an allowed level, probabilities summing to 100 per horizon,
    confidence in 0..1, a present highest_conviction block, and no banned
    phrases ("75%", "guaranteed").
    """
    if not isinstance(prediction, dict):
        return ["prediction must be a JSON object"]
    errors: list[str] = []

    levels = sorted({float(v) for v in (allowed or []) if _is_number(v)})

    totals: dict[str, float] = {}
    for horizon, position, scenario in _iter_scenarios(prediction.get("scenarios")):
        if not isinstance(scenario, dict):
            errors.append(f"scenario {position} must be a JSON object")
            continue
        where = scenario.get("label") or f"#{position}"
        for field in ("low", "high"):
            value = scenario.get(field)
            if not _is_number(value):
                errors.append(
                    f"scenario {where}: {field} price {value!r} is not a number"
                )
                continue
            number = float(value)
            if not levels:
                errors.append(
                    f"scenario {where}: {field} price {number} cannot be "
                    "grounded — no allowed levels"
                )
                continue
            if not any(_near(number, level) for level in levels):
                errors.append(
                    f"scenario {where}: {field} price {number} is not within "
                    "0.5% of any allowed level"
                )
            if number < levels[0] or number > levels[-1]:
                errors.append(
                    f"scenario {where}: {field} price {number} is outside the "
                    f"allowed range {levels[0]:g}-{levels[-1]:g}"
                )
        probability = scenario.get("probability")
        if _is_number(probability):
            totals[horizon] = totals.get(horizon, 0.0) + float(probability)
        else:
            errors.append(
                f"scenario {where}: probability {probability!r} is not a number"
            )

    for horizon, total in totals.items():
        if abs(total - 100.0) > PROBABILITY_SUM_TOLERANCE:
            errors.append(
                f"scenario probabilities for horizon {horizon} must sum to "
                f"100 (got {total:g})"
            )

    conviction = prediction.get("highest_conviction")
    if not isinstance(conviction, dict):
        errors.append("missing highest_conviction {text, confidence}")
    else:
        confidence = conviction.get("confidence")
        if not _is_number(confidence) or not 0 <= float(confidence) <= 1:
            errors.append(
                f"confidence must be a number between 0 and 1, got {confidence!r}"
            )

    text = json.dumps(prediction, ensure_ascii=False, default=str).lower()
    for phrase in BANNED_PHRASES:
        if phrase in text:
            errors.append(f"banned phrase {phrase!r} appears in the prediction")

    errors.extend(_narrative_price_errors(prediction, levels))

    return errors
