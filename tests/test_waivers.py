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
