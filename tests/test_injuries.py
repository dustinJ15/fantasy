"""IR / trade / drop / hold for a hurt player: the worked examples from docs/plans/injured-player-decision.md."""
import pytest

from ff.model.injuries import decide, week_weights
from tests.conftest import P

REG, PLAYOFF_WEEKS = 14, [15, 16, 17]


def hurt(p, weeks_out, weeks_remaining, week, status="OUT"):
    """Give a conftest player an injury horizon the way `blend` would."""
    p.mu_ros_active = p.mu_ros
    p.weeks_out = min(weeks_out, weeks_remaining)
    p.avail_ros = (weeks_remaining - p.weeks_out) / weeks_remaining
    p.mu_ros = round(p.mu_ros_active * p.avail_ros, 2)
    p.return_week = week + int(weeks_out) if 1 <= weeks_out < weeks_remaining else None
    p.sources = {"espn_status": status}
    return p


def roster():
    return [P(1, "QB1", "QB", 20), P(2, "RB1", "RB", 15), P(3, "RB2", "RB", 12), P(4, "RB3", "RB", 10), P(5, "RB4", "RB", 6),
            P(6, "WR1", "WR", 14), P(7, "WR2", "WR", 12), P(8, "WR3", "WR", 9), P(9, "TE1", "TE", 9), P(10, "TE2", "TE", 4),
            P(11, "K", "K", 8), P(12, "D", "D/ST", 7)]


def fa(delta, name="FA", pos="RB", slot="RB"):
    return [{"name": name, "pos": pos, "slot": slot, "delta_over_starter": delta, "streamer": False}]


def run(mine, week, playoff_pct, ir_slots=0, waivers=(), trades=(), starters=None):
    wr = 17 - week + 1
    starters = starters if starters is not None else {p.espn_id for p in mine if p.weeks_out < 1 and p.name not in ("RB4", "TE2")}
    return decide(mine, {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "K": 1, "D/ST": 1}, week, wr, REG, playoff_pct,
                  ir_slots, list(waivers), list(trades), {}, starters)


def test_week_weights_count_playoff_weeks_by_my_odds():
    w = week_weights(3, 15, REG, 60)
    assert sum(w.values()) == pytest.approx(13.8) and w[14] == 1.0 and w[15] == 0.6


def test_season_ender_goes_to_an_open_ir_slot():
    mine = roster(); hurt(mine[1], 15, 15, 3)
    (row,) = run(mine, 3, 60, ir_slots=1, waivers=fa(1.5))
    assert row["name"] == "RB1" and row["verdict"] == "ir" and row["hold_value"] == 0 and row["drop_value"] == pytest.approx(20.7, abs=0.1)


def test_season_ender_with_no_ir_slot_is_a_drop_even_with_nothing_to_add():
    mine = roster(); hurt(mine[1], 15, 15, 3)
    (row,) = run(mine, 3, 60)
    assert row["verdict"] == "drop" and "dead roster spot" in row["why"][0]


def test_four_weeks_in_week_three_is_a_hold():
    mine = roster(); hurt(mine[6], 4, 15, 3)  # WR2, 12/g
    (row,) = run(mine, 3, 60, waivers=fa(1.0, pos="WR", slot="WR"))
    assert row["verdict"] == "hold" and row["return_week"] == 7
    assert row["back_eff"] == pytest.approx(9.8) and row["w_eff"] == pytest.approx(13.8)
    assert row["hold_value"] > row["drop_value"] == pytest.approx(13.8, abs=0.1)


def test_same_injury_in_week_eleven_flips_on_contention_and_on_the_pickup():
    def te_out(pct, delta):
        mine = roster(); hurt(mine[8], 4, 7, 11)  # TE1 back week 15, playoffs only
        return run(mine, 11, pct, waivers=fa(delta, pos="TE", slot="TE"))[0]
    low = te_out(20, 0.8)
    assert low["back_eff"] == pytest.approx(0.6) and low["w_eff"] == pytest.approx(4.6) and low["verdict"] == "hold"
    assert te_out(20, 2.0)["verdict"] == "drop"        # margin met, and he is the cheapest drop
    high = te_out(90, 2.0)
    assert high["verdict"] == "hold" and high["hold_value"] == pytest.approx(high["hold_ppw"] * 2.7, abs=0.1)


def test_not_the_cheapest_drop_means_hold_and_names_who_is():
    mine = roster(); hurt(mine[6], 4, 7, 11)  # WR2 nets 5.1/wk over the stretch; a 3/g RB4 is the cheaper cut
    mine[4].mu_ros = mine[4].mu_ros_active = 3.0
    (row,) = run(mine, 11, 20, waivers=fa(3.0, pos="WR", slot="WR"))
    assert row["verdict"] == "hold" and any("RB4 is the cheaper drop" in w for w in row["why"])


def test_ir_slot_taken_by_a_lesser_stash_is_a_swap():
    mine = roster(); hurt(mine[1], 6, 15, 3)            # RB1, 15/g, back week 9
    hurt(mine[9], 15, 15, 3); mine[9].slot = "IR"        # TE2 on IR, done for the year
    rows = run(mine, 3, 60, ir_slots=1)
    row = next(r for r in rows if r["name"] == "RB1")
    assert row["verdict"] == "ir" and row["ir_occupant"] == "TE2"
    assert not any(r["name"] == "TE2" for r in rows)     # stashed and still out: no row of his own


def test_a_stash_who_is_back_next_week_must_be_activated():
    mine = roster(); hurt(mine[1], 1, 15, 3); mine[1].slot = "IR"
    (row,) = run(mine, 3, 60, ir_slots=1)
    assert row["verdict"] == "activate"


def test_a_sendable_package_that_ships_him_is_the_verdict():
    mine = roster(); hurt(mine[1], 4, 15, 3)
    trades = [{"sendable": True, "rival": "Them", "give": ["RB1"], "get": ["Star"]}, {"sendable": False, "rival": "X", "give": ["RB1"], "get": ["Y"]}]
    (row,) = run(mine, 3, 60, trades=trades)
    assert row["verdict"] == "trade" and row["trades"] == [{"rival": "Them", "get": ["Star"]}]


def test_out_this_week_only_still_gets_a_row_but_holds():
    mine = roster(); hurt(mine[6], 1, 15, 3)
    (row,) = run(mine, 3, 60, waivers=fa(1.0, pos="WR", slot="WR"))
    assert row["verdict"] == "hold" and row["return_week"] == 4


def test_one_ir_slot_goes_to_the_more_valuable_player_only():
    mine = roster(); hurt(mine[1], 4, 15, 3); hurt(mine[3], 2, 15, 3)  # RB1 15/g and RB3 10/g, one slot
    rows = {r["name"]: r["verdict"] for r in run(mine, 3, 60, ir_slots=1)}
    assert rows["RB1"] == "ir" and rows["RB3"] == "hold"
