"""Log every source's weekly projection so we can measure which sources earn their keep (MAE by source × position).

Two things make the score honest. The log carries the projection from *before* `model/clock.py` banked a played
player's points into `mu` (`mu_pre`), so a Monday row never scores the blend against itself. And the truth is ESPN's
own number in each league's scoring (`actual` once his game is `post`, `actual_prev` in the next week's first log
for the Monday-night stragglers), so half-PPR is scored as half-PPR and K and D/ST get rows, which nflverse never gave
them. One row per league per player: the same player is a different forecast and a different truth in each league.

Logs written before 2026-10-08 have none of `league`, `phase`, `actual`, `actual_prev`; for those the clock's
fingerprint stands in: a row with `p_zero` 0.0 is a locked player (the clock zeroes it, the floor for anyone else is
0.02) whose `blend` is his actual, the morning runs never land mid-game, and every other row is a forecast. A legacy
locked row at 0.0 is not a truth: the 2026-09-15 log locked 46 players at zero off a stale scoreboard cache (the
"Monday email" failure in CLAUDE.md), and a real zero is rarer than that artifact."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import polars as pl

from .config import ROOT

LOG_DIR = ROOT / "data" / "projlog"
SOURCES = ("espn_pts", "sleeper_pts", "fp_pts", "blend")
COLUMNS = ("season", "week", "date", "league", "espn_id", "name", "pos", "team", "espn_pts", "sleeper_pts", "fp_pts", "blend",
           "p_zero", "implied", "phase", "actual", "actual_prev")


def phase_of(p: dict) -> str:
    """'bye' | 'pre' | 'in' | 'post' for a packet roster row, from the clock's flag."""
    if p.get("bye"):
        return "bye"
    for f in p.get("flags") or []:
        if f.startswith("clock:"):
            return f.split(":", 1)[1]
    return "pre"


def write(packet: dict) -> Path:
    """One row per league per player per week (last write wins for the day)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    season = packet["season"]
    week = packet["leagues"][0]["week"]
    date = packet["generated"][:10]
    rows: dict[tuple[str, int], dict] = {}
    for lg in packet["leagues"]:
        for p in lg["roster"]:
            s = p["sources"]
            ph = phase_of(p)
            rows[(lg["name"], p["espn_id"])] = {
                "season": season, "week": week, "date": date, "league": lg["name"], "espn_id": p["espn_id"], "name": p["name"],
                "pos": p["pos"], "team": p["team"], "espn_pts": s.get("espn_pts"), "sleeper_pts": s.get("sleeper_pts"),
                "fp_pts": s.get("fp_pts"), "blend": p["mu_pre"] if p.get("mu_pre") is not None else p["mu"],
                "p_zero": p["p_zero"], "implied": s.get("implied_total"), "phase": ph,
                "actual": p.get("actual") if ph in ("in", "post") else None, "actual_prev": s.get("actual_prev")}
    out = LOG_DIR / f"{season}-w{week:02d}-{date}.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(COLUMNS))
        w.writeheader(); w.writerows(rows.values())
    return out


def _num(v) -> float | None:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _logs(season: int) -> dict[int, list[list[dict]]]:
    """week -> the day's rows, one list per file, oldest first."""
    by_week: dict[int, list[list[dict]]] = defaultdict(list)
    for p in sorted(LOG_DIR.glob(f"{season}-w*.csv")):
        wk = int(p.name.split("-w")[1][:2])
        with open(p, newline="") as f:
            by_week[wk].append(list(csv.DictReader(f)))
    return by_week


def _phase(r: dict) -> str:
    if r.get("phase"):
        return r["phase"]
    return "post" if _num(r.get("p_zero")) == 0.0 else "pre"   # legacy log: see the module docstring


def _actual(r: dict) -> float | None:
    if "phase" in r:
        return _num(r.get("actual"))
    act = _num(r.get("blend"))   # legacy log: the clock wrote his actual into the blend
    return act if act else None


def scored_rows(logs: dict[int, list[list[dict]]], through_week: int) -> list[dict]:
    """Each (week, league, player) scored once: his last forecast before kickoff against ESPN's final."""
    recs = []
    for wk in sorted(logs):
        if wk >= through_week:
            continue
        forecast: dict[tuple[str, str], dict] = {}
        truth: dict[tuple[str, str], float] = {}
        for rows in logs[wk]:
            for r in rows:
                key = (r.get("league") or "", r["espn_id"])
                ph = _phase(r)
                if ph == "pre":
                    forecast[key] = r
                elif ph == "post" and (act := _actual(r)) is not None:
                    truth[key] = act
        for rows in logs.get(wk + 1, [])[:1]:   # the next week's first log carries last week's finals, Monday night included
            for r in rows:
                if (act := _num(r.get("actual_prev"))) is not None:
                    truth[(r.get("league") or "", r["espn_id"])] = act
        for key, r in forecast.items():
            act = truth.get(key)
            if act is None:
                continue
            for src in SOURCES:
                v = _num(r.get(src))
                if v is None:
                    continue
                recs.append({"week": wk, "league": key[0], "espn_id": key[1], "pos": r["pos"], "source": src,
                             "err": v - act, "abs_err": abs(v - act)})
    return recs


def current_week(season: int) -> int | None:
    """The league's week as of the newest log (by date), or None with no log: the week still in progress, never Sleeper's clock.

    The harness runs offline, and Sleeper's week rolls on its own schedule (ahead of ESPN's on a Monday, behind it on a
    Tuesday), which scored a half-played week or skipped the one just finished (TODO C8). The newest log is the last
    packet's own `week`; everything before it has its finals (`actual_prev` rides in on that log)."""
    newest = max(LOG_DIR.glob(f"{season}-w*.csv"), key=lambda p: p.name.split("-", 2)[2], default=None)
    return int(newest.name.split("-w")[1][:2]) if newest else None


def accuracy(season: int, through_week: int | None = None) -> pl.DataFrame:
    """MAE and bias per source × position over all logged weeks < through_week, against ESPN's actual in league scoring.

    `through_week` defaults to `current_week`, the newest log's week."""
    if through_week is None:
        through_week = current_week(season)
    if through_week is None:
        return pl.DataFrame()
    recs = scored_rows(_logs(season), through_week)
    if not recs:
        return pl.DataFrame()
    df = pl.DataFrame(recs)
    return df.group_by(["pos", "source"]).agg([pl.len().alias("n"), pl.col("abs_err").mean().round(2).alias("mae"),
                                               pl.col("err").mean().round(2).alias("bias")]).sort(["pos", "mae"])
