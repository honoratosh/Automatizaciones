# module1/request_cache.py

import json
from pathlib import Path

CACHE_FILE = Path("data/request_cache.json")


def _load() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def _save(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def get_request_id(rfc: str, year: int, month: int, direction: str) -> str | None:
    """
    Returns a previously stored id_solicitud, or None if this
    period has never been requested before.
    direction: "emitted" or "received"
    """
    key = f"{rfc}_{year}_{month:02d}_{direction}"
    return _load().get(key)


def save_request_id(rfc: str, year: int, month: int, direction: str, id_solicitud: str):
    """Persist an id_solicitud so we never re-request the same period."""
    key = f"{rfc}_{year}_{month:02d}_{direction}"
    cache = _load()
    cache[key] = id_solicitud
    _save(cache)
