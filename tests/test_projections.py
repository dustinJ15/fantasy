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
