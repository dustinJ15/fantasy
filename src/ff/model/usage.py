"""Usage / opportunity metrics from nflverse weekly stats: target share, TPRR proxy, red-zone, xFP-lite."""
from __future__ import annotations

import polars as pl

from ..sources import nflverse


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
        "tgt_share": _col(st, "target_share"), "ay_share": _col(st, "air_yards_share"),
        "fpts_ppr": _col(st, "fantasy_points_ppr"), "fpts": _col(st, "fantasy_points"),
        "rec_td": _col(st, "receiving_tds"), "rush_td": _col(st, "rushing_tds"),
    }
    sel = [pl.col(pid).alias("gsis_id"), pl.col(name).alias("name"), pl.col(team).alias("team"), pl.col(pos).alias("pos"), pl.col("week")]
    for k, c in cols.items():
        sel.append((pl.col(c) if c else pl.lit(None)).alias(k))
    df = st.select(sel)
    return df


def season_summary(season: int, through_week: int | None = None) -> pl.DataFrame:
    """Aggregate usage with an expected-points-lite: opportunity-weighted expectation vs actual (FPOE-lite)."""
    w = weekly_usage(season, through_week)
    g = w.group_by(["gsis_id", "name", "team", "pos"]).agg([
        pl.col("week").n_unique().alias("games"),
        pl.col("targets").sum().alias("targets"), pl.col("receptions").sum().alias("rec"),
        pl.col("air_yards").sum().alias("air_yards"), pl.col("carries").sum().alias("carries"),
        pl.col("tgt_share").mean().alias("tgt_share"), pl.col("ay_share").mean().alias("ay_share"),
        pl.col("fpts_ppr").sum().alias("fpts_ppr"), (pl.col("rec_td").sum() + pl.col("rush_td").sum()).alias("tds"),
    ])
    # xFP-lite: league-average PPR value per opportunity (target ~1.55 pts, carry ~0.6 pts) + air-yard bonus.
    g = g.with_columns([
        (pl.col("targets").fill_null(0) * 1.55 + pl.col("carries").fill_null(0) * 0.62 + pl.col("air_yards").fill_null(0) * 0.02).alias("xfp_lite"),
    ]).with_columns([
        (pl.col("fpts_ppr") - pl.col("xfp_lite")).alias("fpoe_lite"),
        (pl.col("targets").fill_null(0) / pl.col("games")).alias("tgt_pg"),
        (pl.col("carries").fill_null(0) / pl.col("games")).alias("carry_pg"),
        (pl.col("fpts_ppr") / pl.col("games")).alias("ppg"),
    ])
    return g.sort("xfp_lite", descending=True)


def signals(summary: pl.DataFrame) -> dict[str, dict]:
    """gsis_id -> buy_low / sell_high / usage flags."""
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
        out[r["gsis_id"]] = {"flags": flags, "ppg": round(r["ppg"] or 0, 1), "xfp_pg": round((r["xfp_lite"] or 0) / max(r["games"], 1), 1),
                             "tgt_share": r["tgt_share"], "tgt_pg": round(r["tgt_pg"] or 0, 1), "carry_pg": round(r["carry_pg"] or 0, 1)}
    return out
