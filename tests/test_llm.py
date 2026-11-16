"""Tests for the LLM call and grounded-output validation.

All tests are offline: `_chat_completion` or `requests.post` are monkeypatched
and the API key comes only from monkeypatched env vars.
"""

import pytest
import requests

from engine import llm
from engine.llm import (
    LLMUnavailable,
    allowed_levels,
    build_prompt,
    call_llm,
    validate_prediction,
)


# --- brief: call_llm -------------------------------------------------------

def test_call_llm_without_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMUnavailable):
        call_llm({"api_key_env": "OPENAI_API_KEY"}, "prompt")


def test_call_llm_parses_json(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(llm, "_chat_completion", lambda *a, **k: '{"highest_conviction": {"text": "x", "confidence": 0.6}}')
    assert call_llm({"api_key_env": "OPENAI_API_KEY"}, "prompt")["highest_conviction"]["confidence"] == 0.6


# --- brief: validate_prediction -------------------------------------------

def test_validator_rejects_unknown_price():
    p = {"scenarios": [{"label": "Bounce 64,945", "low": 64945, "high": 65200, "probability": 45}]}
    errors = validate_prediction(p, [64945.0, 63905.0])
    assert any("65200" in e or "price" in e for e in errors)


def test_validator_rejects_bad_probabilities_and_confidence():
    p = {"scenarios": [{"low": 100, "high": 200, "probability": 45}], "highest_conviction": {"confidence": 1.5}}
    errors = validate_prediction(p, [100.0, 200.0])
    assert any("probabilit" in e for e in errors)
    assert any("confidence" in e for e in errors)


def test_validator_accepts_valid():
    p = {"scenarios": [{"low": 100, "high": 200, "probability": 60}, {"low": 50, "high": 100, "probability": 40}],
         "highest_conviction": {"text": "x", "confidence": 0.6}}
    assert validate_prediction(p, [100.0, 200.0, 50.0]) == []


# --- call_llm failure modes ------------------------------------------------

def test_call_llm_empty_key_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(LLMUnavailable):
        call_llm({"api_key_env": "OPENAI_API_KEY"}, "prompt")


def test_call_llm_http_failure_raises_and_never_leaks_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-key")
    monkeypatch.setattr(
        llm,
        "_chat_completion",
        lambda *a, **k: (_ for _ in ()).throw(requests.RequestException("boom")),
    )
    with pytest.raises(LLMUnavailable) as excinfo:
        call_llm({"api_key_env": "OPENAI_API_KEY"}, "prompt")
    assert "super-secret-key" not in str(excinfo.value)


def test_call_llm_invalid_json_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(llm, "_chat_completion", lambda *a, **k: "not json at all")
    with pytest.raises(LLMUnavailable):
        call_llm({"api_key_env": "OPENAI_API_KEY"}, "prompt")


def test_call_llm_accepts_dict_reply(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(llm, "_chat_completion", lambda *a, **k: {"bottom_line": "x"})
    assert call_llm({"api_key_env": "OPENAI_API_KEY"}, "prompt") == {"bottom_line": "x"}


# --- _chat_completion request shape (requests.post patched, no network) ----

def test_chat_completion_posts_json_object_with_timeout(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"ok": 1}'}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content = llm._chat_completion(
        {
            "base_url": "https://llm.example/v1/",
            "model": "some-model",
            "api_key_env": "OPENAI_API_KEY",
            "timeout_s": 42,
        },
        "hello",
    )
    assert content == '{"ok": 1}'
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["json"]["model"] == "some-model"
    assert captured["timeout"] == 42
    assert captured["headers"]["Authorization"] == "Bearer test-key"


# --- allowed_levels --------------------------------------------------------

def test_allowed_levels_collects_payload_prices_and_round_levels():
    payload = {
        "indicators": {
            "15m": {
                "price": 64053.0,
                "bollinger": {"lower": 63500.0, "mid": 64000.0, "upper": 64500.0},
                "moving_averages": {"ema12": 64010.0, "sma200": 61000.0},
            }
        },
        "levels": {
            "key_levels": {"support": [63905.0], "resistance": [64945.0]},
            "positions": [
                {"entry": 63905.0, "tp1": 64945.0, "tp2": 65500.0, "stop": 63500.0}
            ],
        },
        "quotes": [{"source": "Binance", "price": 64040.0}],
    }
    allowed = allowed_levels(payload)
    for value in (
        64053.0, 63500.0, 64000.0, 64500.0, 64010.0, 61000.0,
        63905.0, 64945.0, 65500.0, 64040.0,
    ):
        assert value in allowed, value
    # psychological round level derived from the ~64k price (step 1000)
    assert 65000.0 in allowed
    assert allowed == sorted(allowed)
    assert all(isinstance(v, float) for v in allowed)


def test_allowed_levels_excludes_non_price_numbers():
    payload = {
        "indicators": {
            "15m": {"price": 100.0, "rsi": 64.32, "atr": 7.5, "macd": {"hist": -1.25}}
        }
    }
    allowed = allowed_levels(payload)
    assert 100.0 in allowed
    assert 64.32 not in allowed
    assert 7.5 not in allowed
    assert -1.25 not in allowed


# --- build_prompt ----------------------------------------------------------

def test_build_prompt_includes_grounding_and_disclaimer_instructions():
    payload = {
        "indicators": {"15m": {"price": 64053}},
        "levels": {
            "key_levels": {"support": [63905], "resistance": [64945]},
            "positions": [{"entry": 63905, "tp1": 64945, "tp2": 65500, "stop": 63500}],
        },
        "quotes": [{"source": "Binance", "price": 64040}],
    }
    prompt = build_prompt(payload)
    # the computed payload (incl. the entry/exit table) is serialized into it
    assert "64945" in prompt
    assert "tp2" in prompt
    # the allowed level list is supplied so low/high can be chosen from it
    assert "65000" in prompt
    # required output shape
    assert '"24-48h"' in prompt
    assert '"1-2w"' in prompt
    for key in (
        "highest_conviction", "confidence", "scenarios", "label", "low", "high",
        "probability", "per_timeframe", "favored_trade", "confirmation",
        "invalidation", "bottom_line",
    ):
        assert key in prompt, key
    # behavioural instructions
    assert "100" in prompt  # probabilities sum to 100 per horizon
    assert "subjective" in prompt.lower()
    assert "guaranteed" in prompt.lower()  # never claim a guaranteed win rate
    assert "75%" in prompt  # never mention a 75% win rate
    assert "educational" in prompt.lower()  # educational-only disclaimer
    assert "json" in prompt.lower()


# --- validate_prediction: extra rules --------------------------------------

def test_validator_rejects_banned_phrases():
    base = {
        "scenarios": [
            {"low": 100, "high": 200, "probability": 60},
            {"low": 50, "high": 100, "probability": 40},
        ],
        "highest_conviction": {"text": "x", "confidence": 0.6},
    }
    allowed = [50.0, 100.0, 200.0]
    errors = validate_prediction(
        {**base, "bottom_line": "A 75% win rate from this setup"}, allowed
    )
    assert any("75%" in e for e in errors)
    errors = validate_prediction(
        {**base, "bottom_line": "This bounce is guaranteed"}, allowed
    )
    assert any("guaranteed" in e for e in errors)


def test_validator_accepts_price_within_half_percent():
    # 64700 is 0.39% below 64945: rounding toward a known level is allowed.
    p = {
        "scenarios": [{"low": 64700, "high": 64945, "probability": 100}],
        "highest_conviction": {"text": "x", "confidence": 0.5},
    }
    assert validate_prediction(p, [63905.0, 64945.0]) == []


def test_validator_groups_probabilities_by_horizon():
    p = {
        "scenarios": {
            "24-48h": [{"low": 100, "high": 200, "probability": 60}],
            "1-2w": [{"low": 100, "high": 200, "probability": 45}],
        },
        "highest_conviction": {"text": "x", "confidence": 0.6},
    }
    errors = validate_prediction(p, [100.0, 200.0])
    # the 1-2w horizon does not sum to 100; the 24-48h group is also incomplete
    assert any("probabilit" in e for e in errors)
