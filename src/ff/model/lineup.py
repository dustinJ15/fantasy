"""Slot assignment maximizing P(win) vs an opponent distribution (not E[points])."""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from math import erf, sqrt

from .projections import PlayerProj


def phi(z: float) -> float:
    return 0.5 * (1 + erf(z / sqrt(2)))


def win_prob(mu_me: float, var_me: float, mu_opp: float, var_opp: float) -> float:
    denom = sqrt(max(var_me + var_opp, 1e-9))
    return phi((mu_me - mu_opp) / denom)


@dataclass
class Lineup:
    assignment: dict[str, list[PlayerProj]]
    mu: float
    var: float
    p_win: float | None
    bench: list[PlayerProj]

    def to_dict(self) -> dict:
        return {
            "slots": {s: [p.name for p in ps] for s, ps in self.assignment.items()},
            "mu": round(self.mu, 2), "sd": round(self.var**0.5, 2),
            "p_win": round(self.p_win, 3) if self.p_win is not None else None,
            "bench": [p.name for p in self.bench],
        }


def _expand_slots(lineup_slots: dict[str, int]) -> list[str]:
    slots = []
    # fill specific positions first so FLEX search sees leftovers; order: QB,RB,WR,TE,K,D/ST then flex-ish
    order = sorted(lineup_slots.items(), key=lambda kv: (("/" in kv[0]) or kv[0] == "OP", kv[0]))
    for s, n in order:
        slots += [s] * n
    return slots


def optimize(players: list[PlayerProj], lineup_slots: dict[str, int], opp_mu: float | None = None, opp_var: float | None = None,
             objective: str = "auto") -> Lineup:
    """
    objective: 'ev' maximizes expected points; 'win' maximizes P(win) vs opponent; 'auto' = win if opponent known.
    Exact search over candidates: for each slot we consider the top-K eligible players by EV, then brute force.
    """
    use_win = objective == "win" or (objective == "auto" and opp_mu is not None)
    slots = _expand_slots(lineup_slots)
    avail = [p for p in players if p.ev > 0 or p.mu > 0]
    K = 4
    cands: list[list[PlayerProj]] = []
    for s in slots:
        el = sorted([p for p in avail if s in p.eligible], key=lambda p: -p.ev)[: K + 2]
        cands.append(el)

    best = None
    seen = set()
    for combo in itertools.product(*cands):
        ids = [p.espn_id for p in combo]
        if len(set(ids)) != len(ids):
            continue
        key = tuple(sorted(ids))
        if key in seen:
            continue
        seen.add(key)
        mu = sum(p.ev for p in combo)
        var = sum(p.var for p in combo)
        score = win_prob(mu, var, opp_mu, opp_var or 0.0) if use_win else mu
        if best is None or score > best[0] + 1e-12 or (abs(score - best[0]) < 1e-12 and mu > best[1]):
            best = (score, mu, var, combo)
    if best is None:
        return Lineup({}, 0.0, 0.0, None, list(players))
    score, mu, var, combo = best
    assignment: dict[str, list[PlayerProj]] = {}
    for s, p in zip(slots, combo):
        assignment.setdefault(s, []).append(p)
    chosen = {p.espn_id for p in combo}
    bench = [p for p in players if p.espn_id not in chosen]
    pw = win_prob(mu, var, opp_mu, opp_var or 0.0) if opp_mu is not None else None
    return Lineup(assignment, mu, var, pw, bench)


def compare(ev_lineup: Lineup, win_lineup: Lineup) -> list[dict]:
    """Players that differ between the E[points] lineup and the P(win) lineup."""
    a = {p.espn_id: p for ps in ev_lineup.assignment.values() for p in ps}
    b = {p.espn_id: p for ps in win_lineup.assignment.values() for p in ps}
    out = []
    for pid in set(a) ^ set(b):
        p = a.get(pid) or b.get(pid)
        out.append({"name": p.name, "in": "ev" if pid in a else "win", "ev": round(p.ev, 2), "sd": round(p.var**0.5, 2)})
    return out
