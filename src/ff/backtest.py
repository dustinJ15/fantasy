"""Replay a season through the same code and score it against what happened (TODO D8, ROADMAP 8).

Without this, a model change is a vibe. The replay is one league's season as ESPN archived it, pulled once by
`ff replay-pull` into `data/replay/<season>-<league>.json` (`pull_replay`): every matchup, both rosters as they were
set, ESPN's pre-kickoff projection and the actual for every rostered player, in that league's scoring. Two scorers read
it. `lineup_calibration` is the P(win) question: the number `model/lineup.py` puts on a lineup, applied to the lineups
that actually played, against who actually won (a reliability table, the Brier score), and what the optimizer's
lineup would have scored next to the one the manager set. `trade_hits` is the trade question: every offer of mine
ESPN executed (`rulings.record_outcomes`), the points the players I got scored against the ones I gave, week by week
after the trade, next to the delta the scan promised.

What the archive keeps and what it lost, so the replay is honest about which half of the model it scores:
- `projected_points` per scoring period is the projection ESPN showed before that week's kickoff (statSourceId 1),
  and `points` is the final; that is the forecast and the truth. No Sleeper, no FantasyPros, no Vegas line and no
  forecast for a past week, so the replay's `mu` is ESPN's number alone and the blend is not scored here (the projlog
  does that for the live season, `ff accuracy`).
- Injury designations are the player's today, not the week's, so the replay carries none: everyone sits at the
  `p_zero` floor, except that ESPN projects zero for a player it knew was out, so a zero on a week with a game reads
  as a certain zero (`row_proj`). The sit-risk half of the model (`P_ZERO`, `QUESTIONABLE_BY_WEEKDAY`) is not scored
  by a replay; the projlog's rows carry it.
- The sigma is the house prior (`BASE_SIGMA`, `CV_FLOOR`), exactly what the live lineup uses, so the calibration
  table is a test of that prior: over-confident P(win) (an 80% bin that wins 65%) says the sigma is too small.
- A matchup spread over two scoring periods (a two-week final) is skipped: ESPN's per-period box score carries the
  period's roster but the matchup's running total. `skipped_weeks` names them.
- Version 2 adds `players`, the universe (TODO D12, `docs/plans/scanner-replay.md`): every player in ESPN's
  ownership-sorted list, with the preseason season total and his projection and actual for every period, so the
  scanner replay can build the week-w wire (the universe minus the week-w rosters: ESPN keeps no past pool, the
  probe found) and the rest-of-season prior the live scan has. `universe_missing` counts the rostered players the
  list does not reach (or carries without a `stats` block); each is priced from his box-score rows alone.
"""
from __future__ import annotations

import json
from datetime import date
from math import log
from pathlib import Path
from typing import Any

from .config import DATA_DIR, LeagueRef
from .model.lineup import Lineup, as_set, optimize, win_prob
from .model.projections import PlayerProj, blend
from .model.season import SeasonCtx, greedy_lineup
from .model.sim import simulate
from .model.trades import lineup_strength, scan
from .model.vbd import replacement_levels
from .sources import espn

REPLAY_DIR = DATA_DIR / "replay"
REPLAY_VERSION = 2
# Reliability bins over P(win): ten of 10 points each. A season of one league is ~80 matchups, three leagues ~250,
# so the middle bins hold 30-50 each and the tails a handful; the table prints n so a thin bin is read as thin.
BINS = 10
# A side's recorded score and the sum of its starters' actuals should agree to this; a larger gap is a roster entry the
# box score did not carry (counted in `score_mismatch`, never silently fixed).
SCORE_TOL = 0.05
# A P(win) lineup that differs from the highest-points lineup is the only place the objective can earn or lose anything;
# `optimizer.differs` scores those weeks alone, and this is the sample under which the row says so.
DIFFERS_MIN_N = 20
# ESPN keeps a completed season's scores but not its lineups: every week of 2025 came back without a roster on either
# side (checked 2026-10-20 on all three leagues with the mMatchupScore, mScoreboard, mBoxscore and mMatchup views, the
# leagueHistory endpoint, and mRoster, which returns the final roster whatever `scoringPeriodId` says). espn-api raises
# a KeyError from inside its box score for that; `pull_replay` turns it into this, so the finding reads as a finding.
NO_LINEUPS = ("{name}: ESPN serves no lineups for {season} (week {week} came back without a roster), only the scores. "
              "A completed season cannot be replayed; the current season replays up to last week (--season <this year>).")


def replay_path(season: int, name: str) -> Path:
    return REPLAY_DIR / f"{season}-{name}.json"


# ---------- the pull: ESPN's archived box scores into the replay file ----------

def _row(p) -> dict:
    """One roster entry of a box score, as the replay keeps it. `p` is an espn-api BoxPlayer (or anything with the
    same attributes): `projected_points` is ESPN's number before that week's kickoff, `points` the final."""
    return {"espn_id": int(p.playerId), "name": p.name, "pos": p.position, "team": getattr(p, "proTeam", None),
            "eligible": [s for s in p.eligibleSlots if s not in espn.NON_STARTER], "slot": p.slot_position,
            "proj": round(float(p.projected_points or 0.0), 2), "actual": round(float(p.points or 0.0), 2),
            "bye": bool(getattr(p, "on_bye_week", False))}


def _team_id(t) -> int | None:
    return getattr(t, "team_id", t) if t is not None else None


def _first_kickoff(lineup: list) -> str | None:
    """The earliest game date among the period's players, ISO date: the clock a trade's `closed` date is placed on."""
    dates = [getattr(p, "game_date", None) for p in lineup]
    dates = [d for d in dates if d is not None]
    return min(dates).date().isoformat() if dates else None


def _universe_row(p) -> dict:
    """One player of the universe pull, as the replay keeps him. `p` is an espn-api Player from `espn.player_universe`
    (or anything with the same attributes): `stats[period]` carries `projected_points` (ESPN's number before that
    period's kickoff, the box score's) and `points` (the final) for every period the season has played; period 0 is
    the season row, whose `projected_points` is the static preseason total the live scan fades (`proj_season`)."""
    weeks = {}
    for per, st in (p.stats or {}).items():
        if int(per) < 1:
            continue
        row = {}
        if "projected_points" in st:
            row["proj"] = round(float(st["projected_points"] or 0.0), 2)
        if "points" in st:
            row["actual"] = round(float(st["points"] or 0.0), 2)
        if row:
            weeks[int(per)] = row
    return {"espn_id": int(p.playerId), "name": p.name, "pos": p.position, "team": getattr(p, "proTeam", None),
            "eligible": [s for s in p.eligibleSlots if s not in espn.NON_STARTER],
            "proj_season": round(float(getattr(p, "projected_total_points", 0) or 0.0), 2),
            "bye_weeks": espn.bye_weeks(p), "weeks": weeks}


def universe(players: list, rostered: set[int]) -> tuple[dict[int, dict], int, int]:
    """The universe as the replay keeps it: espn_id -> `_universe_row` for every pulled player with a `stats` block,
    the size of the pull, and how many of `rostered` (everyone on any replayed week's roster) it does not hold. A
    player with no `stats` block at all (the probe found one, a season-long 0.0 on a bench) has neither the season
    total nor a period, so he is left out and counted: the scan prices him from his box-score rows alone."""
    out = {int(p.playerId): _universe_row(p) for p in players if p.stats}
    return out, len(players), sum(pid not in out for pid in rostered)


def pull_replay(ref: LeagueRef, league, season: int, weeks: list[int] | None = None, today: date | None = None) -> dict:
    """One league's season from ESPN's box scores (read-only). `league` is a connected espn-api League for `season`.

    Only the scoring periods that are a whole matchup period are pulled (the regular season everywhere, and a
    playoff round that is one week); a week that is one half of a two-week matchup goes to `skipped_weeks`. A week
    nobody has played yet (every score zero) is left out, so the current season replays up to last week.

    The universe (`players`) is one `espn.player_universe` pull at the current period: the probe found that one
    pull carries every period's projection and actual, and that the pull's own period changes nothing else the
    replay reads (the ownership, designation and team it carries are today's and are not kept)."""
    s = espn.settings(ref, league)
    single = {per[0]: m for m, per in s.matchup_periods.items() if len(per) == 1}
    multi = sorted(w for m, per in s.matchup_periods.items() if len(per) > 1 for w in per)
    weeks = list(weeks) if weeks else sorted(w for w in single if w <= league.current_week)
    out_weeks, cache = [], {}
    for w in weeks:
        if w not in single:
            continue
        matchups, players = [], []
        try:
            boxes = league.box_scores(w, player_team_cache=cache)
        except KeyError as exc:
            if "rosterForCurrentScoringPeriod" not in str(exc):
                raise
            raise SystemExit(NO_LINEUPS.format(name=ref.name, season=season, week=w)) from exc
        for b in boxes:
            home, away = _team_id(b.home_team), _team_id(b.away_team)
            if home is None or away is None or not b.home_lineup or not b.away_lineup:
                continue   # a bye in the fantasy schedule
            players += list(b.home_lineup) + list(b.away_lineup)
            matchups.append({"home": home, "away": away, "home_score": round(float(b.home_score), 2), "away_score": round(float(b.away_score), 2),
                             "playoff": bool(getattr(b, "is_playoff", False)),
                             "home_roster": [_row(p) for p in b.home_lineup], "away_roster": [_row(p) for p in b.away_lineup]})
        if not matchups or all(m["home_score"] == 0 and m["away_score"] == 0 for m in matchups):
            continue   # not played yet
        out_weeks.append({"week": w, "first_kickoff": _first_kickoff(players), "matchups": matchups})
    rostered = {r["espn_id"] for wk in out_weeks for m in wk["matchups"] for r in m["home_roster"] + m["away_roster"]}
    uni, size, missing = universe(espn.player_universe(league, league.current_week), rostered)
    return {"version": REPLAY_VERSION, "season": season, "league": ref.name, "pulled": (today or date.today()).isoformat(),
            "settings": {"name": s.name, "team_count": s.team_count, "lineup_slots": s.lineup_slots, "ppr": s.ppr,
                         "reg_season_weeks": s.reg_season_weeks, "playoff_weeks": s.playoff_weeks,
                         # the scanner replay's inputs: the sim's bracket size, the roster size and ESPN's position caps
                         "playoff_team_count": s.playoff_team_count, "bench_slots": s.bench_slots, "position_limits": dict(s.position_limits or {})},
            "skipped_weeks": [w for w in multi if w <= league.current_week], "weeks": out_weeks,
            "universe_size": size, "universe_missing": missing, "players": uni}


def save_replay(rep: dict) -> Path:
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    out = replay_path(rep["season"], rep["league"])
    out.write_text(json.dumps(rep, indent=1))
    return out


def load_replay(path: str | Path) -> dict:
    """The replay file back as `pull_replay` built it: JSON strings the `players` keys and each player's `weeks`
    keys, so both come back as ints. A version-1 file (no universe) is refused; the box-score half is unchanged, so
    `ff replay-pull` again is the whole fix."""
    rep = json.loads(Path(path).read_text())
    if rep.get("version") != REPLAY_VERSION:
        raise SystemExit(f"{path}: replay version {rep.get('version')}, this code reads {REPLAY_VERSION} "
                         f"(version 2 added the player universe); re-run `ff replay-pull`")
    rep["players"] = {int(pid): {**row, "weeks": {int(w): v for w, v in row["weeks"].items()}} for pid, row in rep["players"].items()}
    return rep


# ---------- the lineup question ----------

def row_proj(row: dict, week: int) -> PlayerProj:
    """The replay row through `projections.blend` with ESPN as the only source: the house sigma on ESPN's number, the
    `p_zero` floor (the archive keeps no designation), a bye at zero. ESPN's zero on a week with a game is a player it
    knew was out (or never projected): a certain zero, so his seat prices as empty rather than as 0 ± sigma."""
    r = {"espn_id": row["espn_id"], "name": row["name"], "pos": row["pos"], "team": row.get("team"), "eligible": list(row["eligible"]),
         "slot": row["slot"], "fantasy_team_id": None, "injury_status": None, "proj_week": row["proj"], "actual_week": row["actual"],
         "proj_season": 0.0, "percent_owned": 0.0, "pos_rank": None, "bye": bool(row.get("bye"))}
    p = blend(r, None, None, weeks_remaining=1, week=week)
    if row["proj"] <= 0 and not row.get("bye"):
        p.p_zero = 1.0
    return p


def _realized(lu: Lineup, actual: dict[int, float]) -> float:
    return round(sum(actual[p.espn_id] for ps in lu.assignment.values() for p in ps), 2)


def side(rows: list[dict], opp_rows: list[dict], slots: dict[str, int], week: int) -> dict[str, Any]:
    """One team's week: the lineup the manager set (`set`), the highest-points lineup (`ev`) and the P(win) lineup
    against the opponent's set lineup (`win`), each with the P(win) the model put on it before kickoff and the points
    it actually scored. The opponent's distribution is his set lineup, which is what the live packet uses from
    Saturday on (`LINEUP_SET_DAYS`); nothing here looks at an actual before choosing."""
    mine = [row_proj(r, week) for r in rows]
    theirs = [row_proj(r, week) for r in opp_rows]
    actual = {r["espn_id"]: float(r["actual"]) for r in rows}
    opp = as_set(theirs, slots)
    set_lu = as_set(mine, slots, opp.mu, opp.var)
    ev_lu = optimize(mine, slots, objective="ev")
    win_lu = optimize(mine, slots, opp_mu=opp.mu, opp_var=opp.var)
    starters = lambda lu: frozenset(p.espn_id for ps in lu.assignment.values() for p in ps)
    return {"p_set": set_lu.p_win, "p_ev": win_prob(ev_lu.mu, ev_lu.var, opp.mu, opp.var), "p_win": win_lu.p_win,
            "pts_set": _realized(set_lu, actual), "pts_ev": _realized(ev_lu, actual), "pts_win": _realized(win_lu, actual),
            "win_gain": win_lu.win_gain or 0.0, "differs": starters(win_lu) != starters(ev_lu)}


def _won(mine: float, theirs: float) -> float:
    return 1.0 if mine > theirs else 0.0 if mine < theirs else 0.5


def _rate(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 3) if xs else None


def lineup_calibration(rep: dict, bins: int = BINS) -> dict[str, Any]:
    """Score every matchup in the replay.

    `calibration` is the model's P(win) for the home side's set lineup against the away side's, one row per matchup,
    against who won: `brier` (0.25 is a coin flip), `log_loss`, `ece` (the n-weighted gap between what each bin
    predicted and what it won) and the `bins` themselves (`p_mean` against `won`, with n). The away side is the same
    row mirrored, so it is not counted twice.

    `optimizer` is one row per team-week: the points and the win rate of the set, the highest-points and the P(win)
    lineup, each against the opponent's recorded score; `ev_over_set` is what the manager left on the bench by the
    projections' own ranking; `differs` is the weeks the P(win) lineup was not the highest-points lineup, the only
    weeks the objective can earn or lose anything, with both lineups' win rates there and the P(win) the model said
    it was buying (`gain_promised`) next to what it bought (`gain_realized`)."""
    slots = rep["settings"]["lineup_slots"]
    rows: list[tuple[float, float]] = []
    tw: list[dict] = []
    mismatch = 0
    for wk in rep["weeks"]:
        for m in wk["matchups"]:
            h = side(m["home_roster"], m["away_roster"], slots, wk["week"])
            a = side(m["away_roster"], m["home_roster"], slots, wk["week"])
            mismatch += abs(h["pts_set"] - m["home_score"]) > SCORE_TOL
            mismatch += abs(a["pts_set"] - m["away_score"]) > SCORE_TOL
            rows.append((h["p_set"], _won(m["home_score"], m["away_score"])))
            tw.append({**h, "opp": m["away_score"], "week": wk["week"], "team": m["home"]})
            tw.append({**a, "opp": m["home_score"], "week": wk["week"], "team": m["away"]})
    n = len(rows)
    out: dict[str, Any] = {"league": rep.get("league"), "season": rep.get("season"), "weeks": [w["week"] for w in rep["weeks"]],
                           "score_mismatch": int(mismatch)}
    if not n:
        out.update(calibration=None, optimizer=None)
        return out
    eps = 1e-6
    brier = sum((p - w) ** 2 for p, w in rows) / n
    ll = -sum(w * log(max(p, eps)) + (1 - w) * log(max(1 - p, eps)) for p, w in rows) / n
    table = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        inb = [(p, w) for p, w in rows if lo <= p < hi or (i == bins - 1 and p == 1.0)]
        table.append({"lo": round(lo, 2), "hi": round(hi, 2), "n": len(inb),
                      "p_mean": _rate([p for p, _ in inb]), "won": _rate([w for _, w in inb])})
    ece = sum(b["n"] / n * abs(b["p_mean"] - b["won"]) for b in table if b["n"])
    out["calibration"] = {"n": n, "brier": round(brier, 4), "log_loss": round(ll, 4), "ece": round(ece, 4), "bins": table}
    diff = [t for t in tw if t["differs"]]
    opt = {"team_weeks": len(tw),
           "pts": {k: round(sum(t[f"pts_{k}"] for t in tw) / len(tw), 2) for k in ("set", "ev", "win")},
           "win_rate": {k: _rate([_won(t[f"pts_{k}"], t["opp"]) for t in tw]) for k in ("set", "ev", "win")},
           "ev_over_set": round(sum(t["pts_ev"] - t["pts_set"] for t in tw) / len(tw), 2),
           "differs": {"n": len(diff), "min_n": DIFFERS_MIN_N,
                       "win_rate": {k: _rate([_won(t[f"pts_{k}"], t["opp"]) for t in diff]) for k in ("ev", "win")},
                       "gain_promised": _rate([t["win_gain"] for t in diff]),
                       "gain_realized": (round(_rate([_won(t["pts_win"], t["opp"]) for t in diff]) - _rate([_won(t["pts_ev"], t["opp"]) for t in diff]), 3)
                                         if diff else None)}}
    out["optimizer"] = opt
    return out


# ---------- the trade question ----------

def weekly_actuals(rep: dict) -> dict[str, dict[int, float]]:
    """name -> {week: actual} for everyone rostered in the replay, in the league's scoring. A player on nobody's
    roster that week is absent, which `score_trade` counts as a missing week rather than a zero."""
    out: dict[str, dict[int, float]] = {}
    for wk in rep["weeks"]:
        for m in wk["matchups"]:
            for r in m["home_roster"] + m["away_roster"]:
                out.setdefault(r["name"], {})[wk["week"]] = float(r["actual"])
    return out


def week_after(rep: dict, day: str | None) -> int | None:
    """The first replayed week whose first kickoff is after `day` (ISO date): the first week a trade closed on `day`
    could have changed a lineup. None when the replay has no kickoff dates or no week after it."""
    if not day:
        return None
    for wk in rep["weeks"]:
        if wk.get("first_kickoff") and wk["first_kickoff"] > day:
            return wk["week"]
    return None


def score_trade(o: dict, actuals: dict[str, dict[int, float]], from_week: int | None, through_week: int) -> dict:
    """One executed offer against the replay: per week from `from_week` to `through_week` (exclusive), the points the
    players I got scored minus the ones I gave, averaged into `realized_ppw`; a week any of them is unrostered is
    `missing`, not zero. `predicted_ppw` is the scan's delta when the outcome recorded one, and `hit` says the two
    agree in sign (None without a prediction or a scored week)."""
    give, get = list(o.get("give") or []), list(o.get("get") or [])
    deltas, missing = [], 0
    for w in range(from_week or through_week, through_week):
        g = [actuals.get(n, {}).get(w) for n in get]
        v = [actuals.get(n, {}).get(w) for n in give]
        if any(x is None for x in g + v):
            missing += 1
            continue
        deltas.append(sum(g) - sum(v))
    realized = round(sum(deltas) / len(deltas), 2) if deltas else None
    pred = o.get("predicted_ppw")
    hit = None if realized is None or pred is None else (realized > 0) == (pred > 0)
    return {"league": o.get("league"), "rival": o.get("rival"), "give": give, "get": get, "closed": o.get("closed"),
            "from_week": from_week, "weeks": len(deltas), "missing": missing, "realized_ppw": realized,
            "predicted_ppw": pred, "hit": hit}


def trade_hits(outcomes: dict[str, dict], replays: dict[str, dict]) -> list[dict]:
    """Every accepted offer in the outcome log scored against its league's replay (`replays` is league name -> replay).
    An offer whose league has no replay, or that closed after the last replayed week, is listed with no weeks."""
    out = []
    for o in outcomes.values():
        if o.get("status") != "accepted":
            continue
        rep = replays.get(o.get("league"))
        if rep is None or not rep["weeks"]:
            out.append(score_trade(o, {}, None, 0))
            continue
        through = max(w["week"] for w in rep["weeks"]) + 1
        out.append(score_trade(o, weekly_actuals(rep), week_after(rep, o.get("closed")), through))
    return out


# ---------- the scanner replay: every package the scan would have proposed, graded (TODO D12) ----------
# `docs/plans/scanner-replay.md`. Each replayed regular-season week w, each team as `my_id`: the rosters from the
# week-w box scores and the wire from the universe (minus everyone rostered that week), priced as the live scan prices
# them (`replay_proj`: ESPN's week-w number, the season to date from the universe's periods under w, the preseason
# total as the fading prior), the record as of week w, the playoff odds from the sim on the replayed later matchups,
# and no chart (`CHART_OFF`). Every package the hard rules let through is kept, then scored against the weeks after w.

# The reliability bins over a package's promised `my_delta_ppw`, points a week: the scan's own floor is 0.75, so the
# first bin is the marginal rows; `MUST_TRY_PPW` (2) splits the middle.
SCAN_BINS = ((0.0, 1.0), (1.0, 2.0), (2.0, 4.0), (4.0, None))
# The card ranks a team-week's packages by `p_accept × my_delta_ppw` and prints a few; the `top3` tables are the
# sample the card would have shown.
TOP_PER_TEAM_WEEK = 3
# Draws per week for the playoff odds (the acceptance score's `playoff_pct` signal and the playoff-week weights). The
# packet runs 4000 once; the replay runs the sim once per replayed week.
SCAN_SIMS = 1000
CHART_OFF = ("FantasyCalc keeps no archive: the scan ran with no market values, so no package read as a lowball, asked for "
             "a star or carried a throw-in, and p_accept ran on the other signals")


def season_to_date(player: dict | None, week: int) -> tuple[float, int]:
    """(points, games) over periods 1..week-1 of a universe row. A period with an actual is a game played, a zero on a
    game week included (as ESPN's `appliedAverage` counts it); a bye has no row and counts none."""
    if not player:
        return 0.0, 0
    pts = [v["actual"] for per, v in player["weeks"].items() if per < week and "actual" in v]
    return round(sum(pts), 2), len(pts)


def pool_row(player: dict, week: int) -> dict:
    """A universe player as a box-score-shaped row for `replay_proj`: on the wire at week `week`, ESPN's projection for
    that period (none: a zero, a certain one unless it is his bye)."""
    wk = player["weeks"].get(week) or {}
    return {"espn_id": player["espn_id"], "name": player["name"], "pos": player["pos"], "team": player.get("team"),
            "eligible": list(player["eligible"]), "slot": "", "proj": float(wk.get("proj") or 0.0),
            "bye": week in set(player.get("bye_weeks") or [])}


def replay_proj(row: dict, universe: dict[int, dict], week: int, weeks_remaining: int, team_id: int | None = None) -> PlayerProj:
    """The week-w box-score row (or `pool_row`) as the live scan would have priced him: `blend` with ESPN as the only
    source and the rest-of-season inputs the universe keeps (`proj_season` the preseason total, `actual_season` and
    `games_played` over periods 1..w-1, `bye_weeks`). A player the universe does not reach is priced from the row alone
    (this week's number, no prior). ESPN's zero on a game week is a player it knew was out: a certain zero this week
    and out this one week (`weeks_out` 1), healthy from the next, since the archive keeps no designation; the
    package that touches him is flagged `touches_zero` and the tables print with and without them."""
    u = universe.get(row["espn_id"])
    pts, games = season_to_date(u, week)
    r = {"espn_id": row["espn_id"], "name": row["name"], "pos": row["pos"], "team": row.get("team"), "eligible": list(row["eligible"]),
         "slot": row.get("slot") or "", "fantasy_team_id": team_id, "injury_status": None, "proj_week": row["proj"],
         "proj_season": (u or {}).get("proj_season") or 0.0, "actual_season": pts, "games_played": games,
         "percent_owned": 0.0, "pos_rank": None, "bye": bool(row.get("bye")), "bye_weeks": list((u or {}).get("bye_weeks") or [])}
    zero = row["proj"] <= 0 and not row.get("bye")
    ov = {str(row["espn_id"]): {"weeks_out": 1}} if zero else None
    p = blend(r, None, None, weeks_remaining=weeks_remaining, overrides=ov, week=week)
    if zero:
        p.p_zero = 1.0
        p.flags = [f for f in p.flags if f != "llm:weeks_out"] + ["replay:zero"]
    return p


def _week_rosters(wk: dict) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for m in wk["matchups"]:
        out[m["home"]] = m["home_roster"]
        out[m["away"]] = m["away_roster"]
    return out


def standings_at(rep: dict, week: int) -> dict[int, tuple[int, int, float]]:
    """team -> (wins, losses, points for) over the replayed weeks before `week`, from the recorded scores (a tie is
    neither). Every team the replay has seen gets a row, so a team on a fantasy bye still has its record."""
    out: dict[int, list] = {}
    for wk in rep["weeks"]:
        for m in wk["matchups"]:
            h, a = out.setdefault(m["home"], [0, 0, 0.0]), out.setdefault(m["away"], [0, 0, 0.0])
            if wk["week"] >= week:
                continue
            h[2] += m["home_score"]; a[2] += m["away_score"]
            if m["home_score"] > m["away_score"]:
                h[0] += 1; a[1] += 1
            elif m["home_score"] < m["away_score"]:
                a[0] += 1; h[1] += 1
    return {t: (won, lost, round(pf, 2)) for t, (won, lost, pf) in out.items()}


def schedule_after(rep: dict, week: int, reg_season_weeks: int | None) -> list[list[tuple[int, int]]]:
    """The replayed regular-season matchups after `week`, one list of (home, away) per week: the sim's remaining
    schedule (fixed before the season, so not a leak). A week not yet replayed is not in it, so the odds at week w
    of a live season are over the weeks the replay holds, not the whole season."""
    return [[(m["home"], m["away"]) for m in wk["matchups"]] for wk in rep["weeks"]
            if wk["week"] > week and (reg_season_weeks is None or wk["week"] <= reg_season_weeks)]


def playoff_odds(rep: dict, week: int, rosters: dict[int, list[PlayerProj]], sims: int = SCAN_SIMS) -> dict[int, float] | None:
    """Each team's playoff odds as of week `week`: the sim on the week-w record, the week-w rest-of-season lineup
    strength and the replayed later matchups. None when the settings carry no bracket size (an older file)."""
    s = rep["settings"]
    n_teams = s.get("playoff_team_count")
    if not n_teams:
        return None
    ids = list(rosters)
    standings = standings_at(rep, week)
    records = {t: standings.get(t, (0, 0, 0.0)) for t in ids}
    strength = {t: lineup_strength(ps, s["lineup_slots"]) for t, ps in rosters.items()}
    remaining = [[(h, a) for h, a in pairs if h in rosters and a in rosters] for pairs in schedule_after(rep, week, s.get("reg_season_weeks"))]
    odds = simulate(ids, records, strength, remaining, int(n_teams), max(len(s.get("playoff_weeks") or []), 1), n=sims)
    return {t: float(o["playoff_pct"]) for t, o in odds.items()}


def scan_week(rep: dict, week: int, through: int, sims: int = SCAN_SIMS) -> list[dict]:
    """Every package `trades.scan` would have proposed in week `week`, for every team with a roster that week as
    `my_id`, priced and not yet scored. `through` is one past the last week the pricing covers (`weeks_remaining` is
    `through - week`). Nothing here reads an actual from week `week` on: the record and the season to date stop at
    `week - 1`, the lineups and the wire are priced on the week's projections."""
    s = rep["settings"]
    slots = s["lineup_slots"]
    wk = next(w for w in rep["weeks"] if w["week"] == week)
    W = max(through - week, 1)
    uni = rep["players"]
    rosters = {tid: [replay_proj(r, uni, week, W, tid) for r in rows] for tid, rows in _week_rosters(wk).items()}
    rostered = {p.espn_id for ps in rosters.values() for p in ps}
    pool = [replay_proj(pool_row(pl, week), uni, week, W) for pid, pl in uni.items() if pid not in rostered]
    pool = [p for p in pool if p.mu_ros > 0]
    everyone = [p for ps in rosters.values() for p in ps]
    repl = replacement_levels(everyone + pool, slots, s["team_count"])
    reg = s.get("reg_season_weeks")
    ctx = SeasonCtx.build(week, W, reg, None, fas=pool, playoff_weeks=s.get("playoff_weeks"))
    odds = playoff_odds(rep, week, rosters, sims)
    standings = standings_at(rep, week)
    team_meta = {t: {"wins": standings.get(t, (0, 0, 0.0))[0], "losses": standings.get(t, (0, 0, 0.0))[1], "name": f"team {t}"} for t in rosters}
    limits = s.get("position_limits") or {}
    roster_max = sum(slots.values()) + int(s["bench_slots"]) if s.get("bench_slots") else None
    by_id = {p.espn_id: p for p in everyone}
    wire = [p.espn_id for p in ctx.fa_pool]
    out = []
    for tid in rosters:
        cands = scan(tid, rosters, slots, repl, team_meta, {}, max_per_rival=10**6, top=10**6, limits=limits, roster_max=roster_max,
                     ctx=ctx, playoff_pct=odds, reg_season_weeks=reg)
        for rank, c in enumerate(cands, 1):
            ids = c["give_ids"] + c["get_ids"]
            out.append({"week": week, "team": tid, "rank": rank, "rival_team_id": c["rival_team_id"],
                        "give": c["give"], "get": c["get"], "give_ids": c["give_ids"], "get_ids": c["get_ids"],
                        "drops": [d["name"] for d in c["drops"]], "my_delta_ppw": c["my_delta_ppw"], "their_delta_ppw": c["their_delta_ppw"],
                        "p_accept": c["p_accept"], "score": c["score"], "sendable": c["sendable"], "must_try": c["must_try"],
                        "touches_zero": any(by_id[i].p_zero >= 1.0 and not by_id[i].bye for i in ids), "wire_ids": wire})
    return out


class _Body:
    """What `greedy_lineup` reads of a player: the id and the slots he may fill."""
    __slots__ = ("espn_id", "eligible")

    def __init__(self, row: dict):
        self.espn_id, self.eligible = row["espn_id"], row["eligible"]


def by_week(rep: dict) -> tuple[dict[int, dict[int, float]], dict[int, dict[int, float]]]:
    """(proj, actual) as espn_id -> {week: value}: the universe (a bye week, which has no row, as a zero), overlaid by
    the box scores (the two agree on every rostered week, the probe found; the box score alone carries a player the
    universe does not reach). A week absent from both is `missing` to the scorer, never a zero."""
    proj: dict[int, dict[int, float]] = {}
    actual: dict[int, dict[int, float]] = {}
    weeks = [w["week"] for w in rep["weeks"]]
    for pid, pl in rep["players"].items():
        for w, v in pl["weeks"].items():
            if "proj" in v:
                proj.setdefault(pid, {})[w] = float(v["proj"])
            if "actual" in v:
                actual.setdefault(pid, {})[w] = float(v["actual"])
        for w in pl.get("bye_weeks") or []:
            if w in weeks:
                proj.setdefault(pid, {}).setdefault(w, 0.0)
                actual.setdefault(pid, {}).setdefault(w, 0.0)
    for wk in rep["weeks"]:
        for m in wk["matchups"]:
            for r in m["home_roster"] + m["away_roster"]:
                proj.setdefault(r["espn_id"], {})[wk["week"]] = float(r["proj"])
                actual.setdefault(r["espn_id"], {})[wk["week"]] = float(r["actual"])
    return proj, actual


def _lineup_points(bodies: list[_Body], t: int, proj: dict, actual: dict, slots: dict[str, int]) -> float:
    """The highest-points lineup of `bodies` for week `t`, seated on that week's projections and scored on its actuals
    (the leakage rule: the seat never sees the actual). A seated body with no actual that week scores nothing."""
    vals = [(b, proj.get(b.espn_id, {}).get(t, 0.0)) for b in bodies]
    _, used = greedy_lineup(vals, slots)
    return sum(actual.get(i, {}).get(t, 0.0) for i in used)


def score_packages(rep: dict, cands: list[dict], through: int | None = None) -> list[dict]:
    """Each package of `scan_week` against the weeks after its own, `through` exclusive (default: one past the last
    replayed week), two ways. `realized_ppw` is `score_trade`'s raw definition, the players I get minus the ones I
    give, bench or not. `realized_lineup_ppw` is what `my_delta_ppw` forecasts: the week-w roster with and without
    the swap (the cap drops gone too), each seated by the highest-points lineup on that week's projections and scored
    with its actuals, the difference averaged. The wire bodies the pricing assumed (`wire_ids`, the week-w `fa_pool`)
    sit in both lineups, since the promise was priced with them as the fallback for a lost slot; everything is frozen
    at week w, the team's later moves not replayed.
    A week any traded player has no actual for is `missing`, not zero. `hit` is the sign of the lineup number
    against the promise."""
    slots = rep["settings"]["lineup_slots"]
    through = through or (max(w["week"] for w in rep["weeks"]) + 1 if rep["weeks"] else 0)
    proj, actual = by_week(rep)
    rows_at = {w["week"]: _week_rosters(w) for w in rep["weeks"]}
    base: dict[tuple[int, int, int], float] = {}
    for c in cands:
        rows = rows_at[c["week"]]
        mine = {r["espn_id"]: r for r in rows[c["team"]]}
        theirs = {r["espn_id"]: r for r in rows[c["rival_team_id"]]}
        gone = set(c["give_ids"]) | {i for i, r in mine.items() if r["name"] in set(c["drops"])}
        wire = [_Body(rep["players"][i]) for i in c.get("wire_ids") or [] if i in rep["players"] and i not in mine]
        before = [_Body(r) for r in mine.values()] + wire
        after = [_Body(r) for i, r in mine.items() if i not in gone] + [_Body(theirs[i]) for i in c["get_ids"]] + wire
        raw, lu, missing = [], [], 0
        for t in range(c["week"] + 1, through):
            if any(t not in actual.get(i, {}) for i in c["give_ids"] + c["get_ids"]):
                missing += 1
                continue
            raw.append(sum(actual[i][t] for i in c["get_ids"]) - sum(actual[i][t] for i in c["give_ids"]))
            key = (c["team"], c["week"], t)
            if key not in base:
                base[key] = _lineup_points(before, t, proj, actual, slots)
            lu.append(_lineup_points(after, t, proj, actual, slots) - base[key])
        realized_lu = round(sum(lu) / len(lu), 2) if lu else None
        c.update(weeks=len(lu), missing=missing, realized_ppw=round(sum(raw) / len(raw), 2) if raw else None,
                 realized_lineup_ppw=realized_lu,
                 hit=None if realized_lu is None else (realized_lu > 0) == (c["my_delta_ppw"] > 0))
    return cands


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 2) if xs else None


def scan_table(cands: list[dict]) -> dict[str, Any]:
    """n, the hit rate, the promised mean against the two realized means, and the reliability rows by promised bin
    (`SCAN_BINS`), over the scored packages in `cands`. A bin that promises 3 and realizes 1 is the season pricing
    reading too much into a week-w projection; one that realizes 3 is a forecast worth sending."""
    sc = [c for c in cands if c["realized_lineup_ppw"] is not None]
    rows = []
    for lo, hi in SCAN_BINS:
        inb = [c for c in sc if c["my_delta_ppw"] >= lo and (hi is None or c["my_delta_ppw"] < hi)]
        rows.append({"lo": lo, "hi": hi, "n": len(inb), "hit": _rate([float(c["hit"]) for c in inb]),
                     "pred_mean": _mean([c["my_delta_ppw"] for c in inb]), "realized_mean": _mean([c["realized_lineup_ppw"] for c in inb])})
    return {"n": len(sc), "unscored": len(cands) - len(sc), "hit": _rate([float(c["hit"]) for c in sc]),
            "pred_mean": _mean([c["my_delta_ppw"] for c in sc]), "realized_mean": _mean([c["realized_lineup_ppw"] for c in sc]),
            "realized_raw_mean": _mean([c["realized_ppw"] for c in sc]), "bins": rows}


def scan_hits(rep: dict, sims: int = SCAN_SIMS, weeks: list[int] | None = None) -> dict[str, Any]:
    """The scanner replay of one league: every regular-season week with a later replayed week (`weeks` narrows it),
    every team as `my_id`, `scan_week` then `score_packages`, into the tables (`scan_table`) over every package and
    over the top `TOP_PER_TEAM_WEEK` per team-week by the card's ranking, each split by `touches_zero`."""
    reg = rep["settings"].get("reg_season_weeks")
    played = [w["week"] for w in rep["weeks"] if reg is None or w["week"] <= reg]
    through = max(played) + 1 if played else 0
    scored = [w for w in played if w + 1 < through and (not weeks or w in weeks)]
    cands: list[dict] = []
    for w in scored:
        cands += scan_week(rep, w, through, sims)
    score_packages(rep, cands, through)
    top = [c for c in cands if c["rank"] <= TOP_PER_TEAM_WEEK]

    def split(cs: list[dict]) -> dict:
        return {"every": scan_table(cs), "clean": scan_table([c for c in cs if not c["touches_zero"]]),
                "touches_zero": scan_table([c for c in cs if c["touches_zero"]])}

    return {"league": rep.get("league"), "season": rep.get("season"), "weeks": scored, "through": through - 1 if scored else None,
            "team_weeks": len({(c["week"], c["team"]) for c in cands}), "candidates": len(cands), "sims": sims, "chart": CHART_OFF,
            "all": split(cands), "top3": split(top)}
