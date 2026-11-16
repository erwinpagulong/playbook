import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML_FILES = sorted(ROOT.glob("**/*.qml"))


def test_no_literal_hex_colors_in_qml():
    for p in QML_FILES:
        text = p.read_text()
        assert not re.search(r"#[0-9a-fA-F]{6}\b", text), p


def test_service_owns_daemon():
    text = (ROOT / "Service.qml").read_text()
    assert "bin/playbookd" in text
    assert "onExited" in text and "reap" in text


def test_bar_widget_toggles_shell():
    text = (ROOT / "BarWidget.qml").read_text()
    assert 'shell.toggle("windong.cryptoplaybook"' in text
    assert "windowTitle" not in text  # this is a bar widget, not a standalone window


def test_app_derives_theme_tokens():
    text = (ROOT / "App.qml").read_text()
    for token in ("Color.foreground", "Color.background", "Color.accent", "Color.urgent", "Style.normalBorderColor", "Style.font.family"):
        assert token in text
