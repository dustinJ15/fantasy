"""The roster-spot ledger behind one league's checklist: who the cheapest drop is, what cutting him costs, and how
many bodies each position may hold.

`report.todos` builds the rows; this module owns the spots they spend. Every add needs a spot and every spot is spent
once, so the activate row and the waiver row cannot both name the same body (they did, once: Jaxson Dart went twice in
one morning). The drop order is `model.injuries.drop_cost`, the number the Drop row ranks by too, so the two agree.
"""
from __future__ import annotations

from collections import Counter

from .model import injuries

# Chance of sitting at which a starter needs a contingency plan rather than a note.
RISKY_TO_SIT = 0.4

_COUNT_WORD = {2: "two", 3: "three", 4: "four"}  # how many more bodies a half-covered cap cut still owes


def market_value(p: dict) -> float | None:
    """FantasyCalc redraft value with the 30-day trend folded in, or None when the market does not list him."""
    return injuries.market_value(p.get("market"))


def weeks_left(lg: dict) -> int:
    return int(lg.get("weeks_remaining") or max(18 - int(lg.get("week") or 1), 1))


def handcuff_for(lg: dict, name: str) -> str | None:
    """The RB starter of mine this bench player backs up, per `lg["handcuffs"]`, or None."""
    return next((h["starter"] for h in lg.get("handcuffs") or [] if h.get("handcuff") == name), None)


def drop_cost(p: dict, lg: dict) -> float:
    """What a cut costs me, from `model.injuries.drop_cost`: rest-of-season points a week, the market penalty for
    cutting a player someone would trade for, the insurance a handcuff to my RB1 carries, less the week a body on
    bye or likely to sit gives the Sunday pickup nothing for. The Drop row ranks by the same number."""
    cuff = sum(h.get("est_value") or 0.0 for h in lg.get("handcuffs") or [] if h.get("handcuff") == p["name"])
    return injuries.drop_cost(p["mu_ros"], market=p.get("market"), handcuff_value=cuff,
                              sit_this_week=1.0 if p.get("bye") else (p.get("p_zero") or 0.0), weeks_out=p.get("weeks_out") or 0.0,
                              mu_ros_active=p.get("mu_ros_active"), weeks_remaining=weeks_left(lg))


def sit_note(p: dict) -> str:
    """"on bye this week" / "90% to sit this week" when this week is the reason he is cheap; empty otherwise."""
    if p.get("bye"):
        return "on bye this week"
    if (p.get("p_zero") or 0.0) >= RISKY_TO_SIT:
        return f"{p['p_zero']:.0%} to sit this week"
    return ""


def bench(lg: dict, exclude: set[str] = frozenset()) -> list[dict]:
    starters = {n for names in lg["lineup_win"]["slots"].values() for n in names}
    return [p for p in lg["roster"] if p["name"] not in starters and p["pos"] not in ("K", "D/ST") and p.get("slot") != "IR"
            and p["name"] not in exclude]


def drop_order(lg: dict, exclude: set[str] = frozenset()) -> list[str]:
    """Bench players cheapest first by `drop_cost` (rest-of-season value plus the market penalty), skipping K/DST,
    the IR slot and `exclude`.

    `mu_ros` already nets out the games a hurt player will miss, so a season-ender is the cheapest cut and a
    four-week stash is not. The IR occupant is skipped because dropping him frees an IR slot, not a bench spot. The
    market term is the B6 fix: by `mu_ros` alone a rookie RB the market priced like a starter was cut before a WR4
    nobody would trade for; he is trade bait (see the `trade` verdict), not a cut.
    """
    return [p["name"] for p in sorted(bench(lg, exclude), key=lambda p: drop_cost(p, lg))]


def drop_candidate(lg: dict) -> str | None:
    order = drop_order(lg)
    return order[0] if order else None


def drop_note(lg: dict, name: str, exclude: set[str] = frozenset()) -> str:
    """The numbers behind a named drop: " (market 300, 3.0/wk)", the bye or sit risk that made him the cut this
    week, and when a body cheaper by `mu_ros` alone was passed over (for his market price, or because he backs up
    my RB1), who he is and his numbers, so the card shows them side by side. Empty when the market does not list
    the drop, this week is not the reason, and nobody was passed over."""
    pool = {p["name"]: p for p in bench(lg, exclude)}
    p = pool.get(name)
    if p is None:
        return ""
    # Passed over for a reason of his own (priced, or my RB1's backup); a body outranked only by this drop's bye or
    # sit risk is not "kept", and the note on the drop already says why he goes.
    cheaper = [q for q in pool.values() if q["name"] != name and q["mu_ros"] < p["mu_ros"] and drop_cost(q, lg) > drop_cost(p, lg)
               and (market_value(q) is not None or handcuff_for(lg, q["name"]))]
    mv, sit = market_value(p), sit_note(p)
    if mv is None and not cheaper and not sit:
        return ""
    out = f" (market {mv:.0f}, {p['mu_ros']:.1f}/wk" if mv is not None else f" (not priced by the market, {p['mu_ros']:.1f}/wk"
    out += f", {sit})" if sit else ")"
    if cheaper:
        q = min(cheaper, key=lambda q: q["mu_ros"])
        qv, cuff = market_value(q), handcuff_for(lg, q["name"])
        nums = (f"market {qv:.0f}, " if qv is not None else "") + f"{q['mu_ros']:.1f}/wk"
        out += f" over {q['name']} ({nums}; {f'handcuff for {cuff}' if cuff else 'trade bait'}, not a cut)"
    return out


class Spots:
    """The roster-spot ledger for one league's checklist: every add needs a spot, every spot is spent once.

    Open bench spots go first; after that each pickup or activation names the cheapest drop not already used. Before
    this, the activate row and the waiver row each picked "the" drop on their own and the card spent Jaxson Dart
    twice in one morning."""

    def __init__(self, lg: dict, open_spots: int, reserved: set[str]):
        self.lg, self.open, self.reserved, self.dropped = lg, max(int(open_spots or 0), 0), set(reserved), []
        self.gone: set[str] = set()  # drops already counted off, so a body noted twice (a Drop row the ledger then hands out) is one body
        # Bodies per position as the rows above leave them, against ESPN's caps (the IR occupant counts).
        self.pos_of = {p["name"]: p["pos"] for p in lg["roster"]}
        self.counts = Counter(self.pos_of.values())
        self.caps = (lg.get("settings") or {}).get("position_limits") or {}

    def note(self, add_pos: str | None = None, drop: str | None = None) -> None:
        """A row moved a body on or off the roster; keep the position counts honest for `cut`."""
        if add_pos:
            self.counts[add_pos] += 1
        if drop and drop in self.pos_of and drop not in self.gone:
            self.gone.add(drop)
            self.counts[self.pos_of[drop]] -= 1

    def take(self, for_whom: str | None = None, adding: str | None = None) -> tuple[str | None, str]:
        """(drop name or None, suffix for the row text). Uses an open spot before naming a drop. `adding` is the
        position of the player the spot is for."""
        self.note(add_pos=adding)
        if self.open > 0:
            self.open -= 1
            return None, " (there is an open bench spot)"
        excl = self.reserved | set(self.dropped) | ({for_whom} if for_whom else set())
        order = drop_order(self.lg, excl)
        if not order:
            return None, " (no obvious drop, your call who goes)"
        self.dropped.append(order[0])
        self.note(drop=order[0])
        return order[0], f"; drop {order[0]}{drop_note(self.lg, order[0], excl)}"

    def fill(self, add_pos: str) -> bool:
        """Spend an open spot on a body at `add_pos` without naming a drop (the Open-spot row). False when none is left."""
        if self.open <= 0:
            return False
        self.open -= 1
        self.note(add_pos=add_pos)
        return True

    def cut(self, t: dict) -> tuple[list[str], str]:
        """(drops, suffix): the cuts ESPN demands inside the trade screen for a position the trade pushes over its
        cap ("Too many players with default position WR (maximum 6)").

        `model.trades` named them on the untouched roster (`drops`); this re-checks against what the rows above
        already moved, because a waiver row that dropped the sixth WR has cleared the cap and a pickup that added
        one has made it worse. Trade rows are alternatives, so these cuts are not spent on the ledger."""
        named = t.get("drops") or []
        if "get_pos" in t:
            after = Counter(self.counts)
            after.update(t["get_pos"])
            after.subtract(self.pos_of.get(n) for n in t.get("give") or [] if n in self.pos_of)
            excess = {pos: after[pos] - cap for pos, cap in self.caps.items() if after[pos] > cap}
        else:
            excess = dict(Counter(d["pos"] for d in named))
        drops, found, short = [], [], {}  # found: positions with at least one named cut; short: bodies still owed per position
        for pos, n in excess.items():
            excl = self.reserved | set(self.dropped) | set(drops) | set(t.get("give") or [])
            pool = list(dict.fromkeys([d["name"] for d in named if d["pos"] == pos and d["name"] not in excl]
                                      + [p for p in drop_order(self.lg, excl) if self.pos_of.get(p) == pos]))
            drops += pool[:n]
            if pool:
                found.append(pos)
            if len(pool) < n:
                short[pos] = n - len(pool)
        return drops, _cut_suffix(self.caps, drops, found, short)


def _cut_suffix(caps: dict, drops: list[str], found: list[str], short: dict[str, int]) -> str:
    """The words on a `Spots.cut`: the drops with every position a cut was found for, including one the bench only
    half covers (B11: filtering it out as `stuck` printed "()" and then said nobody was found right after naming
    him), then the positions with nobody to cut."""
    cap = lambda pos: f"ESPN caps {pos} at {caps.get(pos)}"  # noqa: E731
    parts = []
    if drops:
        part = f"drop {', '.join(drops)} in the trade screen ({'; '.join(cap(p) for p in found)})"
        owed = [f"one more {pos} has to go" if k == 1 else f"{_COUNT_WORD.get(k, str(k))} more {pos}s have to go"
                for pos, k in short.items() if pos in found]
        if owed:
            part += f" and {', '.join(owed)}, your call"
        parts.append(part)
    for pos in short:
        if pos not in found:
            parts.append(f"{cap(pos)} and there is no obvious {pos} to drop, your call")
    return ("; " + "; ".join(parts)) if parts else ""
