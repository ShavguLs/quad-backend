"""Regression fixture metadata utilities."""
import json
from pathlib import Path
from typing import Any

METADATA_DIR = Path(__file__).parent


def load_metadata(fixture_id: str) -> dict[str, Any]:
    """Load metadata for a specific fixture."""
    path = METADATA_DIR / f"{fixture_id}.json"
    with open(path) as f:
        return json.load(f)


def list_fixtures(category: str | None = None) -> list[str]:
    """List all fixture IDs, optionally filtered by category."""
    fixtures = []
    for path in METADATA_DIR.glob("*.json"):
        if path.name == "__init__.json":
            continue
        metadata = load_metadata(path.stem)
        if category is None or metadata.get("category") == category:
            fixtures.append(path.stem)
    return fixtures


def get_critical_fixtures() -> list[str]:
    """Return list of critical priority fixture IDs."""
    return [
        fid for fid in list_fixtures()
        if load_metadata(fid).get("priority") == "critical"
    ]
