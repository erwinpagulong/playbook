import json

from engine.keys import clear_key, key_for, load_keys, mask, set_key


def test_keys_file_is_mode_600_and_round_trips(tmp_path):
    p = tmp_path / "keys.json"
    set_key("openrouter", "sk-1234567890abcdef", p)
    assert p.stat().st_mode & 0o777 == 0o600
    assert load_keys(p) == {"providers": {"openrouter": "sk-1234567890abcdef"}}


def test_key_hint_is_masked():
    assert mask("sk-1234567890abcdef") == "sk-…cdef"
    assert mask("short") == "••••hort"
    assert mask("abcd") == "••••"
    assert mask("AIzaSyABC123") == "••••C123"


def test_mask_never_reveals_full_key():
    for key in ["sk-1234567890abcdef", "AIzaSyABC123", "gsk_abcdefgh", "short", "abcd"]:
        assert key not in mask(key)


def test_load_keys_skips_non_string_and_empty_values(tmp_path):
    p = tmp_path / "keys.json"
    p.write_text(
        json.dumps({"providers": {"null_key": None, "num_key": 123, "empty_key": "", "real_key": "sk-realvalue123"}}),
        encoding="utf-8",
    )
    assert load_keys(p) == {"providers": {"real_key": "sk-realvalue123"}}


def test_clear_key_removes_only_that_provider(tmp_path):
    p = tmp_path / "keys.json"
    set_key("openrouter", "a", p); set_key("deepseek", "b", p)
    clear_key("openrouter", p)
    assert load_keys(p)["providers"] == {"deepseek": "b"}


def test_key_for_prefers_file_then_env(monkeypatch, tmp_path):
    p = tmp_path / "keys.json"
    set_key("openrouter", "file-key", p)
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    cfg = {"llm": {"api_key_env": "OPENAI_API_KEY"}}
    assert key_for("openrouter", cfg, p) == "file-key"
    assert key_for("deepseek", cfg, p) == "env-key"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert key_for("deepseek", cfg, p) == ""
