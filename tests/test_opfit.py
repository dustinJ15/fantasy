"""The opportunity-weight fitter (D10 step 1): the training frame reads a player's season so far against the rest of it
with no actual read before the week it is priced at, the closed-form weight recovers a known truth and stays a share,
one clip is chosen for every position, and the pass-attempt value is the least-squares one. Synthetic frames; the
network is never touched."""
import numpy as np
import polars as pl
import pytest

from ff import opfit
from ff.model import projections, usage


def _weekly(rows: list[dict]) -> pl.DataFrame:
    """Rows of (season, gsis_id, pos, week, fpts_ppr, targets, carries, air_yards, attempts)."""
    base = {"season": 2024, "gsis_id": "p", "pos": "WR", "fpts_ppr": 0.0, "targets": 0, "carries": 0, "air_yards": 0, "attempts": 0}
    return pl.DataFrame([{**base, **r} for r in rows]).with_columns(pl.col("fpts_ppr").cast(pl.Float64))


def test_training_frame_reads_the_season_so_far_against_the_rest_with_no_look_ahead():
    """Six games of 10, 20, 30, 10, 20, 30 on 10 targets each (xFP 15.5 a game): at his fourth game he has 3 games
    at 20 a game behind him and 3 at 20 ahead; the first two games (under OPPORTUNITY_MIN_GAMES before) and the last
    two (under FIT_MIN_GAMES_AFTER after) are not rows. A bye is not a game."""
    pts = [10.0, 20.0, 30.0, 10.0, 20.0, 30.0]
    weeks = [1, 2, 3, 5, 6, 7]   # week 4 the bye
    w = _weekly([{"week": wk, "fpts_ppr": p, "targets": 10} for wk, p in zip(weeks, pts)])
    df = opfit.training_frame(opfit.with_xfp(w))
    assert df["week"].to_list() == [3, 5]
    at5 = df.filter(pl.col("week") == 5).row(0, named=True)
    assert at5["games"] == 3 and at5["games_after"] == 3
    assert at5["ppg"] == pytest.approx(20.0) and at5["xfp_pg"] == pytest.approx(10 * usage.XFP_PER_TARGET)
    assert at5["future_ppg"] == pytest.approx(20.0)   # games 4-6, never game 3's 30
    at3 = df.filter(pl.col("week") == 3).row(0, named=True)
    assert at3["games"] == 2 and at3["ppg"] == pytest.approx(15.0) and at3["future_ppg"] == pytest.approx(22.5)


def test_training_frame_drops_the_tail_and_the_positions_the_read_never_prices():
    w = _weekly([{"gsis_id": "k", "pos": "K", "week": wk, "fpts_ppr": 9.0, "targets": 5} for wk in range(1, 8)]
                + [{"gsis_id": "tail", "pos": "RB", "week": wk, "fpts_ppr": 2.0, "carries": 3} for wk in range(1, 8)]
                + [{"gsis_id": "rb", "pos": "RB", "week": wk, "fpts_ppr": 12.0, "carries": 15} for wk in range(1, 8)])
    df = opfit.training_frame(opfit.with_xfp(w))
    assert set(df["gsis_id"].to_list()) == {"rb"}   # the kicker is no FIT_POSITIONS, the tail is under FIT_MIN_PPG


def _sample(w_true: float, n: int = 4000, seed: int = 0, noise: float = 0.0, seasons: int = 5) -> opfit.Sample:
    rng = np.random.default_rng(seed)
    ppg = rng.uniform(6.0, 25.0, n)
    xfp = ppg * rng.uniform(0.6, 1.5, n)
    y = ppg * (1 - w_true) + w_true * xfp + rng.normal(0.0, noise, n)
    return opfit.Sample(np.repeat(np.arange(2020, 2020 + seasons), n // seasons), np.full(n, 5), ppg, xfp, y)


def test_fit_w_recovers_the_truth_and_stays_a_share():
    assert opfit.fit_w(_sample(1.0), opfit.NO_CLIP) == pytest.approx(1.0)     # the future is the usage
    assert opfit.fit_w(_sample(0.0), opfit.NO_CLIP) == pytest.approx(0.0)     # the future is the past
    assert opfit.fit_w(_sample(0.35, noise=3.0), opfit.NO_CLIP) == pytest.approx(0.35, abs=0.03)
    s = _sample(0.0)
    s.y = 2 * s.ppg - s.xfp_pg   # away from his usage: a negative weight would fit, the share is held at 0
    assert opfit.fit_w(s, opfit.NO_CLIP) == 0.0
    s = _sample(1.0)
    s.y = 2 * s.xfp_pg - s.ppg   # past his usage: held at 1
    assert opfit.fit_w(s, opfit.NO_CLIP) == 1.0


def test_oos_fits_each_fold_on_the_other_seasons_and_the_verdict_is_against_the_prior():
    s = _sample(0.8, noise=2.0)
    sse, n, ws = opfit.oos(s, opfit.NO_CLIP)
    assert n == s.n and len(ws) == 5 and all(abs(w - 0.8) < 0.05 for w in ws)
    row = opfit.fit_position(s, "RB", opfit.NO_CLIP, min_n=100)
    assert row["fitted"] and row["w_fit"] == pytest.approx(0.8, abs=0.03) and row["rmse_fit"] < row["rmse_prior"] < row["rmse_none"]
    assert set(row["w_by_games"]) == {f"{lo}-{hi}" for lo, hi in opfit.GAMES_BUCKETS} and row["w_by_games"]["4-6"][1] == s.n
    # the prior's own truth: the fit cannot beat it out of sample, so the verdict keeps it
    prior = _sample(projections.OPPORTUNITY_WEIGHT["RB"], noise=2.0, seed=1)
    kept = opfit.fit_position(prior, "RB", projections.OPPORTUNITY_RATIO_CLIP, min_n=100)
    assert abs(kept["w_fit"] - projections.OPPORTUNITY_WEIGHT["RB"]) < 0.03 and kept["rmse_fit"] >= kept["rmse_prior"] - 0.01
    thin = opfit.fit_position(_sample(0.8, n=200, noise=2.0), "WR", opfit.NO_CLIP, min_n=1000)
    assert not thin["fitted"] and thin["w_fit"] is not None   # shown, not adopted


def test_choose_clip_is_one_tuple_for_every_position_from_the_grid_with_the_prior_and_no_clip_shown():
    samples = {"RB": _sample(0.6, noise=2.0, seed=2), "WR": _sample(0.6, noise=2.0, seed=3)}
    clip, table = opfit.choose_clip(samples)
    assert clip[0] in opfit.CLIP_LO_GRID and clip[1] in opfit.CLIP_HI_GRID
    assert projections.OPPORTUNITY_RATIO_CLIP in table and opfit.NO_CLIP in table
    assert table[clip] == min(v for c, v in table.items() if c[0] in opfit.CLIP_LO_GRID and c[1] in opfit.CLIP_HI_GRID)


def test_attempt_value_is_the_least_squares_points_per_attempt_with_carries_at_the_carry_value():
    rng = np.random.default_rng(4)
    rows = []
    for i in range(600):
        att, car = int(rng.integers(20, 45)), int(rng.integers(0, 8))
        rows.append({"season": 2020 + i % 3, "gsis_id": f"q{i % 40}", "pos": "QB", "week": i % 17 + 1, "attempts": att, "carries": car,
                     "fpts_ppr": 0.4 * att + usage.XFP_PER_CARRY * car + rng.normal(0, 1.0)})
    rows.append({"season": 2020, "gsis_id": "wr", "pos": "WR", "week": 1, "targets": 9, "fpts_ppr": 14.0})
    a = opfit.fit_attempt_value(_weekly(rows))
    assert a["per_attempt"] == pytest.approx(0.4, abs=0.01) and a["n"] == 600 and set(a["by_season"]) == {2020, 2021, 2022}
    assert a["joint"]["per_attempt"] == pytest.approx(0.4, abs=0.02) and a["joint"]["per_carry"] == pytest.approx(usage.XFP_PER_CARRY, abs=0.1)
    assert opfit.fit_attempt_value(_weekly(rows[-1:]))["per_attempt"] is None   # no QB week: nothing to fit


def test_the_live_proxy_prices_a_pass_attempt_and_the_fitted_weights_are_what_the_fitter_adopts():
    """`xfp_lite_expr` is one formula for the season summary and the fitter; a QB's attempts count at XFP_PER_ATTEMPT,
    and the adopted weights are shares above the 0.5 prior with the clip wider than the data (the plan's table)."""
    w = _weekly([{"pos": "QB", "week": 1, "attempts": 30, "carries": 4}])
    xfp = opfit.with_xfp(w)["xfp"][0]
    assert xfp == pytest.approx(30 * usage.XFP_PER_ATTEMPT + 4 * usage.XFP_PER_CARRY) and usage.XFP_PER_ATTEMPT > 0
    assert opfit.with_xfp(w, 0.5)["xfp"][0] == pytest.approx(15 + 4 * usage.XFP_PER_CARRY)
    assert set(projections.OPPORTUNITY_WEIGHT) == set(opfit.FIT_POSITIONS)
