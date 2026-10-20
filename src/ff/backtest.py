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
from .sources import espn

REPLAY_DIR = DATA_DIR / "replay"
REPLAY_VERSION = 1
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


def pull_replay(ref: LeagueRef, league, season: int, weeks: list[int] | None = None, today: date | None = None) -> dict:
    """One league's season from ESPN's box scores (read-only). `league` is a connected espn-api League for `season`.

    Only the scoring periods that are a whole matchup period are pulled (the regular season everywhere, and a
    playoff round that is one week); a week that is one half of a two-week matchup goes to `skipped_weeks`. A week
    nobody has played yet (every score zero) is left out, so the current season replays up to last week."""
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
    return {"version": REPLAY_VERSION, "season": season, "league": ref.name, "pulled": (today or date.today()).isoformat(),
            "settings": {"name": s.name, "team_count": s.team_count, "lineup_slots": s.lineup_slots, "ppr": s.ppr,
                         "reg_season_weeks": s.reg_season_weeks, "playoff_weeks": s.playoff_weeks},
            "skipped_weeks": [w for w in multi if w <= league.current_week], "weeks": out_weeks}


def save_replay(rep: dict) -> Path:
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    out = replay_path(rep["season"], rep["league"])
    out.write_text(json.dumps(rep, indent=1))
    return out


def load_replay(path: str | Path) -> dict:
    rep = json.loads(Path(path).read_text())
    if rep.get("version") != REPLAY_VERSION:
        raise SystemExit(f"{path}: replay version {rep.get('version')}, this code reads {REPLAY_VERSION}; re-run `ff replay-pull`")
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
