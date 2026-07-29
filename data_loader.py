import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def _load_groups(filename: str) -> dict[str, list[tuple[str, int]]]:
    path = BASE_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {group: [tuple(pair) for pair in entries] for group, entries in raw.items()}

JOURNEYS = _load_groups("journeys.json")
