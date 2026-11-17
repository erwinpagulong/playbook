import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_user_config(tmp_path, monkeypatch):
    """Never read the real ~/.config/crypto-playbook/config.json.

    Several tests call ``load_config(None)`` expecting shipped defaults; on a
    machine with a personalized config that leaks in (e.g. a different active
    provider), breaking them. Point XDG_CONFIG_HOME at this test's tmp dir so
    every test sees a clean default config. (test_daemon's own xdg_isolation
    fixture sets the same path for its subprocess/CLI tests.)
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def load_manifest() -> dict:
    return json.loads((REPO_ROOT / "manifest.json").read_text(encoding="utf-8"))
