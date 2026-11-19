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


def test_validate_reports_a_malformed_url_instead_of_raising():
    c = load_config(None)
    c["llm"]["base_url"] = "http://[::1"
    errors = validate_config(c)
    assert any("base_url" in error for error in errors)


def test_validate_rejects_backslash_authority():
    """urlsplit and requests disagree on a backslash in the authority.

    requests/urllib3 treat the backslash as a path separator, so
    'http://attacker.example\\@127.0.0.1/v1' must not pass as loopback.
    """
    c = load_config(None)
    c["llm"]["base_url"] = r"http://attacker.example\@127.0.0.1/v1"
    errors = validate_config(c)
    assert any("base_url" in error for error in errors)


def test_validate_rejects_unusable_authorities():
    for url in (
        "https://api.example.com:8o80/v1",
        "https://@/v1",
        "https://:443/v1",
        "https://exa mple.com/v1",
    ):
        c = load_config(None)
        c["llm"]["base_url"] = url
        errors = validate_config(c)
        assert any("base_url" in error for error in errors), url


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


def test_validate_requires_a_custom_destination_when_custom_is_active():
    c = load_config(None)
    c["llm"]["provider"] = "custom"
    errors = validate_config(c)
    assert any("custom_base_url" in error for error in errors)
    assert any("custom_model" in error for error in errors)


def test_validate_requires_a_custom_destination_when_custom_is_fallback():
    c = load_config(None)
    c["llm"]["fallback_provider"] = "custom"
    errors = validate_config(c)
    assert any("custom_base_url" in error for error in errors)
    assert any("custom_model" in error for error in errors)


def test_validate_accepts_a_configured_custom_destination():
    c = load_config(None)
    c["llm"].update(
        {
            "provider": "custom",
            "base_url": "https://api.example.com/v1",
            "model": "example-model",
            "custom_base_url": "https://api.example.com/v1",
            "custom_model": "example-model",
        }
    )
    assert validate_config(c) == []


def test_validate_rejects_plaintext_remote_custom_destination():
    c = load_config(None)
    c["llm"]["custom_base_url"] = "http://api.example.com/v1"
    errors = validate_config(c)
    assert any(
        "custom_base_url" in error and "https" in error.lower()
        for error in errors
    )
