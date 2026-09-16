"""Tiny disk cache: JSON/bytes blobs with TTL, keyed by name."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import CACHE_DIR

CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _path(key: str, ext: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    return CACHE_DIR / f"{safe}.{ext}"


def age_seconds(key: str, ext: str = "json") -> float | None:
    p = _path(key, ext)
    return time.time() - p.stat().st_mtime if p.exists() else None


def cached_json(key: str, ttl: float, fetch: Callable[[], Any], force: bool = False) -> Any:
    p = _path(key, "json")
    age = age_seconds(key)
    if not force and age is not None and age < ttl:
        return json.loads(p.read_text())
    data = fetch()
    p.write_text(json.dumps(data, default=str))
    return data


def cached_bytes(key: str, ttl: float, fetch: Callable[[], bytes], ext: str = "bin", force: bool = False) -> Path:
    """Fetch bytes to a cache file and return its path (for CSV/parquet readers)."""
    p = _path(key, ext)
    age = age_seconds(key, ext)
    if force or age is None or age >= ttl:
        p.write_bytes(fetch())
    return p


def freshness() -> dict[str, float]:
    """name -> age in seconds for everything in the cache."""
    return {p.name: time.time() - p.stat().st_mtime for p in sorted(CACHE_DIR.iterdir()) if p.is_file()}


HOUR = 3600.0
DAY = 24 * HOUR
