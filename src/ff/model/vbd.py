"""Value over replacement / over own starter."""
from __future__ import annotations

from collections import defaultdict

from .projections import PlayerProj

CORE = ("QB", "RB", "WR", "TE", "K", "D/ST")


def starters_per_pos(lineup_slots: dict[str, int]) -> dict[str, float]:
    """Expected starters per position incl. FLEX absorption (RB/WR/TE split ~45/45/10)."""
    n = defaultdict(float)
    for slot, cnt in lineup_slots.items():
        if slot in CORE:
            n[slot] += cnt
        elif slot == "RB/WR/TE":
            n["RB"] += 0.45 * cnt; n["WR"] += 0.45 * cnt; n["TE"] += 0.10 * cnt
        elif slot == "RB/WR":
            n["RB"] += 0.5 * cnt; n["WR"] += 0.5 * cnt
        elif slot == "WR/TE":
            n["WR"] += 0.8 * cnt; n["TE"] += 0.2 * cnt
        elif slot == "OP":
            n["QB"] += cnt
    return dict(n)


def replacement_levels(pool: list[PlayerProj], lineup_slots: dict[str, int], team_count: int, key: str = "mu_ros") -> dict[str, float]:
    """Replacement = the (teams*starters + 1)-th best player at the position across the whole league pool."""
    spp = starters_per_pos(lineup_slots)
    out = {}
    by_pos = defaultdict(list)
    for p in pool:
        by_pos[p.pos].append(getattr(p, key))
    for pos, vals in by_pos.items():
        vals.sort(reverse=True)
        idx = int(round(team_count * spp.get(pos, 0)))
        out[pos] = vals[idx] if idx < len(vals) else (vals[-1] if vals else 0.0)
    return out


def vorp(p: PlayerProj, repl: dict[str, float], key: str = "mu_ros") -> float:
    return round(getattr(p, key) - repl.get(p.pos, 0.0), 2)


def own_starter_value(p: PlayerProj, my_lineup: dict[str, list[PlayerProj]], key: str = "mu_ros") -> tuple[float, str]:
    """Value over the weakest starter p could displace on MY roster. Returns (delta, slot)."""
    best = (-1e9, "")
    for slot, starters in my_lineup.items():
        if slot in p.eligible and starters:
            weakest = min(getattr(s, key) for s in starters)
            d = getattr(p, key) - weakest
            if d > best[0]:
                best = (d, slot)
    if best[1] == "":
        return (0.0, "")
    return (round(best[0], 2), best[1])


def tiers(players: list[PlayerProj], key: str = "mu_ros", gap: float = 1.5) -> list[list[PlayerProj]]:
    """Greedy tiering: new tier when the drop to the next player exceeds `gap` points."""
    ps = sorted(players, key=lambda x: -getattr(x, key))
    out, cur = [], []
    for p in ps:
        if cur and getattr(cur[-1], key) - getattr(p, key) > gap:
            out.append(cur); cur = []
        cur.append(p)
    if cur:
        out.append(cur)
    return out
