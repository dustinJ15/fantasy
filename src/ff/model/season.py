"""Rest-of-season lineup value, week by week.

`lineup_strength` prices a roster as one rest-of-season lineup over availability-weighted averages, which is how a QB on
IR for a month read as 55% of a weekly starter and nobody's slot ever went empty. Here each remaining week gets its
own greedy lineup: a player is worth his per-game number in the weeks he plays, nothing on his bye and nothing until
he is back, and the best free agent at each position sits in the pool as the body the wire would supply, so the cost
of shipping a man's only QB is the gap to the QB he could pick up, not zero and not infinity. Weeks are weighted by
`injuries.week_weights` (1 in the regular season, the team's playoff odds after), and the result is in points per
week so nothing downstream changes units.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .projections import PlayerProj

FIXED = ("QB", "RB", "WR", "TE", "K", "D/ST")
# Free agents per position kept in the fallback pool. One is the body the wire supplies; the second covers his bye.
FA_PER_POS = 2


@dataclass
class SeasonCtx:
    week: int
    weeks_remaining: int
    weights: list[float] = field(default_factory=list)   # per remaining week, len == weeks_remaining
    fa_pool: list[PlayerProj] = field(default_factory=list)

    @classmethod
    def build(cls, week: int, weeks_remaining: int, reg_season_weeks: int | None = None, playoff_pct: float | None = None,
              fas: list[PlayerProj] | None = None) -> SeasonCtx:
        W = max(int(weeks_remaining), 1)
        pp = (playoff_pct if playoff_pct is not None else 100.0) / 100.0
        weights = [1.0 if (reg_season_weeks is None or t <= reg_season_weeks) else pp for t in range(week, week + W)]
        if sum(weights) <= 0:
            weights = [1.0] * W
        return cls(week=week, weeks_remaining=W, weights=weights, fa_pool=fa_pool(fas or []))

    def with_odds(self, reg_season_weeks: int | None, playoff_pct: float | None) -> SeasonCtx:
        """The same weeks and wire, weighted by another team's playoff odds."""
        c = SeasonCtx.build(self.week, self.weeks_remaining, reg_season_weeks, playoff_pct)
        c.fa_pool = self.fa_pool
        return c


def fa_pool(fas: list[PlayerProj], per_pos: int = FA_PER_POS) -> list[PlayerProj]:
    """The best free agents at each position by per-game value: the bodies anyone can add."""
    out: list[PlayerProj] = []
    for pos in FIXED:
        ps = sorted([p for p in fas if p.pos == pos and (p.mu_ros_active or 0) > 0], key=lambda p: -(p.mu_ros_active or 0))
        out += ps[:per_pos]
    return out


def weekly_values(p: PlayerProj, week: int, weeks_remaining: int) -> list[float]:
    """What `p` is worth in each remaining week: his per-game number when he plays, nothing on his bye, nothing until
    he is back. A fractional `weeks_out` (0.3 for a Questionable) scales the first week; whole games missed zero
    whole weeks."""
    base = p.mu_ros_active if p.mu_ros_active is not None else p.mu_ros
    byes = set(p.bye_weeks or [])
    out = []
    for i, t in enumerate(range(week, week + max(weeks_remaining, 1))):
        if t in byes:
            out.append(0.0)
            continue
        avail = min(max((i + 1) - (p.weeks_out or 0.0), 0.0), 1.0)
        out.append(round(base * avail, 3))
    return out


def greedy_lineup(vals: list[tuple[PlayerProj, float]], slots: dict[str, int]) -> tuple[float, set[int]]:
    """(points, starter ids) of the EV-greedy lineup for one week: fixed slots first, best eligible each, then the
    flex slots from what is left. Exact for the standard RB/WR/TE flex; the full search stays in `lineup.optimize`
    for anything the card prints."""
    avail = sorted([(v, p) for p, v in vals if v > 0], key=lambda x: -x[0])
    used: set[int] = set()
    total = 0.0
    for slot in FIXED:
        n = slots.get(slot, 0)
        for v, p in avail:
            if n <= 0:
                break
            if p.espn_id in used or slot not in p.eligible:
                continue
            used.add(p.espn_id); total += v; n -= 1
    for slot, n in slots.items():
        if slot in FIXED:
            continue
        for v, p in avail:
            if n <= 0:
                break
            if p.espn_id in used or slot not in p.eligible:
                continue
            used.add(p.espn_id); total += v; n -= 1
    return total, used


def season_value(roster: list[PlayerProj], slots: dict[str, int], ctx: SeasonCtx) -> tuple[float, dict[int, float]]:
    """(weighted points per week, share of weighted weeks each rostered player starts). The free-agent pool is in the
    lineup search but not in the starts dict, which is about the roster being judged."""
    pool = list(roster) + [f for f in ctx.fa_pool if f.espn_id not in {p.espn_id for p in roster}]
    per_week = {p.espn_id: weekly_values(p, ctx.week, ctx.weeks_remaining) for p in pool}
    total_w = sum(ctx.weights) or 1.0
    acc = 0.0
    starts: dict[int, float] = {p.espn_id: 0.0 for p in roster}
    for i, w in enumerate(ctx.weights):
        if w <= 0:
            continue
        pts, used = greedy_lineup([(p, per_week[p.espn_id][i]) for p in pool], slots)
        acc += w * pts
        for pid in used:
            if pid in starts:
                starts[pid] += w / total_w
    return round(acc / total_w, 3), starts


def starters_this_week(roster: list[PlayerProj], slots: dict[str, int], ctx: SeasonCtx, pos: str) -> list[PlayerProj]:
    """Who fills `pos` in the first remaining week's lineup, free agents included (so the row can say "the wire")."""
    pool = list(roster) + [f for f in ctx.fa_pool if f.espn_id not in {p.espn_id for p in roster}]
    vals = [(p, weekly_values(p, ctx.week, 1)[0]) for p in pool]
    _, used = greedy_lineup(vals, slots)
    return [p for p in pool if p.espn_id in used and p.pos == pos]
