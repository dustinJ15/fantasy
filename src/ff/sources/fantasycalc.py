"""FantasyCalc trade values (Elo-derived from real trades)."""
from __future__ import annotations

import requests

from ..cache import DAY, cached_json


def values(num_teams: int = 12, ppr: float = 1.0, num_qbs: int = 1, force: bool = False) -> list[dict]:
    ppr_flag = 1 if ppr >= 0.75 else (0.5 if ppr > 0 else 0)
    key = f"fantasycalc_{num_teams}_{ppr_flag}_{num_qbs}"

    def fetch():
        r = requests.get(
            "https://api.fantasycalc.com/values/current",
            params={"isDynasty": "false", "numQbs": num_qbs, "numTeams": num_teams, "ppr": ppr_flag},
            timeout=60, headers={"User-Agent": "ff-comanager/0.1"},
        )
        r.raise_for_status()
        return r.json()

    return cached_json(key, DAY, fetch, force)


def by_espn_id(**kw) -> dict[str, dict]:
    out = {}
    for row in values(**kw):
        p = row.get("player", {})
        eid = p.get("espnId")
        if eid:
            out[str(eid)] = {
                "name": p.get("name"), "pos": p.get("position"), "team": p.get("maybeTeam"),
                "value": row.get("value"), "redraft_value": row.get("redraftValue"),
                "overall_rank": row.get("overallRank"), "pos_rank": row.get("positionRank"),
                "trend_30d": row.get("trend30Day"), "sleeper_id": p.get("sleeperId"),
            }
    return out
