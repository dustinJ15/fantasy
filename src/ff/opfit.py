"""The projection-constant fitter (TODO D10): step 1 fits `projections.OPPORTUNITY_WEIGHT` and `OPPORTUNITY_RATIO_CLIP`
per position, and `usage.XFP_PER_ATTEMPT`; step 2 fits `projections.OPPONENT_K`, this week's opponent factor; step 3
fits `projections.VEGAS_K`, this week's implied team total (nflverse `schedules`); step 4 fits `projections.TREND_K`, the
last three games' usage against the season's on the rest-of-season level; all to nflverse weekly stats of past seasons. Prints, never writes: the constants are copied by hand with the sample and the
date in the comment (`docs/plans/fitted-projection.md`).

The question it answers is the one `opportunity_mult` makes a prior on: a player's season so far reads `ppg` points a
game and his targets, carries and attempts were worth `xfp_pg`; how far toward `xfp_pg` should his rest-of-season level
move? The training row is a player at a week of a past season, his season to date on one side and what he scored a
game over the rest of it on the other; the model is the live arithmetic, `ppg * (1 - w + w * clip(xfp_pg / ppg))`, so
`w` has a closed form per clip and the clip is a small grid. Scored leave-one-season-out, against no read at all (w = 0)
and the prior, so a fitted weight that does not beat the prior out of sample is reported as such.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import polars as pl

from .model import projections, usage
from .sources import nflverse

FIT_SEASONS = tuple(range(2016, 2026))
FIT_POSITIONS = ("QB", "RB", "WR", "TE")
# A training row needs this many games on each side of the week: the live read waits for OPPORTUNITY_MIN_GAMES, and a
# rest-of-season target over fewer games is one game of noise (so a body hurt for the year drops out; noted in the plan).
FIT_MIN_GAMES_AFTER = 3
# ...and a season to date worth pricing: the card prices rostered bodies and the top of the wire, not the 2-a-game tail.
FIT_MIN_PPG = 5.0
# The clip grid: the lower and upper bounds `opportunity_mult` clips the ratio to; the prior is (0.7, 1.4).
CLIP_LO_GRID = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
CLIP_HI_GRID = (1.1, 1.2, 1.3, 1.4, 1.6, 2.0, 3.0)
NO_CLIP = (0.0, float("inf"))
# The weight is a share, so the fit is held to [0, 1]: a negative weight would move him away from his usage.
W_BOUNDS = (0.0, 1.0)
# A position is fitted on this many rows or more (a season of one position is about 350-1000 rows).
FIT_MIN_N = 1000
# The weight by games played so far, for the reader: the fit says it falls with the sample (the plan says what that buys).
GAMES_BUCKETS = ((2, 3), (4, 6), (7, 10), (11, 17))
# Step 2: `k` is how much of the opponent factor's deviation this week's number takes; held to [0, 1] (a negative `k`
# would score a player up against a defense that allows less, past 1 would move him further than the factor says).
K_BOUNDS = (0.0, 1.0)
# ...and `k` by the defense's games played when the factor was read, for the reader (a young factor is mostly noise).
DEF_GAMES_BUCKETS = ((3, 5), (6, 9), (10, 17))
# Step 4: `t` is how much of the recent-usage ratio's deviation the level takes; held to [0, 1] (a negative `t` would
# move a player away from his newer role), and `t` by games played for the reader (under RECENT_GAMES + 1 the ratio is 1).
T_BOUNDS = (0.0, 1.0)
TREND_GAMES_BUCKETS = ((4, 6), (7, 10), (11, 17))


def weekly(seasons: Iterable[int] = FIT_SEASONS) -> pl.DataFrame:
    """One row per player-week over the seasons (`usage.weekly_usage`, REG only), with a `season` column."""
    frames = [usage.weekly_usage(int(s)).with_columns(pl.lit(int(s)).alias("season")) for s in seasons]
    return pl.concat(frames, how="vertical_relaxed")


def with_xfp(w: pl.DataFrame, per_attempt: float | None = None) -> pl.DataFrame:
    """The week's xFP-lite on every row (`usage.xfp_lite_expr`), attempts at `per_attempt` when given."""
    return w.with_columns(usage.xfp_lite_expr(per_attempt).alias("xfp"))


def season_rows(w: pl.DataFrame) -> pl.DataFrame:
    """One row per player-game of a season (FIT_POSITIONS), sorted, with his season so far on it: `games` before that
    week, `pts_before` and `xfp_before` over them (the row's own game subtracted from the prefix, so nothing on the row
    is read before its week), `fpts` and `xfp` that game, `opp` the defense he faced, `team` his offense, and the season's
    totals."""
    agg = [pl.col("fpts_ppr").fill_null(0.0).sum().alias("fpts")]
    if "xfp" in w.columns:
        agg.append(pl.col("xfp").fill_null(0.0).sum().alias("xfp"))
    if "opp" in w.columns:
        agg.append(pl.col("opp").drop_nulls().first().alias("opp"))
    if "team" in w.columns:
        agg.append(pl.col("team").drop_nulls().first().alias("team"))
    g = (w.filter(pl.col("pos").is_in(FIT_POSITIONS))
          .group_by(["season", "gsis_id", "pos", "week"]).agg(agg)
          .sort(["season", "gsis_id", "week"]))
    if "xfp" not in g.columns:
        g = g.with_columns(pl.lit(0.0).alias("xfp"))
    over = ["season", "gsis_id"]
    recent = pl.sum_horizontal([pl.col("xfp").shift(i).over(over).fill_null(0.0) for i in range(1, projections.RECENT_GAMES + 1)])
    return g.with_columns([
        (pl.col("fpts").cum_sum().over(over) - pl.col("fpts")).alias("pts_before"),
        recent.alias("xfp_recent"),
        (pl.col("xfp").cum_sum().over(over) - pl.col("xfp")).alias("xfp_before"),
        (pl.col("week").rank("ordinal").over(over) - 1).cast(pl.Int64).alias("games"),
        pl.col("fpts").sum().over(over).alias("pts_total"),
        pl.len().over(over).cast(pl.Int64).alias("games_total"),
    ]).with_columns([
        (pl.col("games_total") - pl.col("games")).alias("games_after"),
    ])


def training_frame(w: pl.DataFrame, min_games: int = projections.OPPORTUNITY_MIN_GAMES, min_after: int = FIT_MIN_GAMES_AFTER,
                   min_ppg: float = FIT_MIN_PPG) -> pl.DataFrame:
    """A row per player-game of a season at which the live read would have run: `games`, `ppg` and `xfp_pg` over his
    games before that week (the inputs `opportunity_mult` reads, the same game count as `usage.season_summary`: a week
    with a stat row), and `future_ppg` over his games from that week on (the truth). Rows under `min_games` before,
    `min_after` after or `min_ppg` so far are dropped."""
    g = season_rows(w).filter((pl.col("games") >= min_games) & (pl.col("games_after") >= min_after)).with_columns([
        (pl.col("pts_before") / pl.col("games")).alias("ppg"),
        (pl.col("xfp_before") / pl.col("games")).alias("xfp_pg"),
        ((pl.col("pts_total") - pl.col("pts_before")) / pl.col("games_after")).alias("future_ppg"),
    ]).filter((pl.col("ppg") >= min_ppg) & (pl.col("xfp_pg") > 0))
    return g.select(["season", "gsis_id", "pos", "week", "games", "ppg", "xfp_pg", "games_after", "future_ppg"])


@dataclass
class Sample:
    """One position's training rows as arrays: `season` for the folds, `ppg` and `xfp_pg` the inputs, `y` the truth."""
    season: np.ndarray
    games: np.ndarray
    ppg: np.ndarray
    xfp_pg: np.ndarray
    y: np.ndarray

    @classmethod
    def of(cls, df: pl.DataFrame, pos: str) -> Sample:
        d = df.filter(pl.col("pos") == pos)
        return cls(d["season"].to_numpy(), d["games"].to_numpy().astype(int), d["ppg"].to_numpy().astype(float),
                   d["xfp_pg"].to_numpy().astype(float), d["future_ppg"].to_numpy().astype(float))

    @property
    def n(self) -> int:
        return int(self.y.size)


def _x(s: Sample, clip: tuple[float, float]) -> np.ndarray:
    """The regressor: `ppg * (ratio - 1)`, so the model `ppg * (1 - w + w * ratio)` is `ppg + w * x`."""
    lo, hi = clip
    return s.ppg * (np.clip(s.xfp_pg / s.ppg, lo, hi) - 1.0)


def fit_w(s: Sample, clip: tuple[float, float], mask: np.ndarray | None = None) -> float:
    """The least-squares weight for one clip, closed form, held to W_BOUNDS. `mask` picks the training rows."""
    x = _x(s, clip)
    y = s.y - s.ppg
    if mask is not None:
        x, y = x[mask], y[mask]
    den = float((x * x).sum())
    if den <= 0:
        return 0.0
    return float(np.clip((x * y).sum() / den, *W_BOUNDS))


def rmse(s: Sample, clip: tuple[float, float], w: float, mask: np.ndarray | None = None) -> float:
    err = s.ppg + w * _x(s, clip) - s.y
    if mask is not None:
        err = err[mask]
    return float(np.sqrt(np.mean(err**2))) if err.size else float("nan")


def oos(s: Sample, clip: tuple[float, float]) -> tuple[float, int, list[float]]:
    """Leave-one-season-out: the weight fitted on the other seasons, scored on the held-out one. The summed squared
    error and count over every held-out row, and the per-fold weights (their spread is whether the number is one
    number)."""
    sse, n, ws = 0.0, 0, []
    for yr in np.unique(s.season):
        test = s.season == yr
        if test.all():
            continue
        w = fit_w(s, clip, ~test)
        ws.append(w)
        err = (s.ppg + w * _x(s, clip) - s.y)[test]
        sse += float((err**2).sum()); n += int(err.size)
    return sse, n, ws


def _rmse(sse: float, n: int) -> float | None:
    return round(float(np.sqrt(sse / n)), 4) if n else None


def fit_position(s: Sample, pos: str, clip: tuple[float, float], min_n: int = FIT_MIN_N) -> dict:
    """One position's row at the chosen clip: the sample, the prior weight and its out-of-sample error at the prior
    clip, no read at all (w = 0), the weight fitted on every season, the per-fold weights, and the verdict: `fit` when
    the fitted weight beats the prior out of sample on `min_n` rows or more, else `keep prior`."""
    prior_w = projections.OPPORTUNITY_WEIGHT.get(pos, 0.0)
    prior_clip = projections.OPPORTUNITY_RATIO_CLIP
    row = {"pos": pos, "n": s.n, "seasons": int(np.unique(s.season).size), "w_prior": prior_w, "clip_prior": prior_clip,
           "rmse_none": None, "rmse_prior": None, "w_fit": None, "rmse_fit": None, "w_folds": [], "w_by_games": {},
           "fitted": False, "min_n": min_n}
    if not s.n:
        return row
    sse, n, ws = oos(s, clip)
    row.update(rmse_none=round(rmse(s, prior_clip, 0.0), 4), rmse_prior=round(rmse(s, prior_clip, prior_w), 4),
               w_fit=round(fit_w(s, clip), 3), rmse_fit=_rmse(sse, n), w_folds=[round(x, 3) for x in ws])
    for lo, hi in GAMES_BUCKETS:
        m = (s.games >= lo) & (s.games <= hi)
        row["w_by_games"][f"{lo}-{hi}"] = (round(fit_w(s, clip, m), 3), int(m.sum())) if m.any() else (None, 0)
    row["fitted"] = s.n >= min_n and row["rmse_fit"] is not None and row["rmse_fit"] < row["rmse_prior"] - 1e-9
    return row


def choose_clip(samples: dict[str, Sample]) -> tuple[tuple[float, float], dict[tuple[float, float], float | None]]:
    """One clip for every position (the constant is one tuple): the grid point with the lowest pooled leave-one-
    season-out error over the positions, and the pooled error of every grid point, the prior's and no clip at all
    included, so the reader sees how little or much the clip moves."""
    grid = [(lo, hi) for lo in CLIP_LO_GRID for hi in CLIP_HI_GRID]
    table: dict[tuple[float, float], float | None] = {}
    for clip in dict.fromkeys(grid + [projections.OPPORTUNITY_RATIO_CLIP, NO_CLIP]):
        sse, n = 0.0, 0
        for s in samples.values():
            if s.n:
                a, b, _ = oos(s, clip)
                sse += a; n += b
        table[clip] = _rmse(sse, n)
    best = min((c for c in grid if table[c] is not None), key=lambda c: table[c], default=projections.OPPORTUNITY_RATIO_CLIP)
    return best, table


def fit_weights(df: pl.DataFrame) -> dict:
    """`choose_clip` over FIT_POSITIONS, then `fit_position` for each at that clip."""
    samples = {pos: Sample.of(df, pos) for pos in FIT_POSITIONS}
    clip, table = choose_clip(samples)
    return {"clip": clip, "clip_table": table, "weights": [fit_position(samples[pos], pos, clip) for pos in FIT_POSITIONS]}


# ---------- step 2: the opponent factor ----------

def factors_by_week(tg: pl.DataFrame) -> pl.DataFrame:
    """Every defense's factor as it stood before each week of each season: `usage.opponent_factors` through week
    w - 1, labelled `week` w, so a row at week w joins the factor the live read would have had on the morning of it."""
    out = []
    for yr in tg["season"].unique().sort().to_list():
        t = tg.filter(pl.col("season") == yr)
        for wk in range(2, int(t["week"].max()) + 1):
            f = usage.opponent_factors(t, through_week=wk - 1)
            if not f.is_empty():
                out.append(f.with_columns(pl.lit(wk).cast(pl.Int64).alias("week")))
    cols = ["season", "team", "pos", "games", "allowed_pg", "expected_pg", "raw", "factor", "week"]
    return pl.concat(out, how="vertical_relaxed") if out else pl.DataFrame({c: [] for c in cols})


def opponent_frame(w: pl.DataFrame, min_games: int = projections.OPPORTUNITY_MIN_GAMES, min_ppg: float = FIT_MIN_PPG,
                   min_def_games: int = projections.OPPONENT_MIN_GAMES) -> pl.DataFrame:
    """A row per player-game at which the live read would have priced his week: `ppg` over his games before it
    (`min_games` or more, `min_ppg` or more), the defense he faced that week with its `factor` and `raw` as they stood
    through the week before (`def_games` games, `min_def_games` or more), and `pts`, what he scored that week (the
    truth). The row's own game is in neither input."""
    tg = usage.team_games(w)
    f = factors_by_week(tg).rename({"team": "opp", "games": "def_games"}).select(["season", "opp", "pos", "week", "def_games", "raw", "factor"])
    g = (season_rows(w).filter((pl.col("games") >= min_games) & pl.col("opp").is_not_null())
           .with_columns((pl.col("pts_before") / pl.col("games")).alias("ppg"))
           .filter(pl.col("ppg") >= min_ppg)
           .join(f, on=["season", "opp", "pos", "week"], how="inner")
           .filter(pl.col("def_games") >= min_def_games))
    return g.select(["season", "gsis_id", "pos", "week", "games", "ppg", "opp", "def_games", "raw", "factor", pl.col("fpts").alias("pts")])


@dataclass
class OppSample:
    """One position's opponent rows as arrays: `season` for the folds, `def_games` the defense's sample, `ppg` his
    level so far, `factor` (and `raw`, the unadjusted one) the defense's, `y` his points that week."""
    season: np.ndarray
    def_games: np.ndarray
    ppg: np.ndarray
    factor: np.ndarray
    raw: np.ndarray
    y: np.ndarray

    @classmethod
    def of(cls, df: pl.DataFrame, pos: str) -> OppSample:
        d = df.filter(pl.col("pos") == pos)
        return cls(d["season"].to_numpy(), d["def_games"].to_numpy().astype(int), d["ppg"].to_numpy().astype(float),
                   d["factor"].to_numpy().astype(float), d["raw"].to_numpy().astype(float), d["pts"].to_numpy().astype(float))

    @property
    def n(self) -> int:
        return int(self.y.size)


def _fx(s: OppSample, raw: bool = False) -> np.ndarray:
    """The regressor: `ppg * (factor - 1)`, so the model `ppg * (1 + k * (factor - 1))` is `ppg + k * x`."""
    return s.ppg * ((s.raw if raw else s.factor) - 1.0)


def fit_k(s: OppSample, mask: np.ndarray | None = None, raw: bool = False) -> float:
    """The least-squares `k`, closed form, held to K_BOUNDS (the cap is left off the fit and put on the score, as the
    live multiplier is: `fit_opponent_position` says how often it binds). `mask` picks the training rows."""
    x = _fx(s, raw)
    y = s.y - s.ppg
    if mask is not None:
        x, y = x[mask], y[mask]
    den = float((x * x).sum())
    if den <= 0:
        return 0.0
    return float(np.clip((x * y).sum() / den, *K_BOUNDS))


def _opp_pred(s: OppSample, k: float, cap: float | None, raw: bool = False) -> np.ndarray:
    m = 1.0 + k * ((s.raw if raw else s.factor) - 1.0)
    if cap is not None:
        m = np.clip(m, 1.0 - cap, 1.0 + cap)
    return s.ppg * m


def opp_rmse(s: OppSample, k: float, cap: float | None, mask: np.ndarray | None = None, raw: bool = False) -> float:
    err = _opp_pred(s, k, cap, raw) - s.y
    if mask is not None:
        err = err[mask]
    return float(np.sqrt(np.mean(err**2))) if err.size else float("nan")


def oos_k(s: OppSample, cap: float | None, raw: bool = False) -> tuple[float, int, list[float]]:
    """Leave-one-season-out: `k` fitted on the other seasons, scored (with the cap) on the held-out one; the summed
    squared error and count over every held-out row, and the per-fold `k`s."""
    sse, n, ks = 0.0, 0, []
    for yr in np.unique(s.season):
        test = s.season == yr
        if test.all():
            continue
        k = fit_k(s, ~test, raw)
        ks.append(k)
        err = (_opp_pred(s, k, cap, raw) - s.y)[test]
        sse += float((err**2).sum()); n += int(err.size)
    return sse, n, ks


def fit_opponent_position(s: OppSample, pos: str, cap: float = projections.OPPONENT_MULT_CAP, min_n: int = FIT_MIN_N) -> dict:
    """One position's row: the sample, the prior `k` and its out-of-sample error, no factor at all (k = 0), the `k`
    fitted on every season, the per-fold `k`s, the same fit on the unadjusted factor (`k_raw`, `rmse_raw`: whether the
    schedule adjustment earns its place), the error without the cap and the share of rows the cap binds on, `k` by the
    defense's games played, and the verdict: `fit` when the fitted `k` beats the prior out of sample on `min_n` rows or
    more, else `keep prior`."""
    prior_k = projections.OPPONENT_K.get(pos, 0.0)
    row = {"pos": pos, "n": s.n, "seasons": int(np.unique(s.season).size), "k_prior": prior_k, "cap": cap,
           "rmse_none": None, "rmse_prior": None, "k_fit": None, "rmse_fit": None, "rmse_nocap": None, "cap_binds": None,
           "k_raw": None, "rmse_raw": None, "k_folds": [], "k_by_def_games": {}, "fitted": False, "min_n": min_n}
    if not s.n:
        return row
    sse, n, ks = oos_k(s, cap)
    sse_nc, n_nc, _ = oos_k(s, None)
    sse_raw, n_raw, _ = oos_k(s, cap, raw=True)
    k = fit_k(s)
    m = 1.0 + k * (s.factor - 1.0)
    row.update(rmse_none=round(opp_rmse(s, 0.0, cap), 4), rmse_prior=round(opp_rmse(s, prior_k, cap), 4),
               k_fit=round(k, 3), rmse_fit=_rmse(sse, n), rmse_nocap=_rmse(sse_nc, n_nc),
               cap_binds=round(float(((m < 1.0 - cap) | (m > 1.0 + cap)).mean()), 3),
               k_raw=round(fit_k(s, raw=True), 3), rmse_raw=_rmse(sse_raw, n_raw), k_folds=[round(x, 3) for x in ks])
    for lo, hi in DEF_GAMES_BUCKETS:
        msk = (s.def_games >= lo) & (s.def_games <= hi)
        row["k_by_def_games"][f"{lo}-{hi}"] = (round(fit_k(s, msk), 3), int(msk.sum())) if msk.any() else (None, 0)
    row["fitted"] = s.n >= min_n and row["rmse_fit"] is not None and row["rmse_fit"] < row["rmse_prior"] - 1e-9
    return row


def fit_opponent(w: pl.DataFrame) -> dict:
    """Step 2 over FIT_POSITIONS: the opponent frame and `fit_opponent_position` for each."""
    df = opponent_frame(w)
    return {"rows": len(df), "weeks": [fit_opponent_position(OppSample.of(df, pos), pos) for pos in FIT_POSITIONS]}


# ---------- step 3: the implied team total ----------

# nflverse `schedules` keeps a franchise's code of the season (OAK, SD, STL); the weekly stats carry today's (LV, LAC, LA).
SCHEDULE_TEAM = {"OAK": "LV", "SD": "LAC", "STL": "LA"}


def implied_lines(sched: pl.DataFrame) -> pl.DataFrame:
    """Every team's implied total in every regular-season game with a closing line: `season`, `week`, `team`,
    `implied`. nflverse's `spread_line` is the home side's margin (positive = home favored), so the home side's
    implied total is `total / 2 + spread / 2`, the same number `sources/vegas.py` reads off ESPN's scoreboard (whose
    spread has the other sign). Teams read in the weekly stats' codes (SCHEDULE_TEAM)."""
    g = sched.filter((pl.col("game_type") == "REG") & pl.col("spread_line").is_not_null() & pl.col("total_line").is_not_null())
    cols = [pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)]
    home = g.select(cols + [pl.col("home_team").alias("team"), (pl.col("total_line") / 2 + pl.col("spread_line") / 2).alias("implied")])
    away = g.select(cols + [pl.col("away_team").alias("team"), (pl.col("total_line") / 2 - pl.col("spread_line") / 2).alias("implied")])
    return (pl.concat([home, away]).with_columns(pl.col("team").replace(SCHEDULE_TEAM))
              .sort(["season", "week", "team"]))


def schedules(seasons: Iterable[int] = FIT_SEASONS) -> pl.DataFrame:
    """nflverse `schedules` over the seasons (the network)."""
    return pl.concat([nflverse.schedules(int(s)) for s in seasons], how="vertical_relaxed")


def vegas_frame(w: pl.DataFrame, lines: pl.DataFrame, min_games: int = projections.OPPORTUNITY_MIN_GAMES,
                min_ppg: float = FIT_MIN_PPG) -> pl.DataFrame:
    """A row per player-game at which the live read would have priced his week (step 2's rows, without waiting on the
    defense's games): `ppg` over his games before it, `level` that moved toward his usage by the live
    `projections.opportunity_mult` (the adopted weight, clip and xFP; `w` needs the `xfp` column, `with_xfp`),
    `implied` his team's implied total that week, and `def_mult`, the opponent multiplier `blend` applies beside the
    implied total, at the adopted OPPONENT_K and cap, 1.0 where the defense had under OPPONENT_MIN_GAMES games through
    the week before (as the live read does). `pts` is the truth. A game with no closing line drops out.

    The base is `level`, not `ppg`: a hot start and his team's line rise together (the market reads the same box
    scores) and the start then regresses, so on raw `ppg` the implied total is fitted against the regression and
    reads near zero; the live number it multiplies is a projection, which has already regressed. The fit on `ppg` is
    printed beside it (`k_ppg`) so the reader sees the confound."""
    tg = usage.team_games(w)
    f = (factors_by_week(tg).rename({"team": "opp", "games": "def_games"}).select(["season", "opp", "pos", "week", "def_games", "factor"])
         .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    ln = lines.with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))
    g = (season_rows(w).filter((pl.col("games") >= min_games) & pl.col("team").is_not_null())
           .with_columns((pl.col("pts_before") / pl.col("games")).alias("ppg"), (pl.col("xfp_before") / pl.col("games")).alias("xfp_pg"),
                         pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))
           .filter(pl.col("ppg") >= min_ppg)
           .join(ln, on=["season", "week", "team"], how="inner")
           .join(f, on=["season", "opp", "pos", "week"], how="left"))
    k = pl.col("pos").replace_strict(projections.OPPONENT_K, default=0.0, return_dtype=pl.Float64)
    cap = projections.OPPONENT_MULT_CAP
    live = (1.0 + k * (pl.col("factor") - 1.0)).clip(1.0 - cap, 1.0 + cap)
    om = [projections.opportunity_mult(r["pos"], {"ppg": r["ppg"], "xfp_pg": r["xfp_pg"], "games": r["games"]})
          for r in g.select(["pos", "ppg", "xfp_pg", "games"]).iter_rows(named=True)]
    g = g.with_columns(pl.when(pl.col("def_games").fill_null(0) >= projections.OPPONENT_MIN_GAMES).then(live).otherwise(1.0).alias("def_mult"),
                       (pl.col("ppg") * pl.Series(om, dtype=pl.Float64)).alias("level"))
    return g.select(["season", "gsis_id", "pos", "week", "games", "ppg", "level", "team", "opp", "implied", "def_mult", pl.col("fpts").alias("pts")])


@dataclass
class VegasSample:
    """One position's implied-total rows as arrays: `season` for the folds, `ppg` his points a game so far and `level`
    that moved toward his usage, `implied` his team's total that week, `def_mult` the opponent multiplier already on
    the live number, `y` his points that week."""
    season: np.ndarray
    ppg: np.ndarray
    level: np.ndarray
    implied: np.ndarray
    def_mult: np.ndarray
    y: np.ndarray

    @classmethod
    def of(cls, df: pl.DataFrame, pos: str) -> VegasSample:
        d = df.filter(pl.col("pos") == pos)
        return cls(d["season"].to_numpy(), d["ppg"].to_numpy().astype(float), d["level"].to_numpy().astype(float),
                   d["implied"].to_numpy().astype(float), d["def_mult"].to_numpy().astype(float), d["pts"].to_numpy().astype(float))

    @property
    def n(self) -> int:
        return int(self.y.size)


def _vbase(s: VegasSample, on_ppg: bool = False) -> np.ndarray:
    """The number the implied total multiplies: `level` (or raw `ppg`) times the opponent multiplier."""
    return (s.ppg if on_ppg else s.level) * s.def_mult


def _vx(s: VegasSample, avg: float, on_ppg: bool = False) -> np.ndarray:
    """The regressor: `base * (implied / avg - 1)`, so the live `base * (1 + k * (implied / avg - 1))` is `base + k * x`
    (`blend` multiplies the implied-total and opponent terms onto one number; the order does not matter)."""
    return _vbase(s, on_ppg) * (s.implied / avg - 1.0)


def fit_vegas_k(s: VegasSample, mask: np.ndarray | None = None, avg: float = projections.LEAGUE_AVG_IMPLIED,
                on_ppg: bool = False) -> float:
    """The least-squares `k`, closed form, held to K_BOUNDS (a negative `k` would score a player down in a shootout).
    `on_ppg` fits it on raw `ppg` instead of `level`, for the reader. `mask` picks the training rows."""
    x = _vx(s, avg, on_ppg)
    y = s.y - _vbase(s, on_ppg)
    if mask is not None:
        x, y = x[mask], y[mask]
    den = float((x * x).sum())
    if den <= 0:
        return 0.0
    return float(np.clip((x * y).sum() / den, *K_BOUNDS))


def vegas_rmse(s: VegasSample, k: float, avg: float = projections.LEAGUE_AVG_IMPLIED, mask: np.ndarray | None = None) -> float:
    err = _vbase(s) + k * _vx(s, avg) - s.y
    if mask is not None:
        err = err[mask]
    return float(np.sqrt(np.mean(err**2))) if err.size else float("nan")


def oos_vegas(s: VegasSample, avg: float = projections.LEAGUE_AVG_IMPLIED) -> tuple[float, int, list[float]]:
    """Leave-one-season-out: `k` fitted on the other seasons, scored on the held-out one (the live shape: `level`
    times the opponent multiplier); the summed squared error and count over every held-out row, and the per-fold `k`s."""
    sse, n, ks = 0.0, 0, []
    for yr in np.unique(s.season):
        test = s.season == yr
        if test.all():
            continue
        k = fit_vegas_k(s, ~test, avg)
        ks.append(k)
        err = (_vbase(s) + k * _vx(s, avg) - s.y)[test]
        sse += float((err**2).sum()); n += int(err.size)
    return sse, n, ks


def fit_vegas_position(s: VegasSample, pos: str, avg: float = projections.LEAGUE_AVG_IMPLIED, min_n: int = FIT_MIN_N) -> dict:
    """One position's row: the sample, the prior `k` (VEGAS_K) and its error, no implied total at all (k = 0), the `k`
    fitted on every season and its out-of-sample error, the per-fold `k`s, `k_ppg` (the same fit on raw `ppg`: the
    regression confound `vegas_frame` explains), the sample's mean implied total (against LEAGUE_AVG_IMPLIED, the
    centre the term reads around), and the verdict: `fit` when the fitted `k` beats the prior out of sample on `min_n`
    rows or more, else `keep prior`."""
    prior_k = projections.VEGAS_K.get(pos, 0.0)
    row = {"pos": pos, "n": s.n, "seasons": int(np.unique(s.season).size), "k_prior": prior_k, "avg": avg,
           "rmse_none": None, "rmse_prior": None, "k_fit": None, "rmse_fit": None, "k_ppg": None, "k_folds": [],
           "mean_implied": None, "fitted": False, "min_n": min_n}
    if not s.n:
        return row
    sse, n, ks = oos_vegas(s, avg)
    row.update(rmse_none=round(vegas_rmse(s, 0.0, avg), 4), rmse_prior=round(vegas_rmse(s, prior_k, avg), 4),
               k_fit=round(fit_vegas_k(s, avg=avg), 3), rmse_fit=_rmse(sse, n), k_ppg=round(fit_vegas_k(s, avg=avg, on_ppg=True), 3),
               k_folds=[round(x, 3) for x in ks], mean_implied=round(float(s.implied.mean()), 2))
    row["fitted"] = s.n >= min_n and row["rmse_fit"] is not None and row["rmse_fit"] < row["rmse_prior"] - 1e-9
    return row


def fit_vegas(w: pl.DataFrame, lines: pl.DataFrame) -> dict:
    """Step 3 over FIT_POSITIONS: the implied-total frame and `fit_vegas_position` for each, and the mean implied
    total of every team-game with a line (the league's, against LEAGUE_AVG_IMPLIED). `w` carries `xfp` (`with_xfp`)."""
    df = vegas_frame(w, lines)
    return {"rows": len(df), "league_implied": round(float(lines["implied"].mean()), 2) if len(lines) else None,
            "weeks": [fit_vegas_position(VegasSample.of(df, pos), pos) for pos in FIT_POSITIONS]}


# ---------- step 4: the recent-usage trend ----------

def trend_frame(w: pl.DataFrame, min_games: int = projections.OPPORTUNITY_MIN_GAMES, min_after: int = FIT_MIN_GAMES_AFTER,
                min_ppg: float = FIT_MIN_PPG) -> pl.DataFrame:
    """Step 1's rows (`w` carries `xfp`, `with_xfp`) with the trend on them: `recent_pg`, his xFP-lite a game over the
    last RECENT_GAMES games before the week (all of them under that many, so the ratio reads 1), `ratio` that over
    `xfp_pg` held to OPPORTUNITY_RATIO_CLIP as the live `trend_mult` holds it, and `level`, `ppg` moved toward his usage
    by the live `opportunity_mult` with the trend off (the base the term multiplies). `future_ppg` is the truth."""
    g = season_rows(w).filter((pl.col("games") >= min_games) & (pl.col("games_after") >= min_after)).with_columns([
        (pl.col("pts_before") / pl.col("games")).alias("ppg"),
        (pl.col("xfp_before") / pl.col("games")).alias("xfp_pg"),
        (pl.col("xfp_recent") / pl.min_horizontal(pl.col("games"), pl.lit(projections.RECENT_GAMES))).alias("recent_pg"),
        ((pl.col("pts_total") - pl.col("pts_before")) / pl.col("games_after")).alias("future_ppg"),
    ]).filter((pl.col("ppg") >= min_ppg) & (pl.col("xfp_pg") > 0))
    lo, hi = projections.OPPORTUNITY_RATIO_CLIP
    om = [projections.opportunity_mult(r["pos"], {"ppg": r["ppg"], "xfp_pg": r["xfp_pg"], "games": r["games"]})
          for r in g.select(["pos", "ppg", "xfp_pg", "games"]).iter_rows(named=True)]
    g = g.with_columns((pl.col("recent_pg") / pl.col("xfp_pg")).clip(lo, hi).alias("ratio"),
                       (pl.col("ppg") * pl.Series(om, dtype=pl.Float64)).alias("level"))
    return g.select(["season", "gsis_id", "pos", "week", "games", "ppg", "xfp_pg", "recent_pg", "ratio", "level", "games_after", "future_ppg"])


@dataclass
class TrendSample:
    """One position's trend rows as arrays: `season` for the folds, `games` so far, `level` the opportunity-moved
    level, `ratio` the recent-usage ratio, `y` his points a game over the rest of the season."""
    season: np.ndarray
    games: np.ndarray
    level: np.ndarray
    ratio: np.ndarray
    y: np.ndarray

    @classmethod
    def of(cls, df: pl.DataFrame, pos: str) -> TrendSample:
        d = df.filter(pl.col("pos") == pos)
        return cls(d["season"].to_numpy(), d["games"].to_numpy().astype(int), d["level"].to_numpy().astype(float),
                   d["ratio"].to_numpy().astype(float), d["future_ppg"].to_numpy().astype(float))

    @property
    def n(self) -> int:
        return int(self.y.size)


def fit_t(s: TrendSample, mask: np.ndarray | None = None) -> float:
    """The least-squares `t`, closed form (`level * (1 + t * (ratio - 1))` is `level + t * x`, `x = level * (ratio - 1)`),
    held to T_BOUNDS. `mask` picks the training rows."""
    x = s.level * (s.ratio - 1.0)
    y = s.y - s.level
    if mask is not None:
        x, y = x[mask], y[mask]
    den = float((x * x).sum())
    if den <= 0:
        return 0.0
    return float(np.clip((x * y).sum() / den, *T_BOUNDS))


def _trend_err(s: TrendSample, t: float) -> np.ndarray:
    return s.level * (1.0 + t * (s.ratio - 1.0)) - s.y


def oos_trend(s: TrendSample) -> tuple[float, int, list[float]]:
    """Leave-one-season-out: `t` fitted on the other seasons, scored on the held-out one; the summed squared error and
    count over every held-out row, and the per-fold `t`s."""
    sse, n, ts = 0.0, 0, []
    for yr in np.unique(s.season):
        test = s.season == yr
        if test.all():
            continue
        t = fit_t(s, ~test)
        ts.append(t)
        err = _trend_err(s, t)[test]
        sse += float((err**2).sum()); n += int(err.size)
    return sse, n, ts


def fit_trend_position(s: TrendSample, pos: str, min_n: int = FIT_MIN_N) -> dict:
    """One position's row: the sample, the prior `t` (TREND_K) and its error in place, no trend (t = 0), the `t` fitted
    on every season and its out-of-sample error, the per-fold `t`s, the share of rows whose ratio is off 1 by 10% or
    more (how often the term moves anyone), `t` by games played, and the verdict: `fit` when the fitted `t` beats the
    prior out of sample on `min_n` rows or more, else `keep prior`."""
    prior_t = projections.TREND_K.get(pos, 0.0)
    row = {"pos": pos, "n": s.n, "seasons": int(np.unique(s.season).size), "t_prior": prior_t, "rmse_none": None,
           "rmse_prior": None, "t_fit": None, "rmse_fit": None, "t_folds": [], "moved": None, "t_by_games": {},
           "fitted": False, "min_n": min_n}
    if not s.n:
        return row
    sse, n, ts = oos_trend(s)
    row.update(rmse_none=_rmse(float((_trend_err(s, 0.0) ** 2).sum()), s.n), rmse_prior=_rmse(float((_trend_err(s, prior_t) ** 2).sum()), s.n),
               t_fit=round(fit_t(s), 3), rmse_fit=_rmse(sse, n), t_folds=[round(x, 3) for x in ts],
               moved=round(float((np.abs(s.ratio - 1.0) >= 0.1).mean()), 3))
    for lo, hi in TREND_GAMES_BUCKETS:
        m = (s.games >= lo) & (s.games <= hi)
        row["t_by_games"][f"{lo}-{hi}"] = (round(fit_t(s, m), 3), int(m.sum())) if m.any() else (None, 0)
    row["fitted"] = s.n >= min_n and row["rmse_fit"] is not None and row["rmse_fit"] < row["rmse_prior"] - 1e-9
    return row


def fit_trend(w: pl.DataFrame) -> dict:
    """Step 4 over FIT_POSITIONS: the trend frame and `fit_trend_position` for each. `w` carries `xfp` (`with_xfp`)."""
    df = trend_frame(w)
    return {"rows": len(df), "weeks": [fit_trend_position(TrendSample.of(df, pos), pos) for pos in FIT_POSITIONS]}


def fit_attempt_value(w: pl.DataFrame, carry: float = usage.XFP_PER_CARRY) -> dict:
    """The PPR points a pass attempt is worth at the league average: QB weeks with an attempt, points less `carry` a
    carry, least squares through the origin on attempts (`per_attempt`, with its per-season range). `joint` is the
    two-term fit (attempts and carries free) for information: what a QB carry is worth when it is not held at the
    rusher's value."""
    q = w.filter((pl.col("pos") == "QB") & (pl.col("attempts").fill_null(0) > 0))
    att = q["attempts"].fill_null(0).to_numpy().astype(float)
    car = q["carries"].fill_null(0).to_numpy().astype(float)
    pts = q["fpts_ppr"].fill_null(0).to_numpy().astype(float)
    if not att.size or float((att * att).sum()) <= 0:
        return {"per_attempt": None, "n": 0, "by_season": {}, "joint": None, "rmse": None}
    y = pts - carry * car
    a = float((att * y).sum() / (att * att).sum())
    by_season = {}
    for yr in np.unique(q["season"].to_numpy()):
        m = q["season"].to_numpy() == yr
        by_season[int(yr)] = round(float((att[m] * y[m]).sum() / (att[m] * att[m]).sum()), 3)
    X = np.column_stack([att, car])
    joint, *_ = np.linalg.lstsq(X, pts, rcond=None)
    return {"per_attempt": round(a, 3), "n": int(att.size), "by_season": by_season,
            "joint": {"per_attempt": round(float(joint[0]), 3), "per_carry": round(float(joint[1]), 3)},
            "rmse": round(float(np.sqrt(np.mean((att * a - y) ** 2))), 3)}


def refit_opportunity_values(w: pl.DataFrame) -> dict[str, dict]:
    """For information only: per position, the per-target, per-carry and per-air-yard values a least-squares fit of
    weekly PPR points on the week's opportunities gives, next to the hand-set constants."""
    out = {}
    for pos in ("RB", "WR", "TE"):
        q = w.filter(pl.col("pos") == pos)
        X = np.column_stack([q[c].fill_null(0).to_numpy().astype(float) for c in ("targets", "carries", "air_yards")])
        y = q["fpts_ppr"].fill_null(0).to_numpy().astype(float)
        if not y.size:
            continue
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        out[pos] = {"n": int(y.size), "per_target": round(float(coef[0]), 3), "per_carry": round(float(coef[1]), 3),
                    "per_air_yard": round(float(coef[2]), 4)}
    return out


def run(seasons: Iterable[int] = FIT_SEASONS) -> dict:
    """Everything `ff fit-opportunity` prints: the attempt value first, then the weight rows on a training frame that
    prices attempts at that value (the pair is adopted together), the per-opportunity refit for information, the
    opponent factor (step 2), the implied total (step 3) and the recent-usage trend (step 4, at the adopted weight and clip)."""
    w = weekly(seasons)
    attempt = fit_attempt_value(w)
    df = training_frame(with_xfp(w, attempt["per_attempt"]))
    return {"seasons": [int(s) for s in seasons], "rows": len(df), "attempt": attempt, "values": refit_opportunity_values(w),
            **fit_weights(df), "opponent": fit_opponent(w), "vegas": fit_vegas(with_xfp(w), implied_lines(schedules(seasons))),
            "trend": fit_trend(with_xfp(w))}
