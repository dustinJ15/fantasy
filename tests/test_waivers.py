from ff.model.waivers import faab_bid, rank_free_agents
from tests.conftest import P


def test_faab_bid_rules():
    assert faab_bid(2, 10, 100, is_streamer=True) == 1
    assert faab_bid(0, 10, 100, is_streamer=False) <= 3
    b = faab_bid(4, 12, 100, is_streamer=False)
    assert 1 <= b <= 35 and b % 2 == 1
    assert faab_bid(10, 12, 100, is_streamer=False) >= 50
    assert faab_bid(10, 12, 100, is_streamer=False, league_max_remaining=70) == 71
    assert faab_bid(5, 10, 0, is_streamer=False) == 0


def test_rank_free_agents_prefers_lineup_upgrade():
    lineup = {"RB": [P(1, "a", "RB", 10), P(2, "b", "RB", 6)], "WR": [P(3, "w", "WR", 12)], "K": [P(5, "k0", "K", 5)]}
    bench = [P(4, "bench", "RB", 4)]
    fas = [P(20, "good_rb", "RB", 9, tid=None), P(21, "meh_wr", "WR", 5, tid=None), P(22, "kicker", "K", 8, tid=None)]
    out = rank_free_agents(fas, lineup, bench, {"RB": 5, "WR": 6, "K": 6}, 12, 100, {})
    assert out[0]["name"] == "good_rb" and out[0]["bid"] > 0
    assert any(o["streamer"] for o in out if o["name"] == "kicker")


def test_a_locked_slot_is_not_an_upgrade_opportunity():
    """The flex holds a player whose game kicked off, so ESPN will not let anyone else in this week. A free agent
    who "beats" his banked score is not a move, and a card that says start him is wrong."""
    played = P(2, "already_played", "WR", 3.0, tid=1)
    played.locked, played.actual = True, 3.0
    week_lineup = {"RB/WR/TE": [played], "RB": [P(1, "rb", "RB", 12)]}
    ros_lineup = {"RB": [P(1, "rb", "RB", 12)], "WR": [P(3, "wr", "WR", 11)]}
    fas = [P(20, "vele", "WR", 9.0, tid=None)]
    out = rank_free_agents(fas, ros_lineup, [P(4, "bench", "WR", 4)], {"RB": 5, "WR": 6}, 12, 100, {},
                           week_lineup=week_lineup)
    assert "vele" in [o["name"] for o in out]
    assert all(o["delta_week"] == 0 for o in out)


def test_an_unlocked_body_in_the_same_slot_is_still_replaceable():
    played = P(2, "already_played", "WR", 3.0, tid=1)
    played.locked, played.actual = True, 3.0
    week_lineup = {"RB/WR/TE": [played, P(5, "still_to_play", "WR", 4.0)]}
    fas = [P(20, "vele", "WR", 9.0, tid=None)]
    out = rank_free_agents(fas, {"WR": [P(3, "wr", "WR", 11)]}, [P(4, "bench", "WR", 4)], {"WR": 6}, 12, 100, {},
                           week_lineup=week_lineup)
    assert out[0]["delta_week"] > 0 and out[0]["week_slot"] == "RB/WR/TE"


def test_a_kicker_who_may_sit_surfaces_a_replacement():
    """Rest-of-season the two kickers are the same player, so only the week view sees the problem."""
    sick = P(9, "sick_k", "K", 8.0, p0=0.5)
    fas = [P(30, "healthy_k", "K", 7.5, tid=None)]
    out = rank_free_agents(fas, {"K": [sick]}, [], {"K": 6}, 12, 100, {}, week_lineup={"K": [sick]})
    assert [o["name"] for o in out] == ["healthy_k"]
