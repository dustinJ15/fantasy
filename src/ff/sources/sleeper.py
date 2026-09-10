"""Sleeper public API: player dump (injury designations, IDs) and trending adds/drops."""
from __future__ import annotations

import requests

from ..cache import DAY, HOUR, cached_json

BASE = "https://api.sleeper.app/v1"
UA = {"User-Agent": "ff-comanager/0.1"}


def players(force: bool = False) -> dict[str, dict]:
    return cached_json("sleeper_players", DAY, lambda: requests.get(f"{BASE}/players/nfl", headers=UA, timeout=120).json(), force)


def trending(kind: str = "add", hours: int = 24, limit: int = 50, force: bool = False) -> list[dict]:
    return cached_json(
        f"sleeper_trending_{kind}_{hours}", HOUR,
        lambda: requests.get(f"{BASE}/players/nfl/trending/{kind}", params={"lookback_hours": hours, "limit": limit}, headers=UA, timeout=30).json(),
        force,
    )


def state(force: bool = False) -> dict:
    return cached_json("sleeper_state", HOUR, lambda: requests.get(f"{BASE}/state/nfl", headers=UA, timeout=30).json(), force)


def injury_table(force: bool = False) -> dict[str, dict]:
    """espn_id (str) -> {status, body_part, notes, depth} for players with any injury flag."""
    out = {}
    for pid, p in players(force).items():
        eid = p.get("espn_id")
        if eid is None:
            continue
        out[str(eid)] = {
            "sleeper_id": pid,
            "name": p.get("full_name"),
            "status": p.get("injury_status"),
            "roster_status": p.get("status"),
            "body_part": p.get("injury_body_part"),
            "notes": p.get("injury_notes"),
            "depth": p.get("depth_chart_order"),
            "gsis_id": p.get("gsis_id"),
        }
    return out


def projections(season: int, week: int, force: bool = False) -> dict[str, dict]:
    """Sleeper (Rotowire) weekly projections keyed by sleeper_id (and DEF:<team> for defenses)."""
    def fetch():
        r = requests.get(f"{BASE.replace('/v1','')}/projections/nfl/{season}/{week}",
                         params={"season_type": "regular", "position[]": ["QB", "RB", "WR", "TE", "K", "DEF"]},
                         headers=UA, timeout=60)
        r.raise_for_status()
        return r.json()
    rows = cached_json(f"sleeper_proj_{season}_{week}", 6 * HOUR, fetch, force)
    pl = players()
    out = {}
    for row in rows:
        st = row.get("stats") or {}
        if not st.get("pts_ppr") and not st.get("pts_std"):
            continue
        p = pl.get(row["player_id"]) or {}
        key = f"DEF:{row.get('team')}" if p.get("position") == "DEF" or row["player_id"] == row.get("team") else str(row["player_id"])
        out[key] = {"pts_ppr": st.get("pts_ppr"), "pts_half_ppr": st.get("pts_half_ppr"), "pts_std": st.get("pts_std"),
                    "opp": row.get("opponent"), "team": row.get("team")}
    return out
