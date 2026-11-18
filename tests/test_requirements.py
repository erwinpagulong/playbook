"""The dependency declarations are the artifact pip consumes, so test the
declarations themselves: exact versions, hashes, and a test-only split.
"""

from __future__ import annotations

from tests.conftest import REPO_ROOT


def records(path):
    """Join pip-compile's backslash continuations into one record per package."""
    result = []
    current = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        current = f"{current} {line.lstrip()}".strip() if current else line.lstrip()
        if current.endswith("\\"):
            current = current[:-1].rstrip()
        else:
            result.append(current)
            current = ""
    return result


def names(records):
    return {record.split("==", 1)[0].lower() for record in records}


def test_runtime_lock_is_pinned_and_hashed():
    locked = records(REPO_ROOT / "requirements.txt")
    assert locked, "requirements.txt must not be empty"
    for record in locked:
        assert "==" in record, f"not an exact pin: {record}"
        assert "--hash=sha256:" in record, f"missing hash: {record}"
    assert {"pandas", "numpy", "requests", "yfinance"} <= names(locked)
    assert "pytest" not in names(locked)


def test_test_only_dependency_is_separate():
    assert "pytest" in names(records(REPO_ROOT / "requirements-dev.txt"))
