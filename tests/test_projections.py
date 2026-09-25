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
    row = {"espn_id": 1, "name": "QB", "pos": "QB", "team": "X", "eligible": ["QB"], "proj_week": 0.4, "proj_season": 300.0,
           "injury_status": "OUT"}
    out = blend(row, None, None, 15, week=3)
    healthy = dict(row, injury_status="ACTIVE", proj_week=20.0)
    ok = blend(healthy, None, None, 15, week=3)
    assert out.mu_ros_active == pytest.approx(20.0) and ok.mu_ros_active == pytest.approx(20.0)
    assert out.mu_ros == pytest.approx(20.0 * 14 / 15, abs=0.05) and out.return_week == 4


def test_a_non_numeric_fantasypros_cell_reads_as_missing():
    """The dynastyprocess mirror writes R's `NA` into `r2p_pts`/`sd` for a player it ranks but has no projection
    for, which turns the whole CSV column to strings. That must not take down the packet build."""
    na = blend(row(), {"r2p_pts": "NA", "sd": "NA", "ecr": 30.0}, None, W, None, week=3)
    missing = blend(row(), {"ecr": 30.0}, None, W, None, week=3)
    assert na.mu == pytest.approx(missing.mu) and na.sigma == pytest.approx(missing.sigma)
    assert na.mu == pytest.approx(12.0)  # the ESPN number, unblended


def test_fantasypros_numbers_still_arrive_as_strings():
    """Same column, ordinary values: one `NA` anywhere makes polars read every cell as a string, so the numeric
    ones have to keep working."""
    s = blend(row(proj_week=0.0), {"r2p_pts": "9.5", "sd": "3.0"}, None, W, None, week=3)
    f = blend(row(proj_week=0.0), {"r2p_pts": 9.5, "sd": 3.0}, None, W, None, week=3)
    assert s.mu == pytest.approx(f.mu) == pytest.approx(9.5) and s.sigma == pytest.approx(f.sigma)
