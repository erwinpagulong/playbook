import re
from datetime import datetime
from pathlib import Path

from engine.report import (
    list_reports,
    load_report,
    new_report,
    render_markdown,
    save_report,
    seed_samples,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_new_report_shape():
    r = new_report("BTC/USDT", {"sources": []}, {}, {"positions": [], "key_levels": {}})
    assert r["coin"] == "BTC/USDT"
    assert r["schema_version"] == 1
    assert r["prediction"]["available"] is False
    assert "id" in r and "generated_at" in r
    assert r["sample"] is False
    assert "markdown" in r and "risk_rules" in r
    assert r["snapshot"] == {"sources": []}
    assert r["levels"] == {"positions": [], "key_levels": {}}


def test_new_report_id_is_microsecond_utc_timestamp():
    """Controller ruling: microsecond ids so concurrent runs can't collide.

    e.g. `BTC-USDT-20261116T130000123456Z`; `generated_at` stays a normal
    ISO-8601 UTC string.
    """
    r = new_report("BTC/USDT", {}, {}, {})
    assert re.fullmatch(r"BTC-USDT-\d{8}T\d{12}Z", r["id"]), r["id"]
    parsed = datetime.fromisoformat(r["generated_at"])
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == 0  # UTC


def test_rapid_report_ids_never_collide():
    """Four back-to-back generations (Task 8) must produce four distinct ids."""
    ids = {new_report("BTC/USDT", {}, {}, {})["id"] for _ in range(4)}
    assert len(ids) == 4, ids


def test_save_list_load_round_trip(tmp_path):
    r = new_report("BTC/USDT", {}, {}, {})
    p = save_report(tmp_path, r)
    assert p.exists()
    assert load_report(tmp_path, r["id"])["id"] == r["id"]
    assert list_reports(tmp_path, "BTC/USDT")[0]["id"] == r["id"]


def test_save_report_writes_json_and_markdown(tmp_path):
    r = new_report("BTC/USDT", {}, {}, {})
    p = save_report(tmp_path, r)
    assert p == tmp_path / "reports" / f"{r['id']}.json"
    md_path = tmp_path / "reports" / f"{r['id']}.md"
    assert md_path.exists()
    assert md_path.read_text(encoding="utf-8") == render_markdown(r)
    # the stored markdown matches the rendered report too
    assert load_report(tmp_path, r["id"])["markdown"] == render_markdown(r)


def test_list_reports_sorts_newest_first(tmp_path):
    older = new_report("BTC/USDT", {}, {}, {})
    older["generated_at"] = "2026-01-01T00:00:00+00:00"
    newer = new_report("ETH/USDT", {}, {}, {})
    newer["generated_at"] = "2026-06-01T00:00:00+00:00"
    save_report(tmp_path, older)
    save_report(tmp_path, newer)
    assert [r["id"] for r in list_reports(tmp_path)] == [newer["id"], older["id"]]
    # coin filter
    assert [r["id"] for r in list_reports(tmp_path, "ETH/USDT")] == [newer["id"]]
    assert list_reports(tmp_path, "SOL/USDT") == []


def test_list_reports_missing_dir_is_empty(tmp_path):
    assert list_reports(tmp_path) == []


def test_markdown_has_required_sections():
    r = new_report("BTC/USDT", {}, {}, {})
    md = render_markdown(r)
    for heading in ("Market snapshot", "Indicator dashboard", "ENTRY & EXIT", "Prediction", "Risk rules"):
        assert heading.lower() in md.lower()


def test_markdown_renders_position_and_scenario_tables():
    levels = {
        "key_levels": {"support": [63900.0], "resistance": [64900.0]},
        "positions": [
            {
                "timeframe": "15m",
                "direction": "LONG",
                "label": "bounce",
                "entry": 64000.0,
                "tp1": 64500.0,
                "tp2": 65000.0,
                "stop": 63500.0,
                "rr": 2.0,
                "zone": "64000-64500",
            }
        ],
    }
    r = new_report("BTC/USDT", {"sources": [{"source": "Binance", "price": 64052.84, "change_pct": -2.13}]}, {}, levels)
    r["prediction"] = {
        "available": True,
        "scenarios": [
            {"name": "bounce", "probability": 0.4, "target": 65800},
            {"name": "breakdown", "probability": 0.6, "target": 62006},
        ],
    }
    md = render_markdown(r)
    # position row and scenario rows render as table data
    assert "64000" in md and "63500" in md and "64500" in md
    assert "bounce" in md and "breakdown" in md and "65800" in md
    assert "Binance" in md and "64052.84" in md
    # prediction availability flips the section text
    assert "not available" not in md.lower()


def test_render_markdown_returns_source_markdown_verbatim():
    r = new_report("BTC/USDT", {}, {}, {})
    r["source_markdown"] = "# Custom\n\ntext with **markdown**\n"
    assert render_markdown(r) == "# Custom\n\ntext with **markdown**\n"


def test_markdown_prediction_surfaces_answering_provider():
    r = new_report("BTC/USDT", {}, {}, {})
    r["prediction"] = {
        "available": True,
        "provider": "deepseek",
        "model": "deepseek-chat",
        "fallback_used": True,
        "scenarios": [{"name": "up", "probability": 100}],
    }
    md = render_markdown(r)
    assert "Answered by deepseek / deepseek-chat (fallback)" in md

    r["prediction"] = {
        "available": False,
        "reason": "prediction unavailable",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "fallback_used": False,
    }
    md = render_markdown(r)
    assert "Answered by openai / gpt-4o-mini" in md
    assert "(fallback)" not in md


def test_markdown_prediction_has_no_answered_line_without_provider():
    r = new_report("BTC/USDT", {}, {}, {})
    r["prediction"] = {"available": True, "model": "gpt-4o-mini"}
    assert "Answered by" not in render_markdown(r)


def test_markdown_prediction_reason_is_emitted_when_unavailable():
    r = new_report("BTC/USDT", {}, {}, {})
    r["prediction"] = {
        "available": False,
        "reason": "prediction unavailable: API key is missing or empty",
    }
    md = render_markdown(r)
    assert "not available" in md.lower()
    assert "API key is missing or empty" in md


def test_seed_samples_only_when_empty(tmp_path):
    seed_samples(tmp_path)
    assert len(list_reports(tmp_path)) == 2
    assert all(r["sample"] for r in list_reports(tmp_path))
    seed_samples(tmp_path)
    assert len(list_reports(tmp_path)) == 2


def test_seed_samples_content_matches_sample_files(tmp_path):
    seed_samples(tmp_path)
    by_id = {r["id"]: r for r in list_reports(tmp_path)}
    assert set(by_id) == {"sample-playbook-20261116", "sample-prediction-20261116"}
    pairs = {
        "sample-playbook-20261116": "BTC_USDT_PLAYBOOK_2026-11-16.md",
        "sample-prediction-20261116": "BTC_USDT_PREDICTION-2026-11-16.md",
    }
    for report_id, filename in pairs.items():
        report = by_id[report_id]
        expected = (REPO_ROOT / "samples" / filename).read_text(encoding="utf-8")
        assert report["coin"] == "BTC/USDT"
        assert report["generated_at"].startswith("2026-11-16")
        assert report["source_markdown"] == expected
        # rendering a seeded sample returns its source verbatim
        assert render_markdown(report) == expected
        # and the saved .md file on disk matches too
        saved = (tmp_path / "reports" / f"{report_id}.md").read_text(encoding="utf-8")
        assert saved == expected
