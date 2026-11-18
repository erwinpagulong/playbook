"""Installer behavior when the bundled script runs from its installed folder.

Marketplace installs clone the repository into the plugin directory and ask
the user to run that copy of install.sh. Source and destination are then the
same path: setup must not delete the files it is about to copy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from tests.conftest import REPO_ROOT

FAKE_PYTHON = """#!/bin/sh
# Stub just enough of `python3 -m venv` for the installer's file operations.
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  target="$4"
  mkdir -p "$target/bin"
  for name in python pip; do
    printf '#!/bin/sh\\nexit 0\\n' > "$target/bin/$name"
    chmod 755 "$target/bin/$name"
  done
fi
exit 0
"""

FILES = ("manifest.json", "App.qml", "BarWidget.qml", "Service.qml", "requirements.txt")
DIRS = ("views", "components", "engine", "samples")


def make_checkout(path: Path) -> None:
    path.mkdir(parents=True)
    shutil.copy(REPO_ROOT / "install.sh", path / "install.sh")
    for name in FILES:
        (path / name).write_text("{}", encoding="utf-8")
    for name in DIRS:
        (path / name).mkdir()


def run_installer(script: Path, plugin: Path, stub_dir: Path, cwd: Path):
    env = dict(os.environ)
    env["CRYPTOPLAYBOOK_PLUGIN_DIR"] = str(plugin)
    env["PATH"] = str(stub_dir) + os.pathsep + env["PATH"]
    return subprocess.run(
        [str(script)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def fake_python_dir(tmp_path: Path) -> Path:
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    python = stub_dir / "python3"
    python.write_text(FAKE_PYTHON, encoding="utf-8")
    python.chmod(0o755)
    return stub_dir


def test_installer_run_in_place_preserves_existing_files(tmp_path):
    plugin = tmp_path / "plugin"
    make_checkout(plugin)
    (plugin / "App.qml").write_text("local app edit\n", encoding="utf-8")
    (plugin / "views" / "Local.qml").write_text("local view edit\n", encoding="utf-8")

    result = run_installer(plugin / "install.sh", plugin, fake_python_dir(tmp_path), plugin)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (plugin / "App.qml").read_text(encoding="utf-8") == "local app edit\n"
    assert (plugin / "views" / "Local.qml").read_text(encoding="utf-8") == "local view edit\n"
    assert (plugin / "bin" / "playbook").is_file()
    assert (plugin / "bin" / "playbookd").is_file()


def test_installer_from_separate_checkout_still_copies_files(tmp_path):
    checkout = tmp_path / "checkout"
    plugin = tmp_path / "installed"
    make_checkout(checkout)
    (checkout / "views" / "Shipped.qml").write_text("shipped\n", encoding="utf-8")

    result = run_installer(checkout / "install.sh", plugin, fake_python_dir(tmp_path), checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (plugin / "App.qml").exists()
    assert (plugin / "views" / "Shipped.qml").read_text(encoding="utf-8") == "shipped\n"
    assert (plugin / "bin" / "playbook").is_file()
