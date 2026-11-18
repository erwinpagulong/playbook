from engine.config import load_config, save_config, validate_config


def test_defaults(tmp_path):
    c = load_config(tmp_path / "missing.json")
    assert c["coins"] == ["BTC/USDT", "ETH/USDT"]
    assert c["interval_minutes"] == 60
    assert c["llm"]["api_key_env"] == "OPENAI_API_KEY"
    assert c["llm"]["base_url"].startswith("https://")


def test_round_trip(tmp_path):
    p = tmp_path / "config.json"
    c = load_config(p)
    c["coins"] = ["ETH/USDT"]
    save_config(c, p)
    assert load_config(p)["coins"] == ["ETH/USDT"]


def test_validate_rejects_bad_coin_and_url():
    c = load_config(None)
    c["coins"] = ["NOT A COIN"]
    c["llm"]["base_url"] = "not-a-url"
    errors = validate_config(c)
    assert any("coin" in e for e in errors)
    assert any("base_url" in e for e in errors)


def test_validate_rejects_plaintext_key_endpoint_off_loopback():
    c = load_config(None)
    c["llm"]["base_url"] = "http://api.example.com/v1"
    errors = validate_config(c)
    assert any("https" in error.lower() for error in errors)


def test_validate_allows_loopback_http_and_remote_https():
    for url in (
        "http://127.0.0.1:11434/v1",
        "http://localhost:11434/v1",
        "http://[::1]:11434/v1",
        "https://api.example.com/v1",
    ):
        c = load_config(None)
        c["llm"]["base_url"] = url
        assert validate_config(c) == [], url
