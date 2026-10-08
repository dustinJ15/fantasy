from ff.model.sim import simulate


def test_sim_favors_strong_team():
    ids = [1, 2, 3, 4]
    rec = {t: (0, 0, 0.0) for t in ids}
    strength = {1: (130, 200), 2: (100, 200), 3: (100, 200), 4: (100, 200)}
    remaining = [[(1, 2), (3, 4)], [(1, 3), (2, 4)], [(1, 4), (2, 3)]] * 3
    r = simulate(ids, rec, strength, remaining, playoff_teams=2, playoff_rounds=1, n=500)
    assert r[1]["playoff_pct"] > 90 and r[1]["title_pct"] > r[2]["title_pct"]
    assert abs(sum(v["title_pct"] for v in r.values()) - 100) < 1.0


def test_four_identical_teams_split_the_odds_evenly():
    """Nothing in the sim may favour a seat: not the home/away column, the lexsort tiebreak, the bracket's pop(0)/pop(-1)
    pairing or the seed-order reseeding. Four equal teams on a round robin each sit near 25% for the title. n=4000 puts
    the standard error of a 25% share at 0.7pp, so 3pp is over four sigma; the seed is fixed, so the run is repeatable."""
    ids = [11, 12, 13, 14]
    rec = {t: (0, 0, 0.0) for t in ids}
    strength = {t: (100, 200) for t in ids}
    remaining = [[(11, 12), (13, 14)], [(11, 13), (12, 14)], [(11, 14), (12, 13)]] * 3
    r = simulate(ids, rec, strength, remaining, playoff_teams=2, playoff_rounds=1, n=4000, seed=7)
    for t in ids:
        assert abs(r[t]["title_pct"] - 25) < 3.0, (t, r[t])
        assert abs(r[t]["playoff_pct"] - 50) < 3.0, (t, r[t])
        assert abs(r[t]["exp_wins"] - 4.5) < 0.1, (t, r[t])
    assert abs(sum(v["title_pct"] for v in r.values()) - 100) < 1.0
    # a four-team bracket: every seat is in, two rounds, and the title is still a quarter each
    r4 = simulate(ids, rec, strength, remaining, playoff_teams=4, playoff_rounds=2, n=4000, seed=7)
    for t in ids:
        assert r4[t]["playoff_pct"] == 100.0 and abs(r4[t]["title_pct"] - 25) < 3.0, (t, r4[t])
