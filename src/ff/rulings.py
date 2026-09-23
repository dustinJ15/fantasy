"""Memory for Claude's `skip` rulings on trade rows, so a package Dustin passed on does not come back every morning.

The scan re-derives the same offers daily from the same rosters; the only state it had was ESPN's pending list.
`ff render-email` records each skipped trade row here; `packet.build` drops candidates skipped in the last
`SKIP_DAYS`. The file lives under data/projlog, which the routine already pushes to the `projlog` branch and
`scripts/cloud_setup.sh` restores on the next clone. A rival roster change that makes the package different (a new
`get` set) is a new row and is not skipped.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .config import DATA_DIR

SKIPS_PATH = DATA_DIR / "projlog" / "skipped_trades.json"
SKIP_DAYS = 14


def skip_key(league: str, get: list[str]) -> str:
    return f"{league}|" + "+".join(sorted(get))


def load_skips(path: Path = SKIPS_PATH) -> dict[str, dict]:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def record_skips(packet: dict, reads: dict, path: Path = SKIPS_PATH, today: date | None = None) -> list[str]:
    """Write every `skip` ruling on a trade row into the file; returns the keys added."""
    from .report import apply_reads, todos  # local import: report imports nothing from here, keep it that way
    today = today or date.today()
    skips = load_skips(path)
    added = []
    for lg in packet.get("leagues") or []:
        r = (reads or {}).get(lg["name"]) or {}
        for row in apply_reads(todos(lg), r):
            if row["kind"] != "trade" or row.get("ruling") != "skip":
                continue
            key = skip_key(lg["name"], row.get("get") or [])
            skips[key] = {"date": today.isoformat(), "league": lg["name"], "rival": row.get("rival"),
                          "give": row.get("give") or [], "get": row.get("get") or [], "note": row.get("ruling_note")}
            added.append(key)
    if added:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(skips, indent=1))
    return added


def drop_recently_skipped(cands: list[dict], skips: dict[str, dict], league: str, today: date | None = None,
                          days: int = SKIP_DAYS) -> list[dict]:
    today = today or date.today()
    out = []
    for c in cands:
        s = skips.get(skip_key(league, c.get("get") or []))
        if s:
            try:
                when = date.fromisoformat(s.get("date", ""))
            except ValueError:
                when = today
            if today - when <= timedelta(days=days):
                continue
        out.append(c)
    return out
