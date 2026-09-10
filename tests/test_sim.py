from ff.model.sim import simulate


def test_sim_favors_strong_team():
    ids = [1, 2, 3, 4]
    rec = {t: (0, 0, 0.0) for t in ids}
    strength = {1: (130, 200), 2: (100, 200), 3: (100, 200), 4: (100, 200)}
    remaining = [[(1, 2), (3, 4)], [(1, 3), (2, 4)], [(1, 4), (2, 3)]] * 3
    r = simulate(ids, rec, strength, remaining, playoff_teams=2, playoff_rounds=1, n=500)
    assert r[1]["playoff_pct"] > 90 and r[1]["title_pct"] > r[2]["title_pct"]
    assert abs(sum(v["title_pct"] for v in r.values()) - 100) < 1.0
