"""Read-only probe for the four things docs/plans/scanner-replay.md cannot know without ESPN cookies (TODO D12 step 1).

    uv run python scripts/probe_replay_pool.py --week <a past week> [--league L1] [--size 1000]

For one league and one past week it pulls the week's box scores (the rosters as they stood, `projected_points` as of
kickoff) and ESPN's player list for that `scoringPeriodId` (`kona_player_info`, the view `espn.free_agent_rows` reads),
and prints:
  1. whether the FREEAGENT/WAIVERS pool for a past period is the week's or today's: any player in it who sat on a
     week-w box-score roster says today's (`pool_verdict`);
  2. whether the list's per-period `projected_points` for that period equals the box score's pre-kickoff number
     (`projection_agreement`);
  3. how deep an ownership-sorted pull must go to hold every player on any week-w roster, and how many it misses at
     300, 600 and 1000 (`coverage`);
  4. whether the past-period payload's `injuryStatus`, `percentOwned` and `onTeamId` are today's: the count of
     players on which the two payloads differ, how many rostered-that-week players the past payload puts on a team
     other than the box score's and whether that is today's team (`payload_drift`), then a few rostered players side
     by side.
The answers go under "What the probe found" in the plan. The pure functions have no ESPN in them and are tested in
`tests/test_probe_replay_pool.py`; `main` is the only thing that talks to ESPN.
"""
from __future__ import annotations

import json
import sys
from typing import Any

SIZES = (300, 600, 1000)
PROJ_TOL = 0.01


# ---------- the pure half ----------

def period_stats(entry: dict, season: int) -> dict[int, dict[str, float]]:
    """{period: {"proj": x, "actual": y}} from one `kona_player_info` entry: the per-period stat rows of `season`
    (`statSplitTypeId` 1), `statSourceId` 1 the projection and 0 the actual, `appliedTotal` the points."""
    out: dict[int, dict[str, float]] = {}
    for st in (entry.get("player") or {}).get("stats") or []:
        if int(st.get("statSplitTypeId", -1)) != 1 or int(st.get("seasonId", season)) != season:
            continue
        per = int(st.get("scoringPeriodId", 0))
        key = "proj" if int(st.get("statSourceId", -1)) == 1 else "actual" if int(st.get("statSourceId", -1)) == 0 else None
        if per and key:
            out.setdefault(per, {})[key] = float(st.get("appliedTotal") or 0.0)
    return out


def pool_verdict(pool_ids: set[int], rostered_ids: set[int]) -> dict[str, Any]:
    """Question 1. A past-period pool that holds a player who was on a roster that week is today's pool, not the
    week's; one that holds none of them may be the week's (or every such player is still rostered today)."""
    overlap = pool_ids & rostered_ids
    return {"n_pool": len(pool_ids), "n_rostered_that_week": len(overlap),
            "verdict": "today's pool (rostered-that-week players are in it)" if overlap
            else "consistent with the week's pool (no rostered-that-week player in it); not proof"}


def projection_agreement(universe: dict[int, dict[int, dict[str, float]]], box_proj: dict[int, float], week: int,
                         tol: float = PROJ_TOL) -> dict[str, Any]:
    """Question 2. `universe` is espn_id -> `period_stats`; `box_proj` is espn_id -> the box score's `projected_points`
    for `week`. Counts the players both carry, how many agree within `tol`, and the largest gap."""
    diffs = []
    for pid, bp in box_proj.items():
        up = (universe.get(pid) or {}).get(week, {}).get("proj")
        if up is not None:
            diffs.append(abs(up - float(bp)))
    return {"n": len(diffs), "n_equal": sum(d <= tol for d in diffs), "max_diff": round(max(diffs), 2) if diffs else None,
            "missing": len(box_proj) - len(diffs)}


def coverage(ordered_ids: list[int], rostered_ids: set[int], sizes: tuple[int, ...] = SIZES) -> dict[str, Any]:
    """Question 3. `ordered_ids` is the universe pull in ESPN's ownership order. `depth` is the 1-based rank of the
    deepest rostered player (None when one is past the end); `missing_at` counts rostered players beyond each size."""
    rank = {pid: i + 1 for i, pid in enumerate(ordered_ids)}
    ranks = [rank.get(pid) for pid in rostered_ids]
    beyond = sum(r is None for r in ranks)
    depth = None if beyond else (max(ranks) if ranks else 0)
    return {"n_rostered": len(rostered_ids), "depth": depth, "beyond_pull": beyond,
            "missing_at": {s: sum(r is None or r > s for r in ranks) for s in sizes}}


def payload_drift(past: dict[int, dict], now: dict[int, dict], box_team: dict[int, int]) -> dict[str, Any]:
    """Question 4. `past` and `now` are espn_id -> the `kona_player_info` entry for the past period and the current
    one; `box_team` is espn_id -> the team that held the player in the week-w box scores. Over the players both
    payloads carry: how many `injuryStatus`, `percentOwned` and `onTeamId` differ between the two payloads (zero says
    the past-period payload is today's), and over the rostered ones how many the past payload puts on a team other
    than the box score's (`moved`) and how many of those it puts on today's team (`moved_to_today`: today's, not the
    week's)."""
    both = [pid for pid in past if pid in now]

    def field(e: dict, key: str):
        pl = e.get("player") or {}
        return (pl.get("ownership") or {}).get("percentOwned") if key == "percentOwned" else pl.get(key)

    status_diff = sum(field(past[pid], "injuryStatus") != field(now[pid], "injuryStatus") for pid in both)
    owned_diff = sum(abs(float(field(past[pid], "percentOwned") or 0) - float(field(now[pid], "percentOwned") or 0)) > 0.05
                     for pid in both)
    team_diff = sum(past[pid].get("onTeamId") != now[pid].get("onTeamId") for pid in both)
    moved = [pid for pid, t in box_team.items() if pid in past and int(past[pid].get("onTeamId") or 0) != int(t)]
    moved_to_today = sum(pid in now and past[pid].get("onTeamId") == now[pid].get("onTeamId") for pid in moved)
    return {"n_both": len(both), "status_diff": status_diff, "owned_diff": owned_diff, "team_diff": team_diff,
            "n_rostered": sum(pid in past for pid in box_team), "moved": len(moved), "moved_to_today": moved_to_today,
            "verdict": "today's payload (designation, ownership and team all match the current period's)"
            if not (status_diff or owned_diff or team_diff) else "the past period's payload differs from today's"}


# ---------- the ESPN half ----------

def _players(league, week: int, size: int, statuses: list[str] | None) -> list[dict]:
    """The `kona_player_info` list for `week`, ownership-sorted, `statuses` as ESPN's `filterStatus` (None: everyone)."""
    f: dict[str, Any] = {"filterSlotIds": {"value": []}, "limit": size,
                         "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                         "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"}}
    if statuses:
        f["filterStatus"] = {"value": statuses}
    data = league.espn_request.league_get(params={"view": "kona_player_info", "scoringPeriodId": week},
                                          headers={"x-fantasy-filter": json.dumps({"players": f})})
    return list(data.get("players") or [])


def main(argv: list[str]) -> None:
    from ff.config import env, leagues
    from ff.sources import espn

    only = argv[argv.index("--league") + 1] if "--league" in argv else None
    size = int(argv[argv.index("--size") + 1]) if "--size" in argv else max(SIZES)
    if "--week" not in argv:
        raise SystemExit("--week <a past week> is required")
    week = int(argv[argv.index("--week") + 1])
    season = env().season
    for ref in leagues(only):
        lg = espn.connect(ref, season)
        print(f"\n== {ref.name}: {lg.settings.name}, season {season}, probing week {week} (current week {lg.current_week})")
        rostered: dict[int, float] = {}
        box_team: dict[int, int] = {}
        for b in lg.box_scores(week):
            for side, lineup in (("home", b.home_lineup), ("away", b.away_lineup)):
                team = getattr(b, f"{side}_team")
                tid = int(getattr(team, "team_id", team) or 0)
                for p in lineup:
                    rostered[int(p.playerId)] = float(p.projected_points or 0.0)
                    box_team[int(p.playerId)] = tid
        past = _players(lg, week, size, None)
        past_pool = _players(lg, week, size, ["FREEAGENT", "WAIVERS"])
        now = {int(e["id"]): e for e in _players(lg, lg.current_week, size, None)}
        universe = {int(e["id"]): period_stats(e, season) for e in past}
        print("1. pool:", pool_verdict({int(e["id"]) for e in past_pool}, set(rostered)))
        print("2. projections:", projection_agreement(universe, rostered, week))
        print("3. coverage:", coverage([int(e["id"]) for e in past], set(rostered)))
        print("4. designation and ownership, past-period payload against the current one:",
              payload_drift({int(e["id"]): e for e in past}, now, box_team))
        shown = 0
        for e in past:
            pid = int(e["id"])
            if pid not in rostered or pid not in now or shown >= 8:
                continue
            pp, np_ = e.get("player") or {}, now[pid].get("player") or {}
            print(f"   {pp.get('fullName', pid):24} status {str(pp.get('injuryStatus')):14} now {str(np_.get('injuryStatus')):14} "
                  f"owned {float((pp.get('ownership') or {}).get('percentOwned') or 0):6.1f} now {float((np_.get('ownership') or {}).get('percentOwned') or 0):6.1f} "
                  f"onTeam {e.get('onTeamId')} now {now[pid].get('onTeamId')}")
            shown += 1


if __name__ == "__main__":
    main(sys.argv)
