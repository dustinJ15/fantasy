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


def run(mine, week, playoff_pct, ir_slots=0, waivers=(), trades=(), starters=None, repl=None, handcuffs=()):
    wr = 17 - week + 1
    starters = starters if starters is not None else {p.espn_id for p in mine if p.weeks_out < 1 and p.name not in ("RB4", "TE2")}
    return decide(mine, {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "K": 1, "D/ST": 1}, week, wr, REG, playoff_pct,
                  ir_slots, list(waivers), list(trades), {}, starters, repl, list(handcuffs))


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


def test_one_week_out_does_not_take_an_open_ir_slot():
    mine = roster(); hurt(mine[6], 1, 15, 3)
    (row,) = run(mine, 3, 60, ir_slots=1)
    assert row["verdict"] == "hold" and row["ir_eligible"]


def test_ir_slot_goes_to_the_long_absence_not_the_better_player():
    mine = roster(); hurt(mine[1], 1, 15, 3); hurt(mine[4], 4, 15, 3, status="INJURY_RESERVE")  # RB1 out a week, RB4 on NFL IR
    rows = {r["name"]: r["verdict"] for r in run(mine, 3, 60, ir_slots=1)}
    assert rows == {"RB1": "hold", "RB4": "ir"}


def test_two_stashes_do_not_both_swap_with_the_same_occupant():
    mine = roster(); hurt(mine[1], 6, 15, 3); hurt(mine[2], 6, 15, 3)   # RB1 and RB2, both back week 9
    hurt(mine[9], 15, 15, 3); mine[9].slot = "IR"                          # TE2 on IR, done for the year
    rows = {r["name"]: r for r in run(mine, 3, 60, ir_slots=1)}
    assert rows["RB1"]["verdict"] == "ir" and rows["RB1"]["ir_occupant"] == "TE2"
    assert rows["RB2"]["verdict"] == "hold" and rows["RB2"]["ir_occupant"] is None


def _backup_out(mu, fa_vorp, weeks=4):
    """A bench RB at `mu`/g who would not start on return, out `weeks`, vs a pickup who would not start either."""
    mine = roster(); mine[4].mu = mine[4].mu_ros = mu; hurt(mine[4], weeks, 15, 3)
    starters = {p.espn_id for p in mine if p.name != "RB4"}
    w = [{"name": "FA", "pos": "RB", "slot": "RB", "delta_over_starter": -3.0, "vorp": fa_vorp, "streamer": False}]
    return run(mine, 3, 60, waivers=w, starters=starters, repl={"RB": 8.0})[0]


def test_a_backup_below_the_wire_is_dropped_for_a_pickup_above_it():
    row = _backup_out(5.0, 4.0)  # the Jonathon Brooks case: 5/g when back, replacement is 8
    assert row["hold_value"] == 0 and row["drop_value"] == pytest.approx(13.8, abs=0.1)
    assert row["verdict"] == "drop" and "FA" in row["why"][0] and row["best_fa"]["ppw"] == pytest.approx(1.0)


def test_a_backup_above_the_wire_is_held_over_a_marginal_pickup():
    row = _backup_out(9.5, 1.0)  # the Josh Jacobs case: clear of replacement (8) though behind every RB starter
    assert row["hold_value"] == pytest.approx(0.25 * 1.5 * 9.8, abs=0.1) and row["verdict"] == "hold"


def test_just_above_the_wire_is_a_hold_that_says_what_he_is_worth():
    row = _backup_out(8.5, 0.0)  # clears replacement by half a point, so not dead, and the pickup adds nothing
    assert row["verdict"] == "hold" and row["why"][0] == "worth 1 pts on return vs 0 from FA"


def test_below_the_wire_on_return_is_a_dead_spot_even_with_nothing_to_add():
    row = _backup_out(5.0, 0.0)  # 5/g when back, replacement is 8, no pickup worth anything
    assert row["verdict"] == "drop" and "dead roster spot" in row["why"][0]


def test_a_dead_spot_that_is_not_the_cheapest_cut_holds_and_names_the_cheaper_one():
    mine = roster(); mine[4].mu = mine[4].mu_ros = 5.0; hurt(mine[4], 4, 15, 3)   # RB4 dead weight, 4 weeks
    mine[9].mu = mine[9].mu_ros = 2.0                                             # TE2 at 2/g is cheaper still
    starters = {p.espn_id for p in mine if p.name not in ("RB4", "TE2")}
    (row,) = run(mine, 3, 60, starters=starters, repl={"RB": 8.0})
    assert row["verdict"] == "hold" and "TE2 is the cheaper drop" in row["why"][0]


# ---------- who fills the freed spot ----------

def depth_fa(name, pos="RB", score=1.0):
    return {"name": name, "pos": pos, "slot": pos, "delta_over_starter": -3.0, "vorp": -1.0, "score": score, "streamer": False}


def test_a_freed_spot_names_a_pickup_even_when_nobody_on_the_wire_beats_replacement():
    mine = roster(); hurt(mine[1], 15, 15, 3)  # RB1 done for the year, no IR slot: a drop
    (row,) = run(mine, 3, 60, waivers=[depth_fa("Body A", score=2.0), depth_fa("Body B", score=5.0)])
    assert row["verdict"] == "drop" and row["add"] == {"name": "Body B", "pos": "RB", "kind": "depth", "why": "best body on the wire, depth only"}


def test_a_free_agent_handcuff_beats_a_depth_body_for_the_freed_spot():
    mine = roster(); hurt(mine[1], 15, 15, 3)
    cuffs = [{"starter": "RB2", "handcuff": "Backup", "owner_team_id": None, "est_value": 1.1},
             {"starter": "RB1", "handcuff": "Owned Guy", "owner_team_id": 4, "est_value": 3.0}]
    (row,) = run(mine, 3, 60, waivers=[depth_fa("Body B", score=5.0)], handcuffs=cuffs)
    assert row["add"]["name"] == "Backup" and row["add"]["why"] == "handcuff for RB2"


def test_a_real_upgrade_still_comes_first_and_two_spots_get_two_names():
    mine = roster(); hurt(mine[1], 15, 15, 3); hurt(mine[2], 15, 15, 3)  # RB1 and RB2 done; one IR slot, one drop
    cuffs = [{"starter": "RB3", "handcuff": "Backup", "owner_team_id": None, "est_value": 1.1}]
    rows = {r["name"]: r for r in run(mine, 3, 60, ir_slots=1, waivers=fa(1.5, name="Starter FA") + [depth_fa("Body B")], handcuffs=cuffs)}
    assert rows["RB1"]["verdict"] == "ir" and rows["RB1"]["add"]["name"] == "Starter FA" and rows["RB1"]["add"]["kind"] == "upgrade"
    assert rows["RB2"]["verdict"] == "drop" and rows["RB2"]["add"]["name"] == "Backup"


def test_an_ir_swap_frees_nothing_so_names_nobody():
    mine = roster(); hurt(mine[1], 6, 15, 3)
    hurt(mine[9], 15, 15, 3); mine[9].slot = "IR"
    row = next(r for r in run(mine, 3, 60, ir_slots=1, waivers=[depth_fa("Body B")]) if r["name"] == "RB1")
    assert row["verdict"] == "ir" and row["ir_occupant"] == "TE2" and row["add"] is None
