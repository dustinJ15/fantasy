"""The injury horizon: `weeks_out` from designations or Claude, and how it reaches the rest-of-season numbers."""
import pytest

from ff.model.projections import blend


def row(**kw):
    base = dict(espn_id=9, name="x", pos="RB", team="GB", eligible=["RB", "RB/WR/TE"], slot="BE", proj_week=12.0,
                proj_season=180.0, injury_status=None, bye=False)
    base.update(kw)
    return base


W = 12  # weeks remaining


def test_healthy_player_has_no_horizon():
    p = blend(row(), None, None, W, None, week=3)
    assert p.weeks_out == 0 and p.avail_ros == 1.0 and p.mu_ros == p.mu_ros_active and p.return_week is None


def test_ir_designation_defaults_to_four_games():
    p = blend(row(injury_status="INJURY_RESERVE"), None, None, W, None, week=3)
    assert p.weeks_out == 4 and p.return_week == 7
    assert p.mu_ros == pytest.approx(p.mu_ros_active * (W - 4) / W, abs=0.01)


def test_sleeper_roster_status_on_ir_counts_too():
    p = blend(row(), None, {"status": None, "roster_status": "Injured Reserve"}, W, None, week=3)
    assert p.weeks_out == 4 and p.mu_ros < p.mu_ros_active


def test_season_ender_is_worth_nothing_rest_of_season():
    p = blend(row(injury_status="OUT"), None, None, W, {"9": {"weeks_out": "season"}}, week=3)
    assert p.weeks_out == W and p.avail_ros == 0 and p.mu_ros == 0 and p.return_week is None
    assert p.mu_ros_active > 0  # still know what he is worth when he plays
    beyond = blend(row(injury_status="OUT"), None, None, W, {"9": {"weeks_out": 40}}, week=3)
    assert beyond.weeks_out == W and beyond.return_week is None


def test_ruled_out_this_week_means_one_game():
    p = blend(row(), None, None, W, {"9": {"p_zero": 1.0}}, week=3)
    assert p.p_zero == 1.0 and p.weeks_out == 1 and p.return_week == 4
    out = blend(row(injury_status="OUT"), None, None, W, None, week=3)
    assert out.weeks_out == 1 and out.mu_ros == pytest.approx(out.mu_ros_active * 11 / 12, abs=0.01)


def test_questionable_is_a_fraction_of_one_game():
    p = blend(row(injury_status="QUESTIONABLE"), None, None, W, None, week=3)
    assert p.weeks_out == 0.3 and 0.97 < p.avail_ros < 1.0 and p.return_week is None


def test_ros_mult_scales_the_season_and_mu_mult_scales_the_week():
    base = blend(row(), None, None, W, None)
    ros = blend(row(), None, None, W, {"9": {"ros_mult": 0.8}})
    assert ros.mu == base.mu
    assert ros.mu_ros_active == pytest.approx(base.mu_ros_active * 0.8, abs=0.01)
    assert ros.mu_ros == pytest.approx(base.mu_ros * 0.8, abs=0.01)
    wk = blend(row(), None, None, W, {"9": {"mu_mult": 0.5}})
    assert wk.mu == pytest.approx(base.mu * 0.5, abs=0.01)
    assert wk.mu_ros == base.mu_ros and wk.mu_ros_active == base.mu_ros_active  # the regression the plan fixes


def test_a_bye_is_not_an_injury():
    p = blend(row(bye=True), None, None, W, None, week=3)
    assert p.p_zero == 1.0 and p.weeks_out == 0 and p.mu_ros == p.mu_ros_active


def test_packet_carries_the_horizon():
    d = blend(row(injury_status="INJURY_RESERVE"), None, {"status": "IR", "roster_status": "Injured Reserve", "body_part": "Knee"}, W,
              {"9": {"weeks_out": 6, "note": "MRI Monday"}}, week=3).to_dict()
    assert d["weeks_out"] == 6 and d["return_week"] == 9 and d["sources"]["weeks_out_source"] == "override"
    assert d["sources"]["body_part"] == "Knee" and d["sources"]["sleeper_roster_status"] == "Injured Reserve"


def test_a_player_listed_out_keeps_his_healthy_per_game_number():
    """This week's ~0 projection must not drag the rest-of-season per-game number down: he is not playing this week,
    and `weeks_out` already charges for that."""
    row = {"espn_id": 1, "name": "QB", "pos": "QB", "team": "X", "eligible": ["QB"], "proj_week": 0.4, "proj_season": 340.0,
           "injury_status": "OUT"}
    out = blend(row, None, None, 15, week=3)
    healthy = dict(row, injury_status="ACTIVE", proj_week=20.0)
    ok = blend(healthy, None, None, 15, week=3)
    assert out.mu_ros_active == pytest.approx(20.0) and ok.mu_ros_active == pytest.approx(20.0)
    assert out.mu_ros == pytest.approx(20.0 * 14 / 15, abs=0.05) and out.return_week == 4


def test_blend_treats_a_non_numeric_fantasypros_value_as_missing():
    """The dynastyprocess mirror writes NA for a missing r2p_pts; one NA makes the column text and used to crash."""
    from ff.model.projections import blend
    row = {"espn_id": 1, "name": "X", "pos": "WR", "team": "GB", "eligible": ["WR"], "slot": "BE", "fantasy_team_id": 1,
           "injury_status": None, "proj_week": 10.0, "actual_week": 0.0, "proj_season": 100.0, "percent_owned": 50.0,
           "pos_rank": 30, "bye": False}
    p = blend(row, {"r2p_pts": "NA", "sd": "NA"}, None, 15, None)
    assert p.mu > 0 and p.sigma > 0


def test_fantasypros_reader_parses_na_as_null(tmp_path):
    import polars as pl

    from ff.sources.fantasypros import NULLS
    f = tmp_path / "fp.csv"
    f.write_text("fantasypros_id,player_name,pos,ecr,sd,r2p_pts\n1,A,WR,1.0,0.5,12.3\n2,B,WR,2.0,NA,NA\n")
    df = pl.read_csv(f, infer_schema_length=10000, ignore_errors=True, null_values=NULLS)
    assert df["r2p_pts"].dtype == pl.Float64 and df["r2p_pts"].null_count() == 1 and df["sd"].dtype == pl.Float64


# ---------- A1: the rest-of-season per-game base ----------

def test_ros_per_game_does_not_divide_the_season_total_by_weeks_remaining():
    """ESPN's `proj_season` is a full-season figure, so late in the season `proj_season / weeks_remaining` says a
    10-a-week player is worth 34 a game. He is worth about 10."""
    p = blend(row(proj_week=10.0, proj_season=170.0), None, None, 5, None, week=13)
    assert p.mu_ros_active == pytest.approx(10.0, abs=0.5)
    assert p.sources["espn_pg"] == pytest.approx(10.0, abs=0.5)
    early = blend(row(proj_week=10.0, proj_season=170.0), None, None, 17, None, week=1)
    assert early.mu_ros_active == pytest.approx(p.mu_ros_active, abs=0.01)  # the week does not move the number


def test_season_to_date_points_per_game_replace_the_preseason_prior():
    """St. Brown on 2026-10-08: 91.3 in 4 games, preseason total 246.2 (14.5 a game), weekly 18. His level is his
    own games with the preseason total fading, not 246.2 over the 13 weeks left (18.9) and not 246.2 / 17 either."""
    r = row(name="ARSB", pos="WR", proj_week=18.0, proj_season=246.2, actual_season=91.3, games_played=4)
    p = blend(r, None, None, 13, None, week=5)
    ytd, prior = 91.3 / 4, 246.2 / 17
    assert prior < p.mu_ros_active < ytd
    assert p.mu_ros_active == pytest.approx(0.5 * (ytd * 4 / 6 + prior * 2 / 6) + 0.5 * 18.0, abs=0.05)
    assert p.sources["ytd_pg"] == pytest.approx(ytd, abs=0.01)
    settled = blend(row(**{**r, "actual_season": 91.3 * 2, "games_played": 8}), None, None, 9, None, week=9)
    assert settled.mu_ros_active == pytest.approx(0.5 * ytd + 0.5 * 18.0, abs=0.05)  # prior gone after six games


def test_rival_app_view_uses_espn_numbers_only_and_is_not_inflated():
    """`espn_pg` is what his app shows him; it rides ESPN's own total, average and weekly, never the Sleeper blend."""
    r = row(proj_week=10.0, proj_season=170.0, actual_season=60.0, games_played=4)
    p = blend(r, None, None, 5, None, week=13, sleeper_pts=20.0)
    assert p.sources["espn_pg"] == pytest.approx(0.5 * (15.0 * 4 / 6 + 10.0 * 2 / 6) + 0.5 * 10.0, abs=0.05)
    assert p.mu_ros_active > p.sources["espn_pg"]  # Sleeper's 20 reaches my number, not his
    assert blend(row(proj_season=0.0, proj_week=10.0), None, None, 5, None).sources["espn_pg"] is None


def test_this_weeks_matchup_stays_out_of_the_rest_of_season_number():
    """A6: the Vegas multiplier and this week's opponent belong to `mu`, not to every hold and trade row."""
    flat = blend(row(proj_week=12.0, proj_season=204.0), None, None, 10, None, implied_total=23.0)
    shoot = blend(row(proj_week=12.0, proj_season=204.0), None, None, 10, None, implied_total=30.0)
    assert shoot.mu > flat.mu
    assert shoot.mu_ros_active == pytest.approx(flat.mu_ros_active, abs=0.01)


# ---------- D5: wind into this week's number ----------

WINDY = {"dome": False, "temp_f": 41.0, "wind_mph": 20.0, "precip_pct": 10, "precip_in": 0.0}


def test_wind_over_15_discounts_passing_game_and_kicker_this_week_only():
    """20 mph at kickoff: halfway up the ramp from WIND_MPH_START (15) to WIND_MPH_CAP (25), so QB and WR take half of
    their cap penalty (0.95), the kicker half of his (0.925); the RB is untouched and no rest-of-season number moves."""
    from ff.model.projections import WIND_PENALTY_AT_CAP
    for pos, elig in (("QB", ["QB"]), ("WR", ["WR", "RB/WR/TE"]), ("K", ["K"]), ("RB", ["RB", "RB/WR/TE"])):
        calm = blend(row(pos=pos, eligible=elig), None, None, W, None)
        windy = blend(row(pos=pos, eligible=elig), None, None, W, None, weather=WINDY)
        mult = 1 - 0.5 * WIND_PENALTY_AT_CAP.get(pos, 0.0)
        assert windy.mu == pytest.approx(calm.mu * mult, abs=0.01), pos
        assert windy.sources["weather_mult"] == pytest.approx(mult, abs=0.001) and windy.sources["wind_mph"] == 20.0
        assert windy.mu_ros == calm.mu_ros and windy.mu_ros_active == calm.mu_ros_active, pos
    assert blend(row(pos="QB", eligible=["QB"]), None, None, W, None, weather=WINDY).mu == pytest.approx(12.0 * 0.95, abs=0.01)
    assert blend(row(pos="K", eligible=["K"]), None, None, W, None, weather=WINDY).mu == pytest.approx(12.0 * 0.925, abs=0.01)


def test_wind_penalty_is_capped_and_starts_at_the_threshold():
    from ff.model.projections import WIND_PENALTY_AT_CAP, wind_mult
    assert wind_mult("QB", {**WINDY, "wind_mph": 15.0}) == 1.0           # the threshold itself is calm
    assert wind_mult("QB", {**WINDY, "wind_mph": 40.0}) == pytest.approx(1 - WIND_PENALTY_AT_CAP["QB"])  # capped at 25
    assert wind_mult("K", {**WINDY, "wind_mph": 40.0}) == pytest.approx(1 - WIND_PENALTY_AT_CAP["K"])
    assert wind_mult("RB", {**WINDY, "wind_mph": 40.0}) == 1.0 and wind_mult("D/ST", {**WINDY, "wind_mph": 40.0}) == 1.0
    windy = blend(row(pos="QB", eligible=["QB"]), None, None, W, None, weather={**WINDY, "wind_mph": 40.0})
    assert "wind:40mph x0.90" in windy.flags


def test_a_dome_or_missing_forecast_leaves_the_number_alone():
    calm = blend(row(pos="QB", eligible=["QB"]), None, None, W, None)
    for wx in ({"dome": True}, {"dome": False, "unavailable": True}, None, {"dome": False}):
        p = blend(row(pos="QB", eligible=["QB"]), None, None, W, None, weather=wx)
        assert p.mu == calm.mu and p.sources["weather_mult"] == 1.0, wx
        assert not any(f.startswith("wind:") for f in p.flags)
    assert calm.sources["weather_mult"] == 1.0 and calm.sources["wind_mph"] is None


def test_weather_lookup_is_one_forecast_per_game_and_honours_espn_indoor(monkeypatch):
    """`weather.by_team` maps both teams of a game to the home stadium's forecast, fetched once; ESPN's `indoor` flag
    makes a dome without a fetch, and a team with no kickoff reads None (calm)."""
    from ff.sources import weather
    calls = []

    def fake_forecast(home, kick, force=False):
        calls.append((home, kick))
        return {"dome": False, "wind_mph": 22.0}
    monkeypatch.setattr(weather, "forecast", fake_forecast)
    k = "2026-10-11T17:00Z"
    lines = {"BUF": {"home": True, "opp": "NYJ", "kickoff": k, "indoor": False},
             "NYJ": {"home": False, "opp": "BUF", "kickoff": k, "indoor": False},
             "DET": {"home": True, "opp": "GB", "kickoff": k, "indoor": True},
             "GB": {"home": False, "opp": "DET", "kickoff": k, "indoor": True},
             "KC": {"home": True, "opp": "LV", "kickoff": None, "indoor": False}}
    wx = weather.by_team(lines)
    assert calls == [("BUF", k)]
    assert wx["BUF"] == wx["NYJ"] == {"dome": False, "wind_mph": 22.0}
    assert wx["DET"] == wx["GB"] == {"dome": True} and wx["KC"] is None


def test_wind_reaches_the_packet_through_analyze_league(monkeypatch):
    """Wiring: a windy forecast for the demo QB's team shows on his packet row as `sources.weather_mult`, the dome
    teams and the no-forecast run read 1.0, and the card still renders."""
    from ff import demo, report
    from ff.packet import analyze_league
    monkeypatch.setattr("ff.packet.fantasycalc.by_espn_id", lambda **kw: {})
    snap = demo.make_snapshot()
    qb = next(r for r in snap["roster"] if r["fantasy_team_id"] == snap["my_team_id"] and r["pos"] == "QB")
    calm = analyze_league(snap, demo.FakeCrosswalk(), {}, {}, {}, {}, sims=100)
    wx = {t: {"dome": True} for t in {r["team"] for r in snap["roster"]}}
    wx[qb["team"]] = {"dome": False, "wind_mph": 25.0}
    windy = analyze_league(snap, demo.FakeCrosswalk(), {}, {}, {}, {}, sims=100, wx=wx)
    row_calm = next(p for p in calm["roster"] if p["espn_id"] == qb["espn_id"])
    row_wind = next(p for p in windy["roster"] if p["espn_id"] == qb["espn_id"])
    assert row_calm["sources"]["weather_mult"] == 1.0 and row_wind["sources"]["weather_mult"] == 0.9
    assert row_wind["mu"] == pytest.approx(row_calm["mu"] * 0.9, abs=0.02) and row_wind["mu_ros"] == row_calm["mu_ros"]
    assert all(p["sources"]["weather_mult"] == 1.0 for p in windy["roster"] if p["team"] != qb["team"])
    assert "wind:25mph x0.90" in row_wind["flags"]
    packet = {"version": 6, "generated": "2026-10-11T07:00:00", "season": 2026, "leagues": [windy],
              "shared": {"injury_watchlist": [], "exposure": {}, "trending_adds": [], "usage_error": None, "unmatched_ids": []}}
    md = report.render(packet)
    assert "Demo League" in md and "wind:25mph x0.90" in md   # the roster table's flags column says why he reads low


# ---------- D1: opportunity moves the rest-of-season level ----------

def _usage(ppg: float, xfp_pg: float, games: int = 4) -> dict:
    return {"flags": [], "games": games, "ppg": ppg, "xfp_pg": xfp_pg, "tgt_share": 0.2, "tgt_pg": 6.0, "carry_pg": 0.0}


def test_opportunity_mult_moves_toward_what_the_targets_say_by_the_fitted_weight_and_is_clipped():
    """The weight per position is the fitted one (D10 step 1): over half, under one, and a running QB's attempts count."""
    from ff.model.projections import OPPORTUNITY_RATIO_CLIP, OPPORTUNITY_WEIGHT, opportunity_mult
    w_wr, w_rb, w_te, w_qb = (OPPORTUNITY_WEIGHT[p] for p in ("WR", "RB", "TE", "QB"))
    assert all(0.5 < w < 1.0 for w in (w_wr, w_rb, w_te, w_qb))
    assert opportunity_mult("WR", _usage(ppg=20.0, xfp_pg=16.0)) == pytest.approx(1 - w_wr + w_wr * 0.8)   # 20% over his usage
    assert opportunity_mult("RB", _usage(ppg=10.0, xfp_pg=12.0)) == pytest.approx(1 - w_rb + w_rb * 1.2)   # under it
    assert opportunity_mult("QB", _usage(ppg=20.0, xfp_pg=15.0)) == pytest.approx(1 - w_qb + w_qb * 0.75)
    lo, hi = OPPORTUNITY_RATIO_CLIP
    assert lo < 0.5 and hi >= 1.8   # inside the data the clip is off; it guards a bad row
    assert opportunity_mult("TE", _usage(ppg=4.0, xfp_pg=12.0)) == pytest.approx(1 - w_te + w_te * hi)
    assert opportunity_mult("WR", _usage(ppg=20.0, xfp_pg=2.0)) == pytest.approx(1 - w_wr + w_wr * lo)


def test_opportunity_has_no_say_on_a_kicker_a_one_game_sample_or_a_blank():
    from ff.model.projections import opportunity_mult
    assert opportunity_mult("K", _usage(ppg=8.0, xfp_pg=0.0)) == 1.0 and opportunity_mult("D/ST", None) == 1.0
    assert opportunity_mult("WR", _usage(ppg=20.0, xfp_pg=16.0, games=1)) == 1.0
    assert opportunity_mult("WR", None) == 1.0 and opportunity_mult("WR", {}) == 1.0
    assert opportunity_mult("WR", _usage(ppg=0.0, xfp_pg=10.0)) == 1.0 and opportunity_mult("WR", {"games": 4, "ppg": "NA"}) == 1.0


def test_a_td_heavy_start_is_regressed_toward_the_targets_and_the_rival_still_sees_espn():
    """A receiver with 91.3 in 4 games on usage worth 73 (five touchdowns on 24 targets): his level reads under his
    average by the fitted weight (11% at 0.58; 10% at the 0.5 prior of the plan's worked example), the preseason
    prior and the weekly blend as before; his rival's app (`espn_pg`) never sees it."""
    from ff.model.projections import OPPORTUNITY_WEIGHT
    r = row(name="TD WR", pos="WR", proj_week=18.0, proj_season=246.2, actual_season=91.3, games_played=4)
    plain = blend(r, None, None, 13, None, week=5)
    hot = blend(r, None, None, 13, None, week=5, usage=_usage(ppg=22.8, xfp_pg=18.3))
    ytd, prior, w = 91.3 / 4, 246.2 / 17, OPPORTUNITY_WEIGHT["WR"]
    mult = 1 - w + w * 18.3 / 22.8
    assert hot.mu_ros_active == pytest.approx(0.5 * (ytd * mult * 4 / 6 + prior * 2 / 6) + 0.5 * 18.0, abs=0.05)
    assert hot.mu_ros_active < plain.mu_ros_active and hot.mu_ros < plain.mu_ros
    assert hot.sources["espn_pg"] == plain.sources["espn_pg"] and hot.sources["ytd_pg"] == plain.sources["ytd_pg"]
    assert hot.sources["opp_mult"] == pytest.approx(mult, abs=0.001) and f"opp:x{mult:.2f}" in hot.flags
    assert hot.mu == plain.mu and hot.sigma == plain.sigma   # this week's number is the matchup's, not the season's


def test_a_back_whose_carries_outrun_his_points_reads_up_and_a_blank_usage_changes_nothing():
    r = row(name="Volume RB", pos="RB", proj_week=12.0, proj_season=180.0, actual_season=40.0, games_played=4)
    plain = blend(r, None, None, 13, None, week=5)
    from ff.model.projections import OPPORTUNITY_WEIGHT
    cold = blend(r, None, None, 13, None, week=5, usage=_usage(ppg=10.0, xfp_pg=13.0))
    assert cold.mu_ros_active > plain.mu_ros_active and cold.sources["opp_mult"] == pytest.approx(1 + 0.3 * OPPORTUNITY_WEIGHT["RB"], abs=0.001)
    same = blend(r, None, None, 13, None, week=5, usage={"flags": [], "games": 0, "ppg": 0.0, "xfp_pg": 0.0})
    assert same.mu_ros_active == plain.mu_ros_active and same.sources["opp_mult"] == 1.0 and "opp:x1.00" not in same.flags
    # no games on ESPN's side: nothing to scale, the prior is the level
    fresh = blend(row(pos="RB", proj_week=12.0, proj_season=180.0), None, None, 13, None, week=1, usage=_usage(ppg=10.0, xfp_pg=13.0))
    assert fresh.sources["opp_mult"] == 1.0 and fresh.mu_ros_active == pytest.approx(0.5 * 180 / 17 + 0.5 * 12.0, abs=0.05)


# ---------- D10 step 2: the opponent factor moves this week's number ----------

def test_opponent_mult_takes_k_of_the_factor_held_to_the_cap_and_waits_for_the_defense(monkeypatch):
    from ff.model import projections
    monkeypatch.setattr(projections, "OPPONENT_K", {"QB": 0.2, "RB": 0.25, "WR": 0.1, "TE": 0.2})
    assert projections.opponent_mult("QB", {"factor": 1.4, "games": 6}) == pytest.approx(1.08)
    assert projections.opponent_mult("RB", {"factor": 0.5, "games": 6}) == pytest.approx(0.9)    # 0.875 held to the cap
    assert projections.opponent_mult("RB", {"factor": 1.6, "games": 6}) == pytest.approx(1.1)
    assert projections.opponent_mult("RB", {"factor": 1.6, "games": 2}) == 1.0    # under OPPONENT_MIN_GAMES
    assert projections.opponent_mult("K", {"factor": 1.6, "games": 9}) == 1.0 == projections.opponent_mult("D/ST", {"factor": 0.5, "games": 9})
    assert projections.opponent_mult("WR", None) == 1.0 == projections.opponent_mult("WR", {"factor": None, "games": 9})


def test_a_soft_defense_lifts_this_week_only_and_the_rival_still_sees_espn(monkeypatch):
    from ff.model import projections
    monkeypatch.setattr(projections, "OPPONENT_K", {"QB": 0.2, "RB": 0.25, "WR": 0.1, "TE": 0.2})
    r = row(pos="QB", eligible=["QB"], proj_week=20.0, proj_season=340.0, actual_season=88.0, games_played=4)
    flat = blend(r, None, None, 13, None, week=5)
    soft = blend(r, None, None, 13, None, week=5, opponent={"factor": 1.4, "games": 6, "raw": 1.3})
    assert soft.mu == pytest.approx(flat.mu * 1.08, abs=0.01)
    assert soft.mu_ros == flat.mu_ros and soft.mu_ros_active == flat.mu_ros_active   # a matchup, not a level
    assert soft.sources["espn_pg"] == flat.sources["espn_pg"]
    assert soft.sources["def_factor"] == 1.4 and soft.sources["def_mult"] == 1.08 and "def:x1.08" in soft.flags
    assert flat.sources["def_factor"] is None and flat.sources["def_mult"] == 1.0 and not any(f.startswith("def:") for f in flat.flags)
    tough = blend(r, None, None, 13, None, week=5, opponent={"factor": 0.4, "games": 6}, implied_total=23.0)
    assert tough.mu == pytest.approx(flat.mu * 0.9, abs=0.01) and "def:x0.90" in tough.flags
    small = blend(r, None, None, 13, None, week=5, opponent={"factor": 1.05, "games": 6})
    assert small.sources["def_mult"] == 1.01 and not any(f.startswith("def:") for f in small.flags)   # under the flag's 3%
