from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_renders_core_cards():
    text = (ROOT / "views/Dashboard.qml").read_text()
    for label in ("ENTRY & EXIT", "INDICATOR DASHBOARD", "PREDICTION", "RECENT REPORTS"):
        assert label in text


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
