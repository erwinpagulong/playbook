from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_renders_core_cards():
    text = (ROOT / "views/Dashboard.qml").read_text()
    for label in ("ENTRY & EXIT", "INDICATOR DASHBOARD", "PREDICTION", "RECENT REPORTS"):
        assert label in text


def test_indicator_bb_width_subtracts_row_gaps_in_header_and_delegate():
    """The BB column shares a 7-column Row with 6 gaps of Style.space(8).

    Both the header and the delegate must subtract those 6 gaps, or the BB
    column eats the ATR column's space and ATR is clipped off the card.
    """
    text = (ROOT / "views/Dashboard.qml").read_text()
    bb_widths = [
        line
        for line in text.splitlines()
        if "indicatorCard.width - indicatorCard.pad * 2 - Style.space(40 + 80 + 56 + 72 + 90 + 64)" in line
    ]
    assert len(bb_widths) == 2, "expected BB width in both header and delegate"
    for line in bb_widths:
        assert "Style.space(8) * 6" in line, f"BB width misses the 6 row gaps: {line}"


def test_api_keys_view_uses_key_commands():
    text = (ROOT / "views/ApiKeys.qml").read_text()
    assert 'set-key' in text and 'clear-key' in text and 'key_hint' in text


def test_api_keys_view_never_puts_a_key_in_helper_argv():
    text = (ROOT / "views/ApiKeys.qml").read_text()
    save = text.split("function saveKey", 1)[1].split("function clearKey", 1)[0]
    # The helper argv carries only the provider id; the key is the third
    # argument to run(), which writes it to the helper's stdin instead.
    assert 'run(["set-key", id]' in save
    assert ", key)" in save


def test_app_mutate_process_passes_stdin_without_argv():
    text = (ROOT / "App.qml").read_text()
    pump = text.split("function pumpMutations", 1)[1].split("function showToast", 1)[0]
    assert "pendingStdin" in pump
    assert "stdinEnabled" in pump
    started = text.split("id: mutateProc", 1)[1].split("onExited:", 1)[0]
    assert "write(mutateProc.pendingStdin)" in started


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


def test_predictions_conviction_row_has_explicit_width():
    text = (ROOT / "views" / "Predictions.qml").read_text()
    block = text.split('title: "HIGHEST CONVICTION"', 1)[1].split("// ---- scenarios", 1)[0]
    row = block.split("Row {", 1)[1].strip().splitlines()
    assert row[0].strip() == "width: parent.width"


def test_app_loader_surfaces_view_load_errors():
    text = (ROOT / "App.qml").read_text()
    # A failed view load must reach the user, not a blank panel.
    assert "Loader.Error" in text
    assert "viewFailed" in text
    assert "Retry" in text
