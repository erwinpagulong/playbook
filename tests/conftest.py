import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_manifest() -> dict:
    return json.loads((REPO_ROOT / "manifest.json").read_text(encoding="utf-8"))
