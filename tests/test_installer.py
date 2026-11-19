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

# Records the pip command line so tests can assert how dependencies are
# installed, without actually installing anything.
FAILING_PIP_PYTHON = """#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  target="$4"
  mkdir -p "$target/bin"
  cat > "$target/bin/python" <<'PYEOF'
#!/bin/sh
exit 0
PYEOF
  cat > "$target/bin/pip" <<'PIPEOF'
#!/bin/sh
printf 'simulated pip failure\\n' >&2
exit 1
PIPEOF
  chmod 755 "$target/bin/python" "$target/bin/pip"
fi
exit 0
"""

LOGGING_PYTHON = """#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  target="$4"
  mkdir -p "$target/bin"
  cat > "$target/bin/python" <<'PYEOF'
#!/bin/sh
exit 0
PYEOF
  cat > "$target/bin/pip" <<'PIPEOF'
#!/bin/sh
printf '%s\\n' "$*" >> "${PIP_LOG:-/dev/null}"
exit 0
PIPEOF
  chmod 755 "$target/bin/python" "$target/bin/pip"
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


def run_installer(script: Path, plugin: Path, stub_dir: Path, cwd: Path, extra_env=None):
    env = dict(os.environ)
    env["CRYPTOPLAYBOOK_PLUGIN_DIR"] = str(plugin)
    env["PATH"] = str(stub_dir) + os.pathsep + env["PATH"]
    env.update(extra_env or {})
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


def failing_pip_dir(tmp_path: Path) -> Path:
    stub_dir = tmp_path / "failpip"
    stub_dir.mkdir()
    python = stub_dir / "python3"
    python.write_text(FAILING_PIP_PYTHON, encoding="utf-8")
    python.chmod(0o755)
    return stub_dir


def logging_python_dir(tmp_path: Path) -> Path:
    stub_dir = tmp_path / "logstub"
    stub_dir.mkdir()
    python = stub_dir / "python3"
    python.write_text(LOGGING_PYTHON, encoding="utf-8")
    python.chmod(0o755)
    return stub_dir


def failing_copy_dir(tmp_path: Path, fail_on: Path) -> Path:
    """A stub PATH with python3 and a cp that fails on exactly one source."""
    stub_dir = fake_python_dir(tmp_path)
    cp = stub_dir / "cp"
    cp.write_text(
        "#!/bin/sh\n"
        'for arg in "$@"; do\n'
        f'  if [ "$arg" = "{fail_on}" ]; then\n'
        "    printf 'simulated copy failure\\n' >&2\n"
        "    exit 28\n"
        "  fi\n"
        "done\n"
        'exec /bin/cp "$@"\n',
        encoding="utf-8",
    )
    cp.chmod(0o755)
    return stub_dir


def failing_move_dir(tmp_path: Path) -> Path:
    """A stub PATH whose mv fails on one staged file during the swap loop."""
    stub_dir = fake_python_dir(tmp_path)
    mv = stub_dir / "mv"
    mv.write_text(
        "#!/bin/sh\n"
        'for arg in "$@"; do\n'
        "  case \"$arg\" in\n"
        "    */.cryptoplaybook-stage.*/requirements.txt)\n"
        "      printf 'simulated swap failure\\n' >&2\n"
        "      exit 1\n"
        "      ;;\n"
        "  esac\n"
        "done\n"
        'exec /bin/mv "$@"\n',
        encoding="utf-8",
    )
    mv.chmod(0o755)
    return stub_dir


def assert_no_temp_leftovers(tmp_path: Path) -> None:
    assert list(tmp_path.glob(".cryptoplaybook-*")) == []


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


def test_separate_checkout_failed_copy_preserves_previous_installation(tmp_path):
    """A copy that fails mid-install must not destroy the installed plugin."""
    checkout = tmp_path / "checkout"
    plugin = tmp_path / "installed"
    make_checkout(checkout)
    make_checkout(plugin)
    (plugin / "App.qml").write_text("local app edit\n", encoding="utf-8")
    (plugin / "views" / "Local.qml").write_text("local view edit\n", encoding="utf-8")

    stub_dir = failing_copy_dir(tmp_path, checkout / "requirements.txt")

    result = run_installer(checkout / "install.sh", plugin, stub_dir, checkout)
    assert result.returncode != 0, result.stdout + result.stderr
    assert (plugin / "App.qml").read_text(encoding="utf-8") == "local app edit\n"
    assert (plugin / "views" / "Local.qml").read_text(encoding="utf-8") == "local view edit\n"
    assert (plugin / "manifest.json").is_file()
    assert_no_temp_leftovers(tmp_path)


def test_separate_checkout_failed_swap_restores_previous_installation(tmp_path):
    """A failure during the mv swap (old paths already in backup) restores them."""
    checkout = tmp_path / "checkout"
    plugin = tmp_path / "installed"
    make_checkout(checkout)
    make_checkout(plugin)
    (plugin / "App.qml").write_text("local app edit\n", encoding="utf-8")
    (plugin / "views" / "Local.qml").write_text("local view edit\n", encoding="utf-8")

    result = run_installer(checkout / "install.sh", plugin, failing_move_dir(tmp_path), checkout)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "simulated swap failure" in result.stderr
    assert (plugin / "App.qml").read_text(encoding="utf-8") == "local app edit\n"
    assert (plugin / "views" / "Local.qml").read_text(encoding="utf-8") == "local view edit\n"
    assert (plugin / "manifest.json").is_file()
    assert_no_temp_leftovers(tmp_path)


def test_separate_checkout_success_preserves_unmanaged_files(tmp_path):
    """Staging replacements must leave the venv and user files untouched."""
    checkout = tmp_path / "checkout"
    plugin = tmp_path / "installed"
    make_checkout(checkout)
    make_checkout(plugin)
    # A valid venv (real interpreter binaries, no symlinks) is reused as-is.
    venv_bin = plugin / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    for name in ("python", "pip"):
        exe = venv_bin / name
        exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        exe.chmod(0o755)
    (plugin / ".venv" / "marker").write_text("keep me\n", encoding="utf-8")
    (plugin / "user-note.txt").write_text("mine\n", encoding="utf-8")

    result = run_installer(checkout / "install.sh", plugin, fake_python_dir(tmp_path), checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (plugin / ".venv" / "marker").read_text(encoding="utf-8") == "keep me\n"
    assert (plugin / "user-note.txt").read_text(encoding="utf-8") == "mine\n"
    assert_no_temp_leftovers(tmp_path)


def test_separate_checkout_failed_setup_restores_previous_installation(tmp_path):
    """A failure after the swap (wrappers/venv/pip) must not leave a half-updated plugin."""
    checkout = tmp_path / "checkout"
    plugin = tmp_path / "installed"
    make_checkout(checkout)
    make_checkout(plugin)
    (plugin / "App.qml").write_text("local app edit\n", encoding="utf-8")
    (plugin / "bin").mkdir()
    (plugin / "bin" / "playbook").write_text("old wrapper\n", encoding="utf-8")
    # An invalid venv forces a rebuild, so this marker must survive a failure.
    (plugin / ".venv").mkdir()
    (plugin / ".venv" / "marker").write_text("old venv marker\n", encoding="utf-8")
    (checkout / "views" / "Shipped.qml").write_text("shipped\n", encoding="utf-8")

    result = run_installer(checkout / "install.sh", plugin, failing_pip_dir(tmp_path), checkout)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "simulated pip failure" in result.stderr
    assert (plugin / "App.qml").read_text(encoding="utf-8") == "local app edit\n"
    assert (plugin / "bin" / "playbook").read_text(encoding="utf-8") == "old wrapper\n"
    assert (plugin / ".venv" / "marker").read_text(encoding="utf-8") == "old venv marker\n"
    assert not (plugin / "views" / "Shipped.qml").exists()
    assert_no_temp_leftovers(tmp_path)


def test_installer_enforces_hashed_requirements(tmp_path):
    """The installer must give pip the hash-enforcing flag and the lock file."""
    checkout = tmp_path / "checkout"
    plugin = tmp_path / "installed"
    make_checkout(checkout)
    pip_log = tmp_path / "pip-args.log"

    result = run_installer(
        checkout / "install.sh",
        plugin,
        logging_python_dir(tmp_path),
        checkout,
        {"PIP_LOG": str(pip_log)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    args = pip_log.read_text(encoding="utf-8")
    assert "--require-hashes" in args, args
    assert f"-r {plugin}/requirements.txt" in args, args
