"""Usage / opportunity metrics from nflverse weekly stats: target share, TPRR proxy, red-zone, xFP-lite."""
from __future__ import annotations

import polars as pl

from ..sources import nflverse

# xFP-lite: what a season's opportunities are worth at league-average PPR values, so a player's points over or under
# them can be read as luck to regress (`projections.opportunity_mult`). A target and a carry were set by hand
# (2026-09, the public per-opportunity averages), the air-yard bonus likewise; the pass attempt is fitted
# (`ff fit-opportunity`, `opfit.fit_attempt_value`): QB weeks of 2016-2025, points less XFP_PER_CARRY a carry, least
# squares through the origin. The fitter prints the per-target and per-carry refit next to these for information only
# (a per-position value is ROADMAP item 3, the proper xFP; `docs/plans/fitted-projection.md`).
XFP_PER_TARGET = 1.55
XFP_PER_CARRY = 0.62
XFP_PER_AIR_YARD = 0.02
XFP_PER_ATTEMPT = 0.415   # fitted 2026-10-21 on 5,992 QB weeks of 2016-2025 (0.39-0.45 by season); was 0 (QB read 1.0)


def xfp_lite_expr(per_attempt: float | None = None) -> pl.Expr:
    """The xFP-lite expression over summed `targets`, `carries`, `air_yards` and `attempts` columns; one formula for
    the season summary and the fitter's training frame, so the live read and the fit price the same thing.
    `per_attempt` overrides XFP_PER_ATTEMPT (the fitter prices attempts at the value it has just fitted)."""
    att = XFP_PER_ATTEMPT if per_attempt is None else per_attempt
    return (pl.col("targets").fill_null(0) * XFP_PER_TARGET + pl.col("carries").fill_null(0) * XFP_PER_CARRY
            + pl.col("air_yards").fill_null(0) * XFP_PER_AIR_YARD + pl.col("attempts").fill_null(0) * att)


def _col(df: pl.DataFrame, *names: str) -> str | None:
    for n in names:
        if n in df.columns:
            return n
    return None


def weekly_usage(season: int, through_week: int | None = None) -> pl.DataFrame:
    """Per player per week: targets, target_share, air-yards share, carries, rz touches, receptions, fantasy pts."""
    st = nflverse.player_stats(season)
    if through_week:
        st = st.filter(pl.col("week") <= through_week)
    st = st.filter(pl.col("season_type") == "REG") if "season_type" in st.columns else st
    pid = _col(st, "player_id", "gsis_id")
    name = _col(st, "player_display_name", "player_name")
    team = _col(st, "team", "recent_team")
    pos = _col(st, "position")
    cols = {
        "targets": _col(st, "targets"), "receptions": _col(st, "receptions"), "rec_yards": _col(st, "receiving_yards"),
        "air_yards": _col(st, "receiving_air_yards"), "carries": _col(st, "carries"), "rush_yards": _col(st, "rushing_yards"),
        "attempts": _col(st, "attempts"),
        "tgt_share": _col(st, "target_share"), "ay_share": _col(st, "air_yards_share"),
        "fpts_ppr": _col(st, "fantasy_points_ppr"), "fpts": _col(st, "fantasy_points"),
        "rec_td": _col(st, "receiving_tds"), "rush_td": _col(st, "rushing_tds"),
        "opp": _col(st, "opponent_team"),
    }
    sel = [pl.col(pid).alias("gsis_id"), pl.col(name).alias("name"), pl.col(team).alias("team"), pl.col(pos).alias("pos"), pl.col("week")]
    for k, c in cols.items():
        sel.append((pl.col(c) if c else pl.lit(None)).alias(k))
    df = st.select(sel)
    return df


# The positions the opponent factor prices (nflverse has no kicks, and a D/ST is the defense); K and D/ST read 1.0.
FACTOR_POSITIONS = ("QB", "RB", "WR", "TE")
# ESPN's team abbreviations where nflverse's differ (the scoreboard's `opp` is ESPN's; the stats' `opponent_team` is nflverse's).
NFLVERSE_TEAM = {"LAR": "LA", "WSH": "WAS"}


def nfl_team(abbrev: str | None) -> str | None:
    """nflverse's abbreviation for an ESPN team abbreviation (LAR -> LA, WSH -> WAS, the rest unchanged)."""
    return NFLVERSE_TEAM.get(abbrev, abbrev) if abbrev else None


def team_games(w: pl.DataFrame) -> pl.DataFrame:
    """One row per team-game and position over the weekly rows: `week`, `team` (the offense), `opp` (the defense),
    `pos` and `pts`, the PPR points the offense's players at that position scored in that game, 0 when none of them
    had a stat row (a game is any week a team has a row for, so a bye is no game). `season` is carried when present."""
    keys = (["season"] if "season" in w.columns else []) + ["week", "team", "opp"]
    rows = w.filter(pl.col("team").is_not_null() & pl.col("opp").is_not_null())
    games = rows.select(keys).unique()
    grid = games.join(pl.DataFrame({"pos": list(FACTOR_POSITIONS)}), how="cross")
    pts = (rows.filter(pl.col("pos").is_in(FACTOR_POSITIONS)).group_by(keys + ["pos"])
               .agg(pl.col("fpts_ppr").fill_null(0.0).sum().alias("pts")))
    return grid.join(pts, on=keys + ["pos"], how="left").with_columns(pl.col("pts").fill_null(0.0)).sort(keys + ["pos"])


def opponent_factors(tg: pl.DataFrame, through_week: int | None = None) -> pl.DataFrame:
    """Each defense's points-allowed factor per position over the team-games through `through_week` (every week when
    None): `games` it has played, `allowed_pg` (PPR points a game the position scored against it), `raw` (that over
    the league's average team-game at the position) and `factor`, the schedule-adjusted one: `allowed_pg` over what
    those offenses scored a game at the position in their other games (one pass of adjustment; an offense with no
    other game reads the league average). A defense with no game yet has no row; a factor whose expectation is zero
    reads 1.0. `season` is carried when present and the league average is per season."""
    g = tg.filter(pl.col("week") <= through_week) if through_week is not None else tg
    by = (["season"] if "season" in g.columns else [])
    if g.is_empty():
        return pl.DataFrame({c: [] for c in by + ["team", "pos", "games", "allowed_pg", "expected_pg", "raw", "factor"]})
    g = g.with_columns([
        pl.col("pts").mean().over(by + ["pos"]).alias("league_pg"),
        pl.col("pts").sum().over(by + ["team", "pos"]).alias("off_pts"),
        pl.len().over(by + ["team", "pos"]).alias("off_games"),
    ]).with_columns(
        pl.when(pl.col("off_games") > 1).then((pl.col("off_pts") - pl.col("pts")) / (pl.col("off_games") - 1))
          .otherwise(pl.col("league_pg")).alias("elsewhere"))
    out = g.group_by(by + ["opp", "pos"]).agg([
        pl.len().cast(pl.Int64).alias("games"), pl.col("pts").mean().alias("allowed_pg"),
        pl.col("elsewhere").mean().alias("expected_pg"), pl.col("league_pg").first().alias("league_pg"),
    ]).rename({"opp": "team"})
    return out.with_columns([
        pl.when(pl.col("league_pg") > 0).then(pl.col("allowed_pg") / pl.col("league_pg")).otherwise(1.0).alias("raw"),
        pl.when(pl.col("expected_pg") > 0).then(pl.col("allowed_pg") / pl.col("expected_pg")).otherwise(1.0).alias("factor"),
    ]).drop("league_pg").sort(by + ["pos", "team"])


def opponent_factor_index(season: int, through_week: int) -> dict[tuple[str, str], dict]:
    """The live read: (nflverse defense, pos) -> {factor, raw, games, allowed_pg} over the season's games through
    `through_week` (the week before the one being priced: the week's own box score never enters the factor).
    Empty before the first week."""
    if through_week < 1:
        return {}
    f = opponent_factors(team_games(weekly_usage(season, through_week)))
    return {(r["team"], r["pos"]): {"factor": round(r["factor"], 3), "raw": round(r["raw"], 3), "games": int(r["games"]),
                                    "allowed_pg": round(r["allowed_pg"], 2)} for r in f.iter_rows(named=True)}


def season_summary(season: int, through_week: int | None = None) -> pl.DataFrame:
    """Aggregate usage with an expected-points-lite: opportunity-weighted expectation vs actual (FPOE-lite)."""
    w = weekly_usage(season, through_week)
    g = w.group_by(["gsis_id", "name", "team", "pos"]).agg([
        pl.col("week").n_unique().alias("games"),
        pl.col("targets").sum().alias("targets"), pl.col("receptions").sum().alias("rec"),
        pl.col("air_yards").sum().alias("air_yards"), pl.col("carries").sum().alias("carries"),
        pl.col("attempts").sum().alias("attempts"),
        pl.col("tgt_share").mean().alias("tgt_share"), pl.col("ay_share").mean().alias("ay_share"),
        pl.col("fpts_ppr").sum().alias("fpts_ppr"), (pl.col("rec_td").sum() + pl.col("rush_td").sum()).alias("tds"),
    ])
    g = g.with_columns([xfp_lite_expr().alias("xfp_lite")]).with_columns([
        (pl.col("fpts_ppr") - pl.col("xfp_lite")).alias("fpoe_lite"),
        (pl.col("targets").fill_null(0) / pl.col("games")).alias("tgt_pg"),
        (pl.col("carries").fill_null(0) / pl.col("games")).alias("carry_pg"),
        (pl.col("attempts").fill_null(0) / pl.col("games")).alias("att_pg"),
        (pl.col("fpts_ppr") / pl.col("games")).alias("ppg"),
    ])
    return g.sort("xfp_lite", descending=True)


def signals(summary: pl.DataFrame) -> dict[str, dict]:
    """gsis_id -> buy_low / sell_high / usage flags, and the per-game numbers `projections.opportunity_mult` reads
    (`games`, `ppg`, `xfp_pg`, both PPR; their ratio is what moves a rest-of-season level)."""
    out = {}
    for r in summary.iter_rows(named=True):
        flags = []
        if r["games"] and r["games"] >= 1:
            if r["fpoe_lite"] is not None and r["fpoe_lite"] < -6 and r["xfp_lite"] > 12 * r["games"]:
                flags.append("buy_low: usage >> production")
            if r["fpoe_lite"] is not None and r["fpoe_lite"] > 8 and r["tds"] and r["tds"] / r["games"] >= 1.0:
                flags.append("sell_high: TD-dependent")
            if r["tgt_share"] is not None and r["tgt_share"] >= 0.25:
                flags.append(f"target_share {r['tgt_share']:.0%}")
            if r["carry_pg"] and r["carry_pg"] >= 15:
                flags.append(f"bellcow {r['carry_pg']:.0f} carries/g")
        out[r["gsis_id"]] = {"flags": flags, "games": int(r["games"] or 0),
                             "ppg": round(r["ppg"] or 0, 1), "xfp_pg": round((r["xfp_lite"] or 0) / max(r["games"], 1), 1),
                             "tgt_share": r["tgt_share"], "tgt_pg": round(r["tgt_pg"] or 0, 1), "carry_pg": round(r["carry_pg"] or 0, 1),
                             "att_pg": round(r["att_pg"] or 0, 1)}
    return out
