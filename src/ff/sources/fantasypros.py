"""FantasyPros consensus via the dynastyprocess/data daily mirror (no scraping)."""
from __future__ import annotations

import polars as pl
import requests

from ..cache import DAY, cached_bytes

BASE = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/"


def _get(name: str) -> bytes:
    r = requests.get(BASE + name, timeout=60, headers={"User-Agent": "ff-comanager/0.1"})
    r.raise_for_status()
    return r.content


def weekly_ecr(force: bool = False) -> pl.DataFrame:
    """Weekly ECR: rank, ecr, sd, best, worst, pos_rank, r2p_pts (projected pts), start_sit_grade."""
    p = cached_bytes("fp_latest_weekly", DAY / 2, lambda: _get("fp_latest_weekly.csv"), ext="csv", force=force)
    return pl.read_csv(p, infer_schema_length=10000, ignore_errors=True)


def player_ids(force: bool = False) -> pl.DataFrame:
    """Cross-platform ID crosswalk (espn_id, gsis_id, sleeper_id, fantasypros_id, ...)."""
    p = cached_bytes("db_playerids", 7 * DAY, lambda: _get("db_playerids.csv"), ext="csv", force=force)
    return pl.read_csv(p, infer_schema_length=10000, ignore_errors=True)
