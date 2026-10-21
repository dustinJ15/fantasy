"""The blend question (D10 step 5): the fitted weekly number against ESPN's on a replay, and the mixing weight."""
from __future__ import annotations

import polars as pl
import pytest

from ff import backtest as bt
from ff.model import projections as P


def _u(pid=1, pos="WR", team="KC", total=170.0, weeks=None):
    return {"espn_id": pid, "name": f"p{pid}", "pos": pos, "team": team, "eligible": [pos], "proj_season": total,
            "bye_weeks": [], "weeks": weeks or {}}


def _inp(usage=None, defense=None, games=None, gsis=None):
    return bt.FitInputs(usage or {}, defense or {}, games or {}, gsis or {})


def test_week_one_is_the_preseason_total_a_game_times_this_weeks_line_and_defense():
    u = _u(weeks={1: {"proj": 12.0, "actual": 20.0}})
    inp = _inp(games={(1, "KC"): {"opp": "DEN", "implied": 27.6}}, defense={1: {("DEN", "WR"): {"factor": 1.2, "games": 5}}})
    f = bt.fitted_week(u, 1, inp)
    level = 170.0 / P.NFL_GAMES
    assert f["level"] == pytest.approx(level)
    assert f["vegas_mult"] == pytest.approx(1 + P.VEGAS_K["WR"] * (27.6 / P.LEAGUE_AVG_IMPLIED - 1))
    assert f["def_mult"] == pytest.approx(1 + P.OPPONENT_K["WR"] * 0.2)
    assert f["fitted"] == pytest.approx(level * f["vegas_mult"] * f["def_mult"])


def test_the_fitted_number_reads_nothing_from_its_own_week_on():
    weeks = {1: {"proj": 10.0, "actual": 8.0}, 2: {"proj": 10.0, "actual": 14.0}, 3: {"proj": 10.0, "actual": 9.0},
             4: {"proj": 10.0, "actual": 30.0}}
    a = bt.fitted_week(_u(weeks=weeks), 3, _inp())
    later = {**weeks, 3: {"proj": 10.0, "actual": 50.0}, 4: {"proj": 10.0, "actual": 0.0}}
    assert bt.fitted_week(_u(weeks=later), 3, _inp())["fitted"] == a["fitted"]
    earlier = {**weeks, 2: {"proj": 10.0, "actual": 30.0}}
    assert bt.fitted_week(_u(weeks=earlier), 3, _inp())["fitted"] > a["fitted"]
    # two games so far, the total fading over PRIOR_FADE_GAMES: the live `season_pg`
    assert a["level"] == pytest.approx(P.season_pg(11.0, 2, 170.0 / P.NFL_GAMES))


def test_the_opportunity_read_moves_the_level_and_no_level_is_no_row():
    weeks = {1: {"proj": 10.0, "actual": 20.0}, 2: {"proj": 10.0, "actual": 20.0}, 3: {"proj": 10.0, "actual": 5.0}}
    usage = {3: {"g1": {"games": 2, "ppg": 20.0, "xfp_pg": 10.0}}}
    plain = bt.fitted_week(_u(weeks=weeks), 3, _inp())
    moved = bt.fitted_week(_u(weeks=weeks), 3, _inp(usage=usage, gsis={1: "g1"}))
    assert moved["opp_mult"] == pytest.approx(P.opportunity_mult("WR", usage[3]["g1"])) and moved["opp_mult"] < 1
    assert moved["fitted"] < plain["fitted"]
    assert bt.fitted_week(_u(total=0.0, weeks={1: {"proj": 5.0, "actual": 3.0}}), 1, _inp()) is None


def test_week_games_reads_each_side_of_the_closing_line():
    sched = pl.DataFrame({"game_type": ["REG", "REG", "POST"], "week": [1, 2, 19], "home_team": ["KC", "LA", "KC"],
                          "away_team": ["DEN", "SF", "BUF"], "total_line": [45.0, None, 50.0], "spread_line": [7.0, 3.0, 1.0]})
    g = bt.week_games(sched)
    assert g[(1, "KC")] == {"opp": "DEN", "implied": 26.0} and g[(1, "DEN")] == {"opp": "KC", "implied": 19.0}
    assert g[(2, "SF")] == {"opp": "LA", "implied": None}
    assert (19, "KC") not in g


def test_fit_inputs_never_reads_the_whole_season_for_week_one(monkeypatch):
    calls = []
    from ff import ids
    from ff.model import usage as usage_mod
    from ff.sources import nflverse
    monkeypatch.setattr(usage_mod, "season_summary", lambda season, through: calls.append(through) or "summary")
    monkeypatch.setattr(usage_mod, "signals", lambda s: {"g": {}})
    monkeypatch.setattr(usage_mod, "opponent_factor_index", lambda season, through: {"through": through})
    monkeypatch.setattr(nflverse, "schedules", lambda season: pl.DataFrame({"game_type": [], "week": [], "home_team": [], "away_team": [],
                                                                          "total_line": [], "spread_line": []}))
    monkeypatch.setattr(ids, "Crosswalk", lambda: type("X", (), {"by_espn": {"1": {"gsis_id": "g1"}, "2": {"gsis_id": None}}})())
    inp = bt.fit_inputs(2026, [1, 2, 3], {1, 2, 3})
    assert calls == [1, 2]   # season_summary(through=None or 0) is the whole season: week 1 must not call it
    assert inp.usage[1] == {} and inp.defense[3] == {"through": 2} and inp.gsis == {1: "g1"}


def test_inverse_error_weights_and_the_held_out_mix():
    rows = [{"week": w, "a": 10.0 + e, "b": 10.0 - 2 * e, "actual": 10.0} for w in (1, 2, 3) for e in (1.0, -1.0)]
    wt = bt.inverse_error_weights(rows, ("a", "b"))
    assert wt["a"] == pytest.approx(0.8) and wt["b"] == pytest.approx(0.2)   # mse 1 against 4
    mae, bias = bt.mix_oos(rows, ("a", "b"))
    assert mae == pytest.approx(0.4) and bias == pytest.approx(0.0)   # each week mixed 0.8 / 0.2 off the other two: 0.8e - 0.4e
    assert bt.mix_oos([r for r in rows if r["week"] == 1], ("a", "b")) == (None, None)
    assert bt.inverse_error_weights([], ("a",)) is None


def _rep(league="L1"):
    weeks = {w: {"proj": 10.0, "actual": 12.0} for w in (1, 2, 3)}
    players = {1: _u(1, "WR", weeks=weeks), 2: _u(2, "RB", weeks={**weeks, 2: {"proj": 1.0, "actual": 0.0}}),
               3: _u(3, "K", weeks=weeks), 4: _u(4, "TE", weeks={1: {"actual": 4.0}, 2: {"proj": 8.0, "actual": 6.0}})}
    players[1]["bye_weeks"] = [3]
    roster = [{"espn_id": 1}]
    return {"season": 2026, "league": league, "players": players,
            "weeks": [{"week": w, "matchups": [{"home_roster": roster if w == 1 else [], "away_roster": []}]} for w in (1, 2, 3)]}


def test_fit_rows_grade_the_card_positions_with_espns_number_and_an_actual():
    rows = bt.fit_rows(_rep(), _inp())
    got = {(r["espn_id"], r["week"]) for r in rows}
    # WR 1: weeks 1-2 (3 is his bye); RB 2: not week 2 (ESPN under FIT_MIN_PROJ); K: not a fitted position;
    # TE 4: week 1 has no projection, week 2 has one
    assert got == {(1, 1), (1, 2), (2, 1), (2, 3), (4, 2)}
    assert next(r for r in rows if (r["espn_id"], r["week"]) == (1, 1))["rostered"] is True
    assert next(r for r in rows if (r["espn_id"], r["week"]) == (1, 2))["rostered"] is False


def test_fit_table_flags_a_short_sample_without_losing_the_fitted_column():
    rows = bt.fit_rows(_rep(), _inp())
    t = {r["pos"]: r for r in bt.fit_table(rows, bt.FIT_SOURCES, ("espn", "fitted"), min_n=2)}
    assert t["WR"]["counts"] is True and t["TE"]["counts"] is False
    assert set(t["WR"]["fitted"]) == {"mae", "bias"} and t["WR"]["espn"]["mae"] == pytest.approx(2.0)
    assert t["QB"]["n"] == 0 and t["QB"]["weights"] is None


def test_the_projlog_table_joins_on_league_and_skips_a_legacy_row():
    logged = {("L1", 1, 1): {"espn_pts": 10.0, "sleeper_pts": 11.0, "blend": 10.5},
              ("", 1, 2): {"espn_pts": 10.0, "sleeper_pts": 11.0, "blend": 10.5}}   # a pre-2026-10-08 log: no league
    res = bt.fit_hits([_rep()], {2026: _inp()}, logged, min_n=1)
    wr = next(r for r in res["projlog"] if r["pos"] == "WR")
    assert wr["n"] == 1 and wr["sleeper"]["mae"] == pytest.approx(1.0) and wr["blend"]["mae"] == pytest.approx(1.5)
    assert set(wr["weights"]) == {"espn", "sleeper", "fitted"}
    assert "projlog" not in bt.fit_hits([_rep()], {2026: _inp()}, None)


def test_vegas_mult_is_blends_implied_total_term():
    for pos in ("QB", "RB", "D/ST"):
        assert P.vegas_mult(pos, 27.0) == pytest.approx(1 + P.VEGAS_K[pos] * (27.0 / P.LEAGUE_AVG_IMPLIED - 1))
    assert P.vegas_mult("WR", None) == 1.0
    row = {"espn_id": 1, "name": "x", "pos": "QB", "team": "KC", "eligible": ["QB"], "proj_week": 20.0}
    assert P.blend(row, None, None, 10, implied_total=27.0).mu == pytest.approx(round(20.0 * P.vegas_mult("QB", 27.0), 2))
