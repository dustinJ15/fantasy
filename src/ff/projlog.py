"""Log every source's weekly projection so we can measure which sources earn their keep (MAE by source × position)."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import polars as pl

from .config import ROOT
from .ids import Crosswalk
from .sources import nflverse

LOG_DIR = ROOT / "data" / "projlog"
SOURCES = ("espn_pts", "sleeper_pts", "fp_pts", "blend")


def write(packet: dict) -> Path:
    """One row per player per week (last write wins for the day). Union across leagues."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    season = packet["season"]
    week = packet["leagues"][0]["week"]
    date = packet["generated"][:10]
    rows: dict[int, dict] = {}
    for lg in packet["leagues"]:
        for p in lg["roster"]:
            s = p["sources"]
            rows[p["espn_id"]] = {"season": season, "week": week, "date": date, "espn_id": p["espn_id"], "name": p["name"], "pos": p["pos"],
                                  "team": p["team"], "espn_pts": s.get("espn_pts"), "sleeper_pts": s.get("sleeper_pts"),
                                  "fp_pts": s.get("fp_pts"), "blend": p["mu"], "p_zero": p["p_zero"], "implied": s.get("implied_total")}
    out = LOG_DIR / f"{season}-w{week:02d}-{date}.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(next(iter(rows.values())).keys()))
        w.writeheader(); w.writerows(rows.values())
    return out


def _latest_per_week() -> dict[int, Path]:
    best: dict[int, Path] = {}
    for p in sorted(LOG_DIR.glob("*.csv")):
        wk = int(p.name.split("-w")[1][:2])
        best[wk] = p  # sorted by date, so last wins
    return best


def accuracy(season: int, through_week: int) -> pl.DataFrame:
    """MAE and bias per source × position over all logged weeks < through_week, using nflverse PPR actuals."""
    xw = Crosswalk()
    st = nflverse.player_stats(season)
    pid = "player_id" if "player_id" in st.columns else "gsis_id"
    actual = {(r[pid], r["week"]): r["fantasy_points_ppr"] for r in st.select([pid, "week", "fantasy_points_ppr"]).iter_rows(named=True)}
    recs = []
    for wk, path in _latest_per_week().items():
        if wk >= through_week:
            continue
        for r in csv.DictReader(open(path)):
            x = xw.lookup(r["espn_id"], r["name"], r["pos"]) or {}
            g = x.get("gsis_id")
            act = actual.get((g, wk)) if g else None
            if act is None:
                act = 0.0 if float(r.get("p_zero") or 0) >= 0.9 else None
            if act is None:
                continue
            for src in SOURCES:
                v = r.get(src)
                if v in (None, "", "None"):
                    continue
                recs.append({"week": wk, "pos": r["pos"], "source": src, "err": float(v) - float(act), "abs_err": abs(float(v) - float(act))})
    if not recs:
        return pl.DataFrame()
    df = pl.DataFrame(recs)
    return df.group_by(["pos", "source"]).agg([pl.len().alias("n"), pl.col("abs_err").mean().round(2).alias("mae"),
                                               pl.col("err").mean().round(2).alias("bias")]).sort(["pos", "mae"])
