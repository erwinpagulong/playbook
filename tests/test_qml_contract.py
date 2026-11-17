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


def test_daemon_process_inherits_llm_key_environment():
    # The daemon reads the LLM key from os.environ; the config stores only the
    # variable's name. A cleared environment strips the exported key and makes
    # predictions permanently unavailable.
    text = (ROOT / "Service.qml").read_text()
    daemon = text.split("id: daemon", 1)[1].split("function reap", 1)[0]
    assert "clearEnvironment: false" in daemon
    assert "clearEnvironment: true" not in daemon
    assert "environment: root.childEnv" in daemon  # PATH/HOME/XDG still overridden


def test_new_views_exist_and_are_management_screens():
    app = (ROOT / "App.qml").read_text()
    assert 'id: "model"' in app and 'id: "apikeys"' in app
    block = app.split("readonly property bool needsReport:", 1)[1].split("}", 1)[0]
    assert '"model"' in block and '"apikeys"' in block


def test_management_views_are_not_gated_on_has_report():
    text = (ROOT / "App.qml").read_text()
    # Coins, Settings and Data & Privacy must open with an empty store.
    gate = text.split("readonly property bool needsReport", 1)[1].split(
        "readonly property string primaryCoin", 1
    )[0]
    for view in ("coins", "settings", "privacy"):
        assert f'case "{view}"' in gate
    loader = text.split("id: contentLoader", 1)[1].split("onStatusChanged", 1)[0]
    assert "viewGateOpen" in loader
    assert "hasReport" not in loader  # the Loader itself is not gated on a report
    # The onboarding placeholder is suppressed while a management view is open.
    onboarding = text.split("// Onboarding:", 1)[1].split("// The views.", 1)[0]
    assert "root.needsReport" in onboarding


def test_query_watchdog_clears_callback_and_pumps_queue():
    text = (ROOT / "App.qml").read_text()
    watchdog = text.split("interval: 15000", 1)[1].split("onRunningChanged", 1)[0]
    block = watchdog.split("if (queryProc.running)", 1)[1].split(
        "if (mutateProc.running)", 1
    )[0]
    assert "root.queryCallback = null" in block
    assert "pumpQueries" in block


def test_app_qml_loads_sidebar_by_file_url():
    text = (ROOT / "App.qml").read_text()
    assert 'source: "components/Sidebar.qml"' in text
    assert "Sidebar {" not in text


def test_data_privacy_key_wording_is_accurate():
    text = (ROOT / "views" / "DataPrivacy.qml").read_text()
    # The key IS transmitted in the Authorization header; what is true is that
    # it is never stored in config/reports/logs.
    assert "Never sent: the API key" not in text
    assert "Authorization header" in text
    assert "never stored" in text.lower()
