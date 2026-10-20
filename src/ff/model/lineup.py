"""Slot assignment maximizing P(win) vs an opponent distribution (not E[points])."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from math import erf, sqrt

from .projections import PlayerProj

# The P(win) lineup may bench a higher-points player only when it buys at least this much P(win) over the
# highest-points lineup. Sigma is a positional guess (`projections.BASE_SIGMA`, `CV_FLOOR`) scaled by a
# FantasyPros rank-sd fudge, not a fitted number, so a 0.3pp edge from it is noise and the points are real. The floor
# comes down once variance is fitted from the projlog residuals (TODO D2).
MIN_WIN_GAIN = 0.015

# What an empty starter slot prints as (the packet, the card and the email all read it by this string).
EMPTY_SLOT = "(EMPTY — no eligible player)"
# A player this likely to sit scores zero for lineup purposes: on bye, out, on IR, or a researched scratch. He never
# starts, even into an otherwise empty slot; the slot reads EMPTY and the card says who fills it (B15).
NEVER_STARTS_AT = 0.99


def startable(p: PlayerProj) -> bool:
    """Worth a starter slot this week: has a game and some expectation of playing it."""
    return p.ev > 0 and not p.bye and p.p_zero < NEVER_STARTS_AT


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
    # P(win) bought over the highest-points lineup against the same opponent: 0.0 when this is that lineup (including
    # when the search found a better P(win) but under MIN_WIN_GAIN), None when there was no P(win) search.
    win_gain: float | None = None
    # Seats per slot nobody startable could fill (a two-RB slot with one healthy RB has one): `to_dict` prints one
    # EMPTY marker per seat, so the card sees every hole, not only a slot with nobody in it.
    holes: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "slots": {s: ([p.name for p in ps] + [EMPTY_SLOT] * self.holes.get(s, 0)) or [EMPTY_SLOT] for s, ps in self.assignment.items()},
            "mu": round(self.mu, 2), "sd": round(self.var**0.5, 2),
            "p_win": round(self.p_win, 3) if self.p_win is not None else None,
            "win_gain": round(self.win_gain, 3) if self.win_gain is not None else None,
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

    A P(win) search is held to MIN_WIN_GAIN: when the best P(win) lineup beats the highest-points lineup by less than
    that, the highest-points lineup is returned (with its P(win)) and `win_gain` reads 0.0.
    """
    use_win = objective == "win" or (objective == "auto" and opp_mu is not None)
    if use_win and opp_mu is None:
        use_win = False  # 'win' asked for with no opponent: nothing to beat, same as 'ev'
    ev_lineup = optimize(players, lineup_slots, opp_mu, opp_var, objective="ev") if use_win else None
    slots = _expand_slots(lineup_slots)
    # Locked players (game started) can't move: pin locked starters to their current slot and drop locked bench.
    pinned: dict[str, list[PlayerProj]] = {}
    free_players = []
    for p in players:
        if p.locked and p.slot in slots and slots.count(p.slot) > sum(len(v) for k, v in pinned.items() if k == p.slot):
            pinned.setdefault(p.slot, []).append(p)
        elif not p.locked:
            free_players.append(p)
    for s_, ps in pinned.items():
        for _ in ps:
            slots.remove(s_)
    pin_list = [p for ps in pinned.values() for p in ps]
    pin_mu, pin_var = sum(p.ev for p in pin_list), sum(p.var for p in pin_list)
    players_all = players
    players = free_players
    if not slots:
        pw = win_prob(pin_mu, pin_var, opp_mu, opp_var or 0.0) if opp_mu is not None else None
        return Lineup({s_: list(ps) for s_, ps in pinned.items()}, pin_mu, pin_var, pw,
                      [p for p in players_all if p not in pin_list], win_gain=0.0 if ev_lineup is not None else None)
    # Only a body who can score: a bye, an IR stash or a certain scratch stays out even when nobody else fits the
    # slot. Before (Oct 20) `mu > 0` let the IR kicker start at K and the fallback below seated a bye QB, so the card
    # swapped one zero for another and the header's P(win) counted two empty slots as filled.
    avail = [p for p in players if startable(p)]
    # Candidate pool per slot: exact search over the top few eligible players. For the E[points]
    # objective the answer is nearly greedy, so a small pool is enough; the win-prob objective
    # needs a wider pool because a lower-EV / higher-variance player can be optimal.
    counts = {s: slots.count(s) for s in set(slots)}
    cands: list[list[PlayerProj]] = []
    for s in slots:
        flex = "/" in s or s == "OP"
        k = (counts[s] + (3 if flex else 1)) if not use_win else (counts[s] + (5 if flex else 3))
        el = sorted([p for p in avail if s in p.eligible], key=lambda p: -p.ev)[:k]
        # Nobody startable for this slot (both QBs on bye, the only K on IR): the seat stays empty rather than hold a
        # zero, and the card names the pickup that fills it. A slot with fewer startable bodies than seats also needs
        # the empty seat as a choice, or the search finds no legal combo at all.
        if len(el) < counts[s]:
            el = el + [None]
        cands.append(el)

    def search(cands: list[list[PlayerProj | None]]):
        best = None
        seen = set()
        for combo in itertools.product(*cands):
            ids = [p.espn_id for p in combo if p is not None]
            if len(set(ids)) != len(ids):
                continue
            key = tuple(sorted(ids))
            if key in seen:
                continue
            seen.add(key)
            mu = pin_mu + sum(p.ev for p in combo if p is not None)
            var = pin_var + sum(p.var for p in combo if p is not None)
            score = win_prob(mu, var, opp_mu, opp_var or 0.0) if use_win else mu
            if best is None or score > best[0] + 1e-12 or (abs(score - best[0]) < 1e-12 and mu > best[1]):
                best = (score, mu, var, combo)
        return best

    best = search(cands)
    if best is None and any(None not in el for el in cands):
        # Every combo doubled a body (two RBs for RB and the flex, say): seats that looked filled were not. Rare, so
        # the wider search with every seat optional runs only here.
        best = search([el if None in el else el + [None] for el in cands])
    if best is None:
        return Lineup({s_: list(ps) for s_, ps in pinned.items()}, pin_mu, pin_var, None, [p for p in players_all if p not in pin_list])
    score, mu, var, combo = best
    if ev_lineup is not None:
        gain = score - ev_lineup.p_win
        if gain < MIN_WIN_GAIN:
            ev_lineup.win_gain = 0.0
            return ev_lineup
    assignment: dict[str, list[PlayerProj]] = {s_: list(ps) for s_, ps in pinned.items()}
    holes: dict[str, int] = {}
    for s, p in _settle(slots, combo):
        assignment.setdefault(s, [])
        if p is not None:
            assignment[s].append(p)
        else:
            holes[s] = holes.get(s, 0) + 1
    chosen = {p.espn_id for p in combo if p is not None} | {p.espn_id for p in pin_list}
    bench = [p for p in players_all if p.espn_id not in chosen]
    pw = win_prob(mu, var, opp_mu, opp_var or 0.0) if opp_mu is not None else None
    return Lineup(assignment, mu, var, pw, bench, win_gain=pw - ev_lineup.p_win if ev_lineup is not None else None, holes=holes)


def as_set(players: list[PlayerProj], lineup_slots: dict[str, int],
           opp_mu: float | None = None, opp_var: float | None = None) -> Lineup:
    """The lineup as ESPN shows it: whoever sits in each starter slot today, no search. What a rival will actually
    score once his lineup is set, where `optimize` is the best he could have done."""
    assignment: dict[str, list[PlayerProj]] = {s: [] for s in lineup_slots}
    bench = []
    for p in players:
        if p.slot in assignment:
            assignment[p.slot].append(p)
        else:
            bench.append(p)
    starters = [p for ps in assignment.values() for p in ps]
    mu, var = sum(p.ev for p in starters), sum(p.var for p in starters)
    pw = win_prob(mu, var, opp_mu, opp_var or 0.0) if opp_mu is not None else None
    return Lineup(assignment, mu, var, pw, bench)


def is_complete(lineup: Lineup, lineup_slots: dict[str, int]) -> bool:
    """Every starter slot holds a player who has a game this week: nothing left for the manager to do."""
    return all(len(lineup.assignment.get(s, [])) >= n and not any(p.bye for p in lineup.assignment.get(s, []))
               for s, n in lineup_slots.items())


def _settle(slots: list[str], combo: tuple) -> list[tuple[str, PlayerProj | None]]:
    """Re-seat the chosen starters so as many as possible keep the ESPN slot they are already in.

    The search returns the first combo with the best score, and slot order is QB, RB, WR, ... then flex, so the top
    two RBs land in RB and the third in the flex regardless of where they sit today. Same starters, two clicks that
    change nothing ("Henderson: FLEX -> RB, Tuten: RB -> FLEX"). Small exact search: at most a handful of starters."""
    players = [p for p in combo if p is not None]
    order = sorted(range(len(slots)), key=lambda i: -len([p for p in players if slots[i] in p.eligible]))  # tight slots first
    best: tuple[int, list] | None = None

    def rec(i: int, left: list[PlayerProj], acc: list[tuple[str, PlayerProj | None]], kept: int) -> None:
        nonlocal best
        if best is not None and kept + len(left) <= best[0]:
            return  # cannot beat the best seating even if every remaining player stays put
        if i == len(order):
            if best is None or kept > best[0]:
                best = (kept, list(acc))
            return
        s = slots[order[i]]
        cands = [p for p in left if s in p.eligible]
        # try the player already sitting in this slot first, then the rest; None if nobody fits (an empty slot)
        cands.sort(key=lambda p: p.slot != s)
        for p in cands or [None]:
            rest = [q for q in left if q is not p] if p is not None else left
            acc.append((s, p)); rec(i + 1, rest, acc, kept + (1 if p is not None and p.slot == s else 0)); acc.pop()
            if p is None:
                break

    rec(0, players, [], 0)
    if best is None or len([p for _, p in best[1] if p is not None]) != len(players):
        return list(zip(slots, combo))  # a seating that drops someone is worse than the original; keep it
    seated = dict(zip(order, best[1]))
    return [seated[i] for i in range(len(slots))]


def compare(ev_lineup: Lineup, win_lineup: Lineup) -> list[dict]:
    """Players that differ between the E[points] lineup and the P(win) lineup."""
    a = {p.espn_id: p for ps in ev_lineup.assignment.values() for p in ps}
    b = {p.espn_id: p for ps in win_lineup.assignment.values() for p in ps}
    out = []
    for pid in set(a) ^ set(b):
        p = a.get(pid) or b.get(pid)
        out.append({"name": p.name, "in": "ev" if pid in a else "win", "ev": round(p.ev, 2), "sd": round(p.var**0.5, 2)})
    return out
