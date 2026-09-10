"""nflverse loads via nflreadpy. Polars frames. Uses the live `stats_player` release."""
from __future__ import annotations

import nflreadpy as nfl
import polars as pl


def player_stats(season: int) -> pl.DataFrame:
    return nfl.load_player_stats(seasons=[season])


def pbp(season: int) -> pl.DataFrame:
    return nfl.load_pbp(seasons=[season])


def injuries(season: int) -> pl.DataFrame:
    return nfl.load_injuries(seasons=[season])


def depth_charts(season: int) -> pl.DataFrame:
    return nfl.load_depth_charts(seasons=[season])


def rosters(season: int) -> pl.DataFrame:
    return nfl.load_rosters(seasons=[season])


def schedules(season: int) -> pl.DataFrame:
    return nfl.load_schedules(seasons=[season])


def snap_counts(season: int) -> pl.DataFrame | None:
    try:
        return nfl.load_snap_counts(seasons=[season])
    except Exception:
        return None


def current_week(season: int) -> int:
    """Highest week with a completed game, plus one if the following week has started."""
    s = schedules(season)
    done = s.filter(pl.col("result").is_not_null())
    if done.is_empty():
        return 1
    return int(done["week"].max()) + 1 if done["week"].max() < s["week"].max() else int(done["week"].max())
