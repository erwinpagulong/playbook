from tests.conftest import REPO_ROOT, load_manifest


def test_manifest_has_required_keys():
    m = load_manifest()
    assert m["schemaVersion"] == 1
    assert m["id"] == "windong.cryptoplaybook"
    assert not m["id"].startswith("omarchy.")
    assert m["kinds"] == ["bar-widget", "panel", "service"]
    for entry in ("BarWidget.qml", "App.qml", "Service.qml"):
        assert m["entryPoints"][  # key maps to file
            {"BarWidget.qml": "barWidget", "App.qml": "panel", "Service.qml": "service"}[entry]
        ] == entry
        assert (REPO_ROOT / entry).exists()


def test_no_symlinks():
    assert not any(p.is_symlink() for p in REPO_ROOT.rglob("*"))
