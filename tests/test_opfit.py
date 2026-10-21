"""The projection-constant fitter (D10): step 1's training frame reads a player's season so far against the rest of it
with no actual read before the week it is priced at, the closed-form weight recovers a known truth and stays a share,
one clip is chosen for every position, and the pass-attempt value is the least-squares one; step 2's opponent factor
is each defense's points allowed over what the offenses it faced score elsewhere, read through the week before, and
`k` is the closed-form one scored with the cap. Synthetic frames; the network is never touched."""
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


# ---------- D10 step 2: the opponent factor ----------

def _games(rows: list[tuple]) -> pl.DataFrame:
    """Rows of (week, team, opp, pos, pts): one player per team-position-game, so `team_games` reads `pts` back."""
    return _weekly([{"season": 2024, "gsis_id": f"{t}-{pos}", "team": t, "opp": o, "pos": pos, "week": wk, "fpts_ppr": pts}
                    for wk, t, o, pos, pts in rows])


def test_opponent_factors_read_points_allowed_over_what_those_offenses_score_elsewhere():
    """Three weeks, four teams. Defense D allows 30 to A (who scores 10 elsewhere) and 30 to B (who scores 20
    elsewhere): the raw factor is over the league's team-game average, the adjusted one over 15, the mean of what
    A and B score elsewhere. A defense's first week reads its offense at the league average (no other game), a
    position no row prices is a 0 game, and `through_week` keeps the week's own box score out."""
    rows = [(1, "A", "D", "RB", 30.0), (1, "D", "A", "RB", 12.0), (1, "B", "C", "RB", 20.0), (1, "C", "B", "RB", 8.0),
            (2, "B", "D", "RB", 30.0), (2, "D", "B", "RB", 12.0), (2, "A", "C", "RB", 10.0), (2, "C", "A", "RB", 8.0),
            (3, "A", "D", "RB", 99.0), (3, "D", "A", "RB", 12.0), (3, "B", "C", "RB", 20.0), (3, "C", "B", "RB", 8.0)]
    tg = usage.team_games(_games(rows))
    assert tg.filter((pl.col("week") == 1) & (pl.col("team") == "A") & (pl.col("pos") == "RB"))["pts"][0] == 30.0
    assert tg.filter((pl.col("week") == 1) & (pl.col("team") == "A") & (pl.col("pos") == "TE"))["pts"][0] == 0.0   # a game, no TE row
    assert tg.filter(pl.col("week") == 1).height == 4 * len(usage.FACTOR_POSITIONS)
    f = usage.opponent_factors(tg, through_week=2).filter(pl.col("pos") == "RB")
    d = f.filter(pl.col("team") == "D").row(0, named=True)
    assert d["games"] == 2 and d["allowed_pg"] == pytest.approx(30.0)
    assert d["expected_pg"] == pytest.approx(15.0) and d["factor"] == pytest.approx(2.0)   # A scores 10 elsewhere, B 20
    assert d["raw"] == pytest.approx(30.0 / 16.25)   # the league's team-game average over weeks 1-2
    assert f.filter(pl.col("team") == "C").row(0, named=True)["factor"] == pytest.approx(0.5)   # allowed 20 and 10 to offenses scoring 30 elsewhere
    first = usage.opponent_factors(tg, through_week=1).filter(pl.col("pos") == "RB")
    assert first.filter(pl.col("team") == "D").row(0, named=True)["expected_pg"] == pytest.approx(17.5)   # A has no other game: the league average
    assert usage.opponent_factors(tg, through_week=0).is_empty()
    # the whole table carries week 3's 99; through week 2 it does not
    assert usage.opponent_factors(tg).filter((pl.col("team") == "D") & (pl.col("pos") == "RB"))["allowed_pg"][0] > 30.0


def test_opponent_frame_joins_the_factor_as_it_stood_before_the_week_and_waits_for_the_defense():
    """A receiver with games at weeks 1-5 against the same defense D: his week-4 row carries his ppg over weeks 1-3,
    the factor D had through week 3 (3 games: the first week the defense has OPPONENT_MIN_GAMES), and his week-4
    points as the truth; the week-3 row is out (D had 2 games), weeks 1-2 are out (under OPPORTUNITY_MIN_GAMES)."""
    rows = []
    for wk in range(1, 6):
        rows += [(wk, "A", "D", "WR", 10.0 * wk), (wk, "D", "A", "WR", 8.0), (wk, "B", "C", "WR", 12.0), (wk, "C", "B", "WR", 12.0)]
    w = _games(rows)
    df = opfit.opponent_frame(w)
    a = df.filter(pl.col("gsis_id") == "A-WR").sort("week")
    assert a["week"].to_list() == [4, 5] and a["def_games"].to_list() == [3, 4]
    at4 = a.row(0, named=True)
    assert at4["ppg"] == pytest.approx(20.0) and at4["pts"] == pytest.approx(40.0) and at4["opp"] == "D"
    tg = usage.team_games(w)
    through3 = usage.opponent_factors(tg, through_week=3).filter((pl.col("team") == "D") & (pl.col("pos") == "WR")).row(0, named=True)
    assert at4["factor"] == pytest.approx(through3["factor"]) and at4["raw"] == pytest.approx(through3["raw"])
    assert through3["allowed_pg"] == pytest.approx(20.0)   # weeks 1-3 only: never week 4's 40


def _opp_sample(k_true: float, n: int = 5000, seed: int = 0, noise: float = 0.0, seasons: int = 5) -> opfit.OppSample:
    rng = np.random.default_rng(seed)
    ppg = rng.uniform(6.0, 25.0, n)
    factor = rng.uniform(0.6, 1.5, n)
    y = ppg * (1 + k_true * (factor - 1)) + rng.normal(0.0, noise, n)
    return opfit.OppSample(np.repeat(np.arange(2020, 2020 + seasons), n // seasons), np.full(n, 8), ppg, factor, factor.copy(), y)


def test_fit_k_recovers_the_truth_stays_in_bounds_and_the_verdict_is_against_the_prior():
    assert opfit.fit_k(_opp_sample(0.0)) == pytest.approx(0.0)
    assert opfit.fit_k(_opp_sample(0.3, noise=3.0)) == pytest.approx(0.3, abs=0.03)
    s = _opp_sample(0.0)
    s.y = s.ppg * (2.0 - s.factor)   # a tougher defense scoring him up: held at 0
    assert opfit.fit_k(s) == 0.0
    s = _opp_sample(0.2, noise=2.0)
    sse, n, ks = opfit.oos_k(s, cap=None)
    assert n == s.n and len(ks) == 5 and all(abs(k - 0.2) < 0.05 for k in ks)
    row = opfit.fit_opponent_position(s, "RB", cap=0.1, min_n=100)
    assert row["fitted"] and row["k_fit"] == pytest.approx(0.2, abs=0.03) and row["rmse_fit"] < row["rmse_none"]
    assert row["rmse_prior"] == row["rmse_none"] or row["k_prior"] != 0.0
    assert 0.0 < row["cap_binds"] < 0.2   # a factor of 0.6 at k 0.2 is x0.92, 1.5 is x1.10: the cap binds on the top
    assert row["k_raw"] == pytest.approx(row["k_fit"]) and row["rmse_raw"] == pytest.approx(row["rmse_fit"])   # raw == factor here
    assert set(row["k_by_def_games"]) == {f"{lo}-{hi}" for lo, hi in opfit.DEF_GAMES_BUCKETS} and row["k_by_def_games"]["6-9"][1] == s.n
    thin = opfit.fit_opponent_position(_opp_sample(0.2, n=200, noise=2.0), "WR", min_n=1000)
    assert not thin["fitted"] and thin["k_fit"] is not None


def test_the_cap_scores_the_live_multiplier():
    s = _opp_sample(0.0)
    s.factor = np.full(s.n, 2.0); s.raw = s.factor.copy()
    s.y = s.ppg * 1.1   # the truth is the capped multiplier at k 1.0
    assert opfit.opp_rmse(s, 1.0, cap=0.1) == pytest.approx(0.0)
    assert opfit.opp_rmse(s, 1.0, cap=None) > 1.0


def test_the_adopted_opponent_constants_are_what_the_fitter_prints():
    assert set(projections.OPPONENT_K) == set(opfit.FIT_POSITIONS) == set(usage.FACTOR_POSITIONS)
    assert all(opfit.K_BOUNDS[0] < k <= opfit.K_BOUNDS[1] for k in projections.OPPONENT_K.values())
    assert usage.nfl_team("LAR") == "LA" and usage.nfl_team("WSH") == "WAS" and usage.nfl_team("GB") == "GB" and usage.nfl_team(None) is None
