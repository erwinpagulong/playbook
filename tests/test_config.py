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
