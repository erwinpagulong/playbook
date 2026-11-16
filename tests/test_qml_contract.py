import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML_FILES = sorted(ROOT.glob("**/*.qml"))

# Hex color literals in QML: exactly 3, 4, 6 or 8 hex digits after '#',
# not followed by another hex digit. Exact lengths only — 5, 7 and longer
# runs are not color literals (the lookahead blocks them).
HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-fA-F])")


def test_no_literal_hex_colors_in_qml():
    for p in QML_FILES:
        text = p.read_text()
        assert not HEX_COLOR_RE.search(text), p


def test_hex_color_regex_catches_short_and_alpha_forms():
    # 3-, 4- and 8-digit forms the old {6}-only gate missed, plus 6-digit.
    for literal in ("#abc", "#ABC", "#Ab3", "#1234", "#Ab3F", "#112233", "#11223344"):
        assert HEX_COLOR_RE.search(literal), literal
    # Not literals, or not exactly one of the four lengths.
    for text in ("#1", "#12", "#", "#xyz", "#12345", "#1234567", "#1122334", "#1122334455"):
        assert not HEX_COLOR_RE.search(text), text
    # Inside surrounding prose or code.
    assert HEX_COLOR_RE.search("color: #abc;")
    assert HEX_COLOR_RE.search('property color x: "#11223344"')
    assert not HEX_COLOR_RE.search("see the notes in #1 and #12")
    assert HEX_COLOR_RE.search("#11223344.")


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
