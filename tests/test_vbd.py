from ff.model.vbd import own_starter_value, replacement_levels, starters_per_pos, tiers
from tests.conftest import P


def test_starters_per_pos(slots):
    s = starters_per_pos(slots)
    assert abs(s["RB"] - 2.45) < 1e-9 and abs(s["TE"] - 1.1) < 1e-9


def test_replacement_levels(slots):
    pool = [P(i, f"RB{i}", "RB", 20 - i) for i in range(40)]
    repl = replacement_levels(pool, slots, team_count=10)
    # 10 teams * 2.45 = 24.5 -> index 24 -> mu = 20-24 = -4
    assert repl["RB"] == -4


def test_own_starter_value():
    lineup = {"RB": [P(1, "a", "RB", 10), P(2, "b", "RB", 6)], "QB": [P(3, "q", "QB", 20)]}
    d, slot = own_starter_value(P(9, "fa", "RB", 9), lineup)
    assert d == 3 and slot == "RB"
    d, slot = own_starter_value(P(10, "k", "K", 9), lineup)
    assert d == 0 and slot == ""


def test_tiers():
    ps = [P(1, "a", "WR", 20), P(2, "b", "WR", 19.5), P(3, "c", "WR", 10)]
    t = tiers(ps)
    assert [len(x) for x in t] == [2, 1]
