"""Tests for the generation pipeline (Task 8).

All tests are offline: the network seams (`data.fetch_candles`,
`data.fetch_quotes`) and the LLM seam (`llm.call_llm`) are monkeypatched —
the autouse `offline_seams` fixture provides defaults that every test
overrides as needed.
"""

import concurrent.futures
import json
import logging
import time

import pytest

from engine import data, llm, providers
from engine.config import load_config
from engine.data import DataUnavailable
from engine.generate import generate_report
from engine.llm import LLMUnavailable, call_llm as real_call_llm
from engine.models import Candle
from engine.report import list_reports

# Flat candles at price 100: every indicator resolves around 100, so the
# allowed price levels are the psychological 10-steps (0..200) around it.
FLAT_CANDLE = Candle(1, 100, 101, 99, 100, 1)


def valid_prediction():
    """An LLM reply that passes `llm.validate_prediction` for flat 100-price data.

    Scenario low/high values sit exactly on allowed levels (psychological
    steps of 10 around the 100 reference price), probabilities sum to 100
    per horizon, confidence is in 0..1, and no banned phrase appears.
    """
    return {
        "highest_conviction": {"text": "Range-bound near 100", "confidence": 0.6},
        "scenarios": {
            "24-48h": [
                {"label": "Hold 100", "low": 90, "high": 110, "probability": 60},
                {"label": "Slip to 80", "low": 80, "high": 90, "probability": 40},
            ],
            "1-2w": [
                {"label": "Grind to 120", "low": 110, "high": 120, "probability": 50},
                {"label": "Fade to 70", "low": 70, "high": 80, "probability": 50},
            ],
        },
        "per_timeframe": {"15m": "flat", "4h": "flat", "1D": "flat"},
        "favored_trade": "wait for a confirmed break",
        "confirmation": "close above 110",
        "invalidation": "close below 70",
        "bottom_line": "Neutral range — educational only, not financial advice.",
    }


@pytest.fixture(autouse=True)
def offline_seams(monkeypatch):
    """Offline defaults: no quotes, no LLM. Tests override both as needed."""
    monkeypatch.setattr(data, "fetch_quotes", lambda *a, **k: [])
    monkeypatch.setattr(
        llm,
        "call_llm",
        lambda *a, **k: (_ for _ in ()).throw(LLMUnavailable("offline test stub")),
    )


# --- brief: pipeline happy path --------------------------------------------

def test_pipeline_produces_prediction(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    monkeypatch.setattr(
        data,
        "fetch_quotes",
        lambda *a, **k: [{"source": "stub", "price": 100.0, "change_pct": 1.5}],
    )
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: valid_prediction())
    result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["error"] is None
    assert result["report"]["prediction"]["available"] is True
    # the quote snapshot and the flattened scenarios land in the report
    assert result["report"]["snapshot"]["sources"][0]["source"] == "stub"
    assert result["report"]["prediction"]["scenarios"][0]["horizon"] == "24-48h"
    assert list_reports(tmp_path)[0]["id"] == result["report"]["id"]


# --- brief: LLM failure -----------------------------------------------------

def test_llm_failure_still_saves_report(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("OPENAI_API_KEY", "sentinel-key-never-logged")
    monkeypatch.setattr(
        llm, "call_llm", lambda *a, **k: (_ for _ in ()).throw(LLMUnavailable())
    )
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    with caplog.at_level(logging.WARNING):
        result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["report"]["prediction"]["available"] is False
    assert result["report"]["prediction"]["reason"]
    assert result["error"]
    assert list_reports(tmp_path)[0]["id"] == result["report"]["id"]
    # the reason is logged and returned, but never an API key value
    assert "sentinel-key-never-logged" not in caplog.text
    assert "sentinel-key-never-logged" not in str(result["error"])


def test_invalid_llm_output_still_saves_report(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: {
        "highest_conviction": {"text": "up", "confidence": 0.5},
        "scenarios": {
            "24-48h": [{"label": "invented", "low": 99999, "high": 100000, "probability": 100}],
        },
    })
    result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["report"]["prediction"]["available"] is False
    assert "99999" in result["report"]["prediction"]["reason"]
    assert list_reports(tmp_path)[0]["id"] == result["report"]["id"]


def test_validation_failure_gets_one_corrective_retry(monkeypatch, tmp_path):
    """One malformed reply (ungrounded narrative price) is retried once with
    a corrective instruction, and the valid retry lands as the prediction."""
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    prompts = []

    def fake_call(cfg, prompt, api_key=None):
        prompts.append(prompt)
        if len(prompts) == 1:
            bad = valid_prediction()
            bad["bottom_line"] = (
                "Price could reach 71234 before the weekend — educational only."
            )
            return bad
        return valid_prediction()

    monkeypatch.setattr(llm, "call_llm", fake_call)
    result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert len(prompts) == 2
    assert result["report"]["prediction"]["available"] is True
    # the retry reuses the original prompt plus a key-free correction that
    # names the rejected token and the grounding rule
    assert prompts[1].startswith(prompts[0])
    assert "71234" in prompts[1]
    assert "ALLOWED_PRICE_LEVELS" in prompts[1]


# --- brief: fetch failure falls back to cache -------------------------------

def test_fetch_failure_uses_cache(monkeypatch, tmp_path):
    cache = tmp_path / "candles" / "BTC_USDT_15m.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps([{"timestamp": 1, "open": 100, "high": 101,
                                   "low": 99, "close": 100, "volume": 1}] * 210))
    monkeypatch.setattr(
        data, "fetch_candles", lambda *a, **k: (_ for _ in ()).throw(DataUnavailable())
    )
    result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["report"]["indicators"]["15m"]["price"] == 100
    # 4h and 1D have no cache: skipped and reported, but the report still saves
    assert "4h" not in result["report"]["indicators"]
    assert result["error"]


# --- fix round 1: total data failure returns an error, never raises ---------

def test_total_data_failure_returns_error_without_report(monkeypatch, tmp_path):
    monkeypatch.setattr(
        data, "fetch_candles", lambda *a, **k: (_ for _ in ()).throw(DataUnavailable())
    )
    result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["report"] is None
    assert isinstance(result["error"], str) and result["error"]
    # nothing was persisted: there is no report to save
    assert list_reports(tmp_path) == []


# --- brief: provider selection and fallback -----------------------------------

def test_quota_failure_uses_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    calls = []
    def fake_call(cfg, prompt, api_key=None):
        calls.append((cfg["base_url"], api_key))
        if len(calls) == 1: raise llm.LLMProviderError("429", status=429, marker="insufficient_quota")
        return valid_prediction()
    monkeypatch.setattr(llm, "call_llm", fake_call)
    cfg = load_config(None)
    cfg["llm"]["provider"] = "openrouter"; cfg["llm"]["fallback_provider"] = "deepseek"
    result = generate_report("BTC/USDT", cfg, tmp_path)
    assert len(calls) == 2
    assert result["report"]["prediction"]["fallback_used"] is True
    assert result["report"]["prediction"]["provider"] == "deepseek"


def test_deepseek_call_uses_own_env_var_not_global(monkeypatch, tmp_path):
    """DeepSeek (a non-active fallback) uses DEEPSEEK_API_KEY, not the global.

    No stored key exists and the global legacy variable holds a different
    value; the preset's own variable must win for the call.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    for name in (
        "OPENAI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY",
        "GROQ_API_KEY", "CUSTOM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-call")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-global-wrong")
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    seen_keys = []

    def fake_call(cfg, prompt, api_key=None):
        seen_keys.append(api_key)
        if len(seen_keys) == 1:
            raise llm.LLMProviderError("429", status=429, marker="insufficient_quota")
        return valid_prediction()

    monkeypatch.setattr(llm, "call_llm", fake_call)
    cfg = load_config(None)
    cfg["llm"]["fallback_provider"] = "deepseek"
    result = generate_report("BTC/USDT", cfg, tmp_path)
    assert result["report"]["prediction"]["fallback_used"] is True
    assert result["report"]["prediction"]["provider"] == "deepseek"
    assert seen_keys == ["sk-global-wrong", "sk-deepseek-call"]


def test_invalid_output_does_not_fall_back(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    calls = []
    def fake_call(cfg, prompt, api_key=None):
        calls.append(cfg["base_url"])
        return {"scenarios": [{"low": 99999, "high": 99999, "probability": 100}]}
    monkeypatch.setattr(llm, "call_llm", fake_call)
    cfg = load_config(None)
    cfg["llm"]["provider"] = "openai"
    cfg["llm"]["base_url"] = providers.PRESETS["openai"]["base_url"]
    cfg["llm"]["model"] = providers.PRESETS["openai"]["model"]
    cfg["llm"]["fallback_provider"] = "deepseek"
    result = generate_report("BTC/USDT", cfg, tmp_path)
    # the one corrective retry reuses the SAME provider — never the fallback
    assert len(calls) == 2
    assert all(url == providers.PRESETS["openai"]["base_url"] for url in calls)
    assert result["report"]["prediction"]["available"] is False
    assert result["report"]["prediction"]["provider"] == "openai"
    assert result["report"]["prediction"]["fallback_used"] is False


def test_active_provider_selects_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    seen = []
    monkeypatch.setattr(llm, "call_llm", lambda cfg, p, api_key=None: (seen.append(cfg["base_url"]), valid_prediction())[1])
    cfg = load_config(None); cfg["llm"]["provider"] = "deepseek"
    # The Model screen writes the selected preset's base_url/model into the
    # config (spec: "Selecting a provider/model fills its base URL and
    # default model"); the active-provider overlay then honors them.
    cfg["llm"]["base_url"] = providers.PRESETS["deepseek"]["base_url"]
    cfg["llm"]["model"] = providers.PRESETS["deepseek"]["model"]
    generate_report("BTC/USDT", cfg, tmp_path)
    assert seen == [providers.PRESETS["deepseek"]["base_url"]]


def test_custom_provider_without_destination_never_sends_the_custom_key(monkeypatch, tmp_path):
    """A Custom selection without its own endpoint must not reuse another URL.

    The previous provider's URL is still in ``llm.base_url`` when the UI
    switches to Custom before a destination is entered; the Custom key must
    never travel to that endpoint.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("CUSTOM_API_KEY", "sk-custom-secret")
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    posted = []
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: posted.append(1))
    # The autouse fixture stubs call_llm; use the real request path here so the
    # assertion covers the actual HTTP seam.
    monkeypatch.setattr(llm, "call_llm", real_call_llm)
    cfg = load_config(None)
    cfg["llm"]["provider"] = "custom"

    result = generate_report("BTC/USDT", cfg, tmp_path)

    assert posted == []
    assert result["report"]["prediction"]["available"] is False
    assert "sk-custom-secret" not in json.dumps(result["report"])


def test_bad_request_does_not_fall_back(monkeypatch, tmp_path):
    """A provider error outside the fallback set (HTTP 400) never triggers fallback."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    calls = []
    def fake_call(cfg, prompt, api_key=None):
        calls.append(1)
        raise llm.LLMProviderError("400", status=400)
    monkeypatch.setattr(llm, "call_llm", fake_call)
    cfg = load_config(None); cfg["llm"]["fallback_provider"] = "deepseek"
    result = generate_report("BTC/USDT", cfg, tmp_path)
    assert len(calls) == 1
    assert result["report"]["prediction"]["available"] is False


def test_unavailable_prediction_records_provider_and_model(monkeypatch, tmp_path):
    """The unavailable path also records which provider/model was attempted."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    monkeypatch.setattr(
        llm, "call_llm",
        lambda *a, **k: (_ for _ in ()).throw(llm.LLMProviderError("429", status=429)),
    )
    cfg = load_config(None)
    result = generate_report("BTC/USDT", cfg, tmp_path)
    prediction = result["report"]["prediction"]
    assert prediction["available"] is False
    assert prediction["provider"] == "openai"
    assert prediction["model"] == cfg["llm"]["model"]
    assert prediction["fallback_used"] is False


def test_no_fallback_configured_stays_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: (_ for _ in ()).throw(llm.LLMProviderError("429", status=429)))
    cfg = load_config(None)
    result = generate_report("BTC/USDT", cfg, tmp_path)
    assert result["report"]["prediction"]["available"] is False


# --- brief: serialized generation -------------------------------------------

def test_generate_is_serialized(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [FLAT_CANDLE] * 210)
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: (time.sleep(0.05), valid_prediction())[1])
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _: generate_report("BTC/USDT", load_config(None), tmp_path), range(4)))
    ids = [r["report"]["id"] for r in results]
    assert len(ids) == len(set(ids)) == 4
    assert all(r["report"]["prediction"]["available"] for r in results)
