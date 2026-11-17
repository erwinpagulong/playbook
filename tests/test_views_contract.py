from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_renders_core_cards():
    text = (ROOT / "views/Dashboard.qml").read_text()
    for label in ("ENTRY & EXIT", "INDICATOR DASHBOARD", "PREDICTION", "RECENT REPORTS"):
        assert label in text


def test_api_keys_view_uses_key_commands():
    text = (ROOT / "views/ApiKeys.qml").read_text()
    assert 'set-key' in text and 'clear-key' in text and 'key_hint' in text


def test_model_view_has_active_and_fallback():
    text = (ROOT / "views/Model.qml").read_text()
    assert 'fallback_provider' in text and 'provider' in text


def test_no_full_key_literal_in_settings():
    text = (ROOT / "views/Settings.qml").read_text()
    assert "THE API KEY" not in text


def test_settings_exposes_coin_interval_model():
    text = (ROOT / "views/Settings.qml").read_text()
    for key in ("coins", "interval_minutes", "model"):
        assert key in text


def test_data_privacy_has_export_and_delete():
    text = (ROOT / "views/DataPrivacy.qml").read_text()
    assert "export" in text.lower() and "delete" in text.lower()


def test_onboarding_state_exists():
    text = (ROOT / "App.qml").read_text()
    assert "no key" in text.lower() or "onboarding" in text.lower()


def test_playbooks_source_fallback_ignores_default_risk_rules():
    text = (ROOT / "views/Playbooks.qml").read_text()
    # risk_rules is always populated (the generator seeds DEFAULT_RISK_RULES),
    # so it must not count as structured content — otherwise the plain-text
    # source document never renders for seeded reports.
    structured = next(
        line for line in text.splitlines() if "readonly property bool structured:" in line
    )
    assert "riskRules" not in structured
    assert "positions.length > 0" in structured and "sources.length > 0" in structured
    # The plain-text fallback itself is still wired up.
    assert "sourceDoc" in text and "hasSourceFallback" in text


def test_app_loader_surfaces_view_load_errors():
    text = (ROOT / "App.qml").read_text()
    # A failed view load must reach the user, not a blank panel.
    assert "Loader.Error" in text
    assert "viewFailed" in text
    assert "Retry" in text
