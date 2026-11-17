from engine.keys import clear_key, key_for, load_keys, mask, set_key


def test_keys_file_is_mode_600_and_round_trips(tmp_path):
    p = tmp_path / "keys.json"
    set_key("openrouter", "sk-1234567890abcdef", p)
    assert p.stat().st_mode & 0o777 == 0o600
    assert load_keys(p) == {"providers": {"openrouter": "sk-1234567890abcdef"}}


def test_key_hint_is_masked():
    assert mask("sk-1234567890abcdef") == "sk-…cdef"
    assert mask("short") == "••••short"


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
