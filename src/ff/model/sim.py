"""Monte Carlo rest-of-season simulation -> playoff and title odds."""
from __future__ import annotations

import numpy as np


def simulate(team_ids: list[int], records: dict[int, tuple[int, int, float]], strength: dict[int, tuple[float, float]],
             remaining: list[list[tuple[int, int]]], playoff_teams: int, playoff_rounds: int, n: int = 4000, seed: int = 7) -> dict[int, dict]:
    """
    records: team -> (wins, losses, points_for)
    strength: team -> (mu, var) weekly optimal-lineup distribution
    remaining: per remaining week, list of (home, away) pairs
    Returns team -> {playoff_pct, title_pct, exp_wins}
    """
    rng = np.random.default_rng(seed)
    idx = {t: i for i, t in enumerate(team_ids)}
    T = len(team_ids)
    mu = np.array([strength[t][0] for t in team_ids])
    sd = np.sqrt(np.array([max(strength[t][1], 1.0) for t in team_ids]))
    wins = np.tile(np.array([records[t][0] for t in team_ids], dtype=float), (n, 1))
    pf = np.tile(np.array([records[t][2] for t in team_ids], dtype=float), (n, 1))

    for week in remaining:
        scores = rng.normal(mu, sd, size=(n, T))
        pf += scores
        for h, a in week:
            if a is None or h is None:
                continue
            hi, ai = idx[h], idx[a]
            hw = scores[:, hi] > scores[:, ai]
            wins[:, hi] += hw
            wins[:, ai] += ~hw

    # Seed by wins then points-for
    order = np.lexsort((-pf, -wins), axis=1)  # shape (n, T), best first
    made = np.zeros((n, T), dtype=bool)
    for s in range(playoff_teams):
        made[np.arange(n), order[:, s]] = True

    # Playoff bracket: reseed each round, 1 vs last, etc. Byes if playoff_teams is 6 (top 2).
    champ = np.zeros(T)
    for i in range(n):
        alive = list(order[i, :playoff_teams])
        for _ in range(playoff_rounds):
            if len(alive) == 1:
                break
            byes = []
            if len(alive) == 6:
                byes, alive = alive[:2], alive[2:]
            nxt = []
            while len(alive) >= 2:
                a, b = alive.pop(0), alive.pop(-1)
                sa, sb = rng.normal(mu[a], sd[a]), rng.normal(mu[b], sd[b])
                nxt.append(a if sa > sb else b)
            alive = byes + sorted(nxt, key=lambda t: list(order[i]).index(t))
        if alive:
            champ[alive[0]] += 1

    return {t: {"playoff_pct": round(100 * made[:, i].mean(), 1), "title_pct": round(100 * champ[i] / n, 1),
                "exp_wins": round(float(wins[:, i].mean()), 2)} for t, i in idx.items()}
