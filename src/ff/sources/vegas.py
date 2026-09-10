"""Vegas lines and implied team totals from ESPN's public scoreboard."""
from __future__ import annotations

import requests

from ..cache import HOUR, cached_json

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"


def _fetch(params: dict) -> dict:
    r = requests.get(URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def scoreboard(week: int | None = None, force: bool = False) -> dict:
    params = {"week": week} if week else {}
    return cached_json(
        f"espn_scoreboard_w{week or 'cur'}", HOUR,
        lambda: _fetch(params),
        force,
    )


def implied_totals(week: int | None = None, force: bool = False) -> dict[str, dict]:
    """team abbrev -> {opp, home, spread (negative = favored), total, implied, kickoff, venue, indoor}."""
    out = {}
    for ev in scoreboard(week, force).get("events", []):
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = teams["home"], teams["away"]
        h, a = home["team"]["abbreviation"], away["team"]["abbreviation"]
        odds = (comp.get("odds") or [{}])[0]
        total = odds.get("overUnder")
        spread = odds.get("spread")  # home spread; negative = home favored
        venue = comp.get("venue", {})
        indoor = bool(venue.get("indoor", False))
        base = {"total": total, "kickoff": ev.get("date"), "venue": venue.get("fullName"), "indoor": indoor, "state": ev.get("status", {}).get("type", {}).get("state")}
        if total is not None and spread is not None:
            imp_h = total / 2 - spread / 2
            imp_a = total / 2 + spread / 2
        else:
            imp_h = imp_a = None
        out[h] = {**base, "opp": a, "home": True, "spread": spread, "implied": imp_h}
        out[a] = {**base, "opp": h, "home": False, "spread": -spread if spread is not None else None, "implied": imp_a}
    return out
