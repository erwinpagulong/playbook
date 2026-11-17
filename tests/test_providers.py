import json

from engine.config import load_config, validate_config
from engine.keys import set_key
from engine.providers import (
    PRESETS,
    is_valid_provider,
    provider_llm_config,
    provider_list,
)


def test_defaults_and_merging():
    cfg = load_config(None)
    assert cfg["llm"]["provider"] == "openai"
    assert cfg["llm"]["fallback_provider"] is None
    assert provider_llm_config("deepseek", cfg)["base_url"] == PRESETS["deepseek"]["base_url"]
    cfg["llm"]["provider"] = "deepseek"
    cfg["llm"]["model"] = "my-model"
    assert provider_llm_config("deepseek", cfg)["model"] == "my-model"
    assert provider_llm_config("openrouter", cfg)["model"] == PRESETS["openrouter"]["model"]


def test_provider_list_has_no_full_key(tmp_path, monkeypatch):
    p = tmp_path / "keys.json"
    set_key("openrouter", "sk-secret-value-1234", p)
    cfg = load_config(None); cfg["llm"]["provider"] = "openrouter"
    rows = provider_list(cfg, p)
    row = next(r for r in rows if r["id"] == "openrouter")
    assert row["active"] is True and row["key_set"] is True
    assert row["key_hint"] == "sk-…1234"
    assert "sk-secret-value-1234" not in json.dumps(rows)


def test_validation_rejects_bad_provider_and_self_fallback():
    cfg = load_config(None)
    cfg["llm"]["provider"] = "nope"
    assert any("provider" in e for e in validate_config(cfg))
    cfg["llm"]["provider"] = "openai"; cfg["llm"]["fallback_provider"] = "openai"
    assert any("fallback" in e for e in validate_config(cfg))


def test_is_valid_provider():
    for pid in ("openai", "openrouter", "deepseek", "groq", "custom"):
        assert is_valid_provider(pid)
    assert not is_valid_provider("nope")
    assert not is_valid_provider(None)
    assert not is_valid_provider("")


def test_provider_llm_config_returns_fresh_dict_and_overlays():
    cfg = load_config(None)
    cfg["llm"]["provider"] = "openai"
    cfg["llm"]["api_key_env"] = "MY_KEY_ENV"
    cfg["llm"]["timeout_s"] = 12
    first = provider_llm_config("groq", cfg)
    second = provider_llm_config("groq", cfg)
    assert first == second and first is not second
    assert first["base_url"] == PRESETS["groq"]["base_url"]
    assert first["api_key_env"] == "MY_KEY_ENV"
    assert first["timeout_s"] == 12


def test_provider_list_rows_cover_all_presets_without_keys(tmp_path):
    p = tmp_path / "keys.json"
    cfg = load_config(None)
    rows = provider_list(cfg, p)
    assert [r["id"] for r in rows] == list(PRESETS)
    for row in rows:
        assert set(row) == {
            "id", "name", "base_url", "model",
            "active", "fallback", "key_set", "key_hint",
        }
        assert row["key_set"] is False
        assert row["key_hint"] == ""
    assert next(r for r in rows if r["id"] == "openai")["active"] is True
