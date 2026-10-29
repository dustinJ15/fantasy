"""The roster-spot ledger behind one league's checklist: who the cheapest drop is, what cutting him costs, and how
many bodies each position may hold.

`report.todos` builds the rows; this module owns the spots they spend. Every add needs a spot and every spot is spent
once, so the activate row and the waiver row cannot both name the same body (they did, once: Jaxson Dart went twice in
one morning). The drop order is `model.injuries.drop_cost`, the number the Drop row ranks by too, so the two agree.
"""
from __future__ import annotations

from collections import Counter

from .model import acceptance, injuries
from .model.lineup import NEVER_STARTS_AT

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


def bodies_ahead(lg: dict, p: dict) -> list[dict]:
    """My bodies at his position, off the IR slot, worth more the rest of the season than he is, best first."""
    ahead = [q for q in lg["roster"] if q["name"] != p["name"] and q["pos"] == p["pos"] and q.get("slot") != "IR"
             and (q.get("mu_ros") or 0.0) > (p.get("mu_ros") or 0.0)]
    return sorted(ahead, key=lambda q: -(q.get("mu_ros") or 0.0))


def depth_share(lg: dict, p: dict) -> float:
    """`model.injuries.depth_share` for a roster body: a tenth of his points when he is the third or later body at a
    one-starter position (the QB3 in a one-QB league), else all of them."""
    return injuries.depth_share(p["pos"], len(bodies_ahead(lg, p)), (lg.get("settings") or {}).get("lineup_slots"))


def offer_hold(lg: dict, name: str) -> tuple[dict, float] | None:
    """(the open offer of mine he sits in, what cancelling it forgoes in points a week) or None when he is in none. The
    forgone number is the offer's chance of landing (`p_accept` from the scan when the package matched one, else the
    acceptance prior) times my gain a week from it (`my_delta_ppw`, zero when the offer is not priced or costs me).
    An accepted trade is not an offer: `packet.apply_accepted_trades` already moved him."""
    for t in lg.get("outgoing_trades") or []:
        if t.get("accepted") or name not in (t.get("give") or []):
            continue
        p_acc = t.get("p_accept")
        p_acc = acceptance.BASE if p_acc is None else float(p_acc)
        return t, round(p_acc * max(float(t.get("my_delta_ppw") or 0.0), 0.0), 2)
    return None


def drop_cost(p: dict, lg: dict) -> float:
    """What a cut costs me, from `model.injuries.drop_cost`: rest-of-season points a week (a tenth of them for a QB3
    behind two healthy QBs, `depth_share`), the market penalty for cutting a player someone would trade for, the
    insurance a handcuff to my RB1 carries, what cancelling an open offer he sits in forgoes (`offer_hold`), less
    the week a body on bye or likely to sit gives the Sunday pickup nothing for. The Drop row ranks by the same
    number."""
    cuff = sum(h.get("est_value") or 0.0 for h in lg.get("handcuffs") or [] if h.get("handcuff") == p["name"])
    held = offer_hold(lg, p["name"])
    return injuries.drop_cost(p["mu_ros"], market=p.get("market"), handcuff_value=cuff,
                              sit_this_week=1.0 if p.get("bye") else (p.get("p_zero") or 0.0), weeks_out=p.get("weeks_out") or 0.0,
                              mu_ros_active=p.get("mu_ros_active"), weeks_remaining=weeks_left(lg),
                              depth_share=depth_share(lg, p), offer_hold=held[1] if held else 0.0)


def depth_note(lg: dict, p: dict) -> str:
    """"QB3 behind Herbert and Lawrence, starts only if both are out" when `depth_share` priced him as the third
    body at a one-starter position; empty otherwise."""
    if depth_share(lg, p) >= 1.0:
        return ""
    ahead = bodies_ahead(lg, p)
    return f"{p['pos']}{len(ahead) + 1} behind {' and '.join(q['name'] for q in ahead[:2])}, starts only if both are out"


def offer_note(lg: dict, name: str) -> str:
    """"in your Rodgers, Hubbard for Jones offer to Them: cancel it first, ESPN will not drop a player in a pending
    trade; the offer is 35% to land for +1.2/wk, so cancelling forgoes ~0.4/wk" for a drop who sits in an open offer
    of mine; empty when he is in none. No parenthetical: `report._spot_words` opens the drop note's first one."""
    held = offer_hold(lg, name)
    if held is None:
        return ""
    t, ppw = held
    out = (f"in your {', '.join(t.get('give') or []) or 'nothing'} for {', '.join(t.get('get') or []) or 'nothing'} offer to "
           f"{t.get('rival') or 'them'}: cancel it first, ESPN will not drop a player in a pending trade")
    if t.get("my_delta_ppw") is not None:
        p_acc = acceptance.BASE if t.get("p_accept") is None else float(t["p_accept"])
        out += f"; the offer is {p_acc:.0%} to land for {float(t['my_delta_ppw']):+.1f}/wk, so cancelling forgoes ~{ppw:.1f}/wk"
    return out


def drop_click(lg: dict, name: str) -> str:
    """The click that cuts him: "drop X", or "cancel your offer to Them, then drop X" when he sits in an open offer of
    mine (ESPN refuses the drop until it is cancelled)."""
    held = offer_hold(lg, name)
    if held is None:
        return f"drop {name}"
    return f"cancel your offer to {held[0].get('rival') or 'them'}, then drop {name}"


def sit_note(p: dict) -> str:
    """"on bye this week" / "out this week" / "90% to sit this week" when this week is the reason he is cheap; empty
    otherwise. An Out designation (or a researched scratch at `NEVER_STARTS_AT`) is "out", never "100% to sit"."""
    if p.get("bye"):
        return "on bye this week"
    if (p.get("p_zero") or 0.0) >= NEVER_STARTS_AT:
        return "out this week"
    if (p.get("p_zero") or 0.0) >= RISKY_TO_SIT:
        return f"{p['p_zero']:.0%} to sit this week"
    return ""


def lock_note(p: dict) -> str:
    """"locked until the week rolls, his game has kicked off" for a body ESPN will not let go until Tuesday; empty otherwise."""
    return "locked until the week rolls, his game has kicked off" if p.get("locked") else ""


def weeks_word(r: dict) -> str:
    """"~4 wks" or "the season" for an injury row's horizon."""
    if r.get("return_week") is None and (r.get("avail_ros") or 0) == 0:
        return "the season"
    return f"~{r['weeks_out']:.0f} wk{'s' if r['weeks_out'] >= 1.5 else ''}"


def drop_verdict_note(r: dict) -> str:
    """"on IR, out ~4 wks, worth ~0 pts the rest of the way": why a Drop-verdict player is the free drop, for the
    detail of whichever row takes him."""
    on_ir = "on IR, " if (r.get("espn_status") or "").upper() in ("INJURY_RESERVE", "IR") else ""
    return f"{on_ir}out {weeks_word(r)}, worth ~{r.get('hold_value') or 0:.0f} pts the rest of the way"


def free_drops(lg: dict, exclude: set[str] = frozenset()) -> list[str]:
    """The players `model.injuries.decide` already said to drop, in its order (most valuable first). Each is a free
    drop for any row that needs a spot, whatever his position: the K/D/ST exclusion in `bench` is for healthy
    specialists, and a kicker on IR with a Drop verdict is a spot, not a body (B12: the cover row cut a healthy RB4
    for a kicker while the Drop row dropped the kicker on IR for a depth body)."""
    return [r["name"] for r in lg.get("injuries") or [] if r.get("verdict") == "drop" and r["name"] not in exclude]


def bench(lg: dict, exclude: set[str] = frozenset()) -> list[dict]:
    starters = {n for names in lg["lineup_win"]["slots"].values() for n in names}
    return [p for p in lg["roster"] if p["name"] not in starters and p["pos"] not in ("K", "D/ST") and p.get("slot") != "IR"
            and p["name"] not in exclude]


def drop_order(lg: dict, exclude: set[str] = frozenset()) -> list[str]:
    """The Drop-verdict players first at cost 0 (`free_drops`), then the bench cheapest first by `drop_cost`
    (rest-of-season value plus the market penalty), skipping K/DST, the IR slot and `exclude`.

    `mu_ros` already nets out the games a hurt player will miss, so a season-ender is the cheapest cut and a
    four-week stash is not. The IR occupant is skipped because dropping him frees an IR slot, not a bench spot. The
    market term is the B6 fix: by `mu_ros` alone a rookie RB the market priced like a starter was cut before a WR4
    nobody would trade for; he is trade bait (see the `trade` verdict), not a cut.

    A locked body (his game has kicked off) sorts last whatever he costs: ESPN refuses the drop until the week rolls
    on Tuesday, so he is named only when nobody else can go, and `drop_note` says he is locked. On a Monday that is
    everyone who played Sunday; the note is the signal to wait for Tuesday's card.
    """
    free = free_drops(lg, exclude)
    rest = sorted(bench(lg, set(exclude) | set(free)), key=lambda p: (bool(p.get("locked")), drop_cost(p, lg)))
    return free + [p["name"] for p in rest]


def drop_candidate(lg: dict) -> str | None:
    order = drop_order(lg)
    return order[0] if order else None


def drop_note(lg: dict, name: str, exclude: set[str] = frozenset()) -> str:
    """The numbers behind a named drop: " (market 300, 3.0/wk)", the bye or sit risk that made him the cut this
    week, and when a body cheaper by `mu_ros` alone was passed over (for his market price, or because he backs up
    my RB1), who he is and his numbers, so the card shows them side by side. Empty when the market does not list
    the drop, this week is not the reason, and nobody was passed over. A drop ESPN has locked (his game has kicked
    off) says so, as does a cheaper body passed over only because he is locked. A Drop-verdict player (the free drop)
    gets his injury row's numbers instead: " (on IR, out ~4 wks, worth ~0 pts the rest of the way)"."""
    verdict = next((r for r in lg.get("injuries") or [] if r.get("verdict") == "drop" and r["name"] == name), None)
    if verdict is not None:
        return f" ({drop_verdict_note(verdict)})"
    pool = {p["name"]: p for p in bench(lg, exclude)}
    p = pool.get(name)
    if p is None:
        return ""
    # Passed over for a reason of his own (locked today, priced, or my RB1's backup); a body outranked only by this
    # drop's bye or sit risk is not "kept", and the note on the drop already says why he goes.
    locked_over = lambda q: bool(q.get("locked")) and not p.get("locked")  # noqa: E731
    # A body cheaper by `mu_ros` alone was kept for his market price or his handcuff value; when this drop is depth
    # (a QB3 at a tenth of his points) or sits in an open offer, the gap is this drop's, not a reason to name anyone.
    plain = depth_share(lg, p) >= 1.0 and offer_hold(lg, name) is None
    cheaper = [q for q in pool.values() if q["name"] != name and q["mu_ros"] < p["mu_ros"]
               and (locked_over(q) or (plain and drop_cost(q, lg) > drop_cost(p, lg) and (market_value(q) is not None or handcuff_for(lg, q["name"]))))]
    mv, extra = market_value(p), ", ".join(x for x in (sit_note(p), lock_note(p), depth_note(lg, p), offer_note(lg, name)) if x)
    if mv is None and not cheaper and not extra:
        return ""
    out = f" (market {mv:.0f}, {p['mu_ros']:.1f}/wk" if mv is not None else f" (not priced by the market, {p['mu_ros']:.1f}/wk"
    out += f", {extra})" if extra else ")"
    if cheaper:
        q = min(cheaper, key=lambda q: q["mu_ros"])
        qv, cuff = market_value(q), handcuff_for(lg, q["name"])
        nums = (f"market {qv:.0f}, " if qv is not None else "") + f"{q['mu_ros']:.1f}/wk"
        reason = ("locked until the week rolls, not a cut today" if locked_over(q)
                  else f"handcuff for {cuff}, not a cut" if cuff else "trade bait, not a cut")
        out += f" over {q['name']} ({nums}; {reason})"
    return out


class Spots:
    """The roster-spot ledger for one league's checklist: every add needs a spot, every spot is spent once.

    Open bench spots go first; after that each pickup or activation names the cheapest drop not already used. Before
    this, the activate row and the waiver row each picked "the" drop on their own and the card spent Jaxson Dart
    twice in one morning."""

    def __init__(self, lg: dict, open_spots: int, reserved: set[str]):
        self.lg, self.open, self.reserved, self.dropped = lg, max(int(open_spots or 0), 0), set(reserved), []
        self.gone: set[str] = set()  # drops already counted off, so a body noted twice (a Drop row the ledger then hands out) is one body
        self.freed: list[str] = []  # the IR moves above whose bench spot is open for the next row that needs one, in card order
        # Bodies per position as the rows above leave them, against ESPN's caps (the IR occupant counts).
        self.pos_of = {p["name"]: p["pos"] for p in lg["roster"]}
        self.counts = Counter(self.pos_of.values())
        self.caps = (lg.get("settings") or {}).get("position_limits") or {}
        # Spots an accepted trade frees when it processes (`trade_spots_after`): a claim that lands after that clock
        # can have one instead of a drop; a claim that lands before it (the waiver run is 3 AM, the trade 8 AM) cannot.
        self.after_open = max(int(lg.get("trade_spots_after") or 0), 0)
        self.after_ts = max((int(m.get("process_ts") or 0) for m in lg.get("pending_moves") or []), default=0) or None
        # The claims I already have in (`pending_claims`, B20): each drop is spent and each add held before any row
        # prints, so no row names either again; a claim with no drop takes an open spot on waiver day.
        for c in lg.get("pending_claims") or []:
            if c.get("drop"):
                if c["drop"] not in self.dropped:
                    self.dropped.append(c["drop"])
                self.note(add_pos=c.get("add_pos"), drop=c["drop"])
            else:
                self.open = max(self.open - 1, 0)
                self.note(add_pos=c.get("add_pos"))

    def note(self, add_pos: str | None = None, drop: str | None = None) -> None:
        """A row moved a body on or off the roster; keep the position counts honest for `cut`."""
        if add_pos:
            self.counts[add_pos] += 1
        if drop and drop in self.pos_of and drop not in self.gone:
            self.gone.add(drop)
            self.counts[self.pos_of[drop]] -= 1

    def free(self, name: str) -> None:
        """An IR move above frees a bench spot: the next row that needs one takes it instead of naming a drop."""
        self.freed.append(name)

    def take(self, for_whom: str | None = None, adding: str | None = None, lands_ts: int | None = None) -> tuple[str | None, str]:
        """(drop name or None, suffix for the row text). Uses an open spot, then the spot an IR move above frees,
        before naming a drop; the first drop named is a Drop-verdict player (`free_drops`), at cost 0. `adding` is the
        position of the player the spot is for; `lands_ts` is when the add actually lands (a claim's waiver run), so
        a claim that lands after an accepted trade processes can take the spot the trade frees."""
        self.note(add_pos=adding)
        if self.open > 0:
            self.open -= 1
            return None, " (there is an open bench spot)"
        if self.freed:
            return None, f" (into the spot {self.freed.pop(0)}'s IR move frees)"
        if lands_ts and self.after_ts and self.after_open > 0 and lands_ts >= self.after_ts:
            self.after_open -= 1
            return None, " (it lands after the accepted trade processes, so the spot the trade frees covers it; no drop)"
        excl = self.reserved | set(self.dropped) | ({for_whom} if for_whom else set())
        order = drop_order(self.lg, excl)
        if not order:
            return None, " (no obvious drop, your call who goes)"
        self.dropped.append(order[0])
        self.note(drop=order[0])
        return order[0], f"; {drop_click(self.lg, order[0])}{drop_note(self.lg, order[0], excl)}"

    def peek(self, adding: str | None = None, lands_ts: int | None = None) -> tuple[str | None, float | None]:
        """What `take` would hand the next row, without spending it: (drop name or None, what the spot costs in
        points a week). An open spot, a freed one, the spot an accepted trade frees and a Drop-verdict player cost 0;
        a named drop costs `drop_cost`; (None, None) when there is no spot and nobody to drop."""
        if self.open > 0 or self.freed:
            return None, 0.0
        if lands_ts and self.after_ts and self.after_open > 0 and lands_ts >= self.after_ts:
            return None, 0.0
        excl = self.reserved | set(self.dropped)
        order = drop_order(self.lg, excl)
        if not order:
            return None, None
        if order[0] in free_drops(self.lg, excl):
            return order[0], 0.0
        p = next((q for q in self.lg["roster"] if q["name"] == order[0]), None)
        return order[0], round(drop_cost(p, self.lg), 2) if p is not None else 0.0

    def swap(self, adding: str, drop: str) -> None:
        """A row that names its own drop (a stream swaps out the specialist it replaces): the spot is spent and the
        drop is counted, so no row below names him again and a Drop row on him folds into this one."""
        self.note(add_pos=adding, drop=drop)
        if drop not in self.dropped:
            self.dropped.append(drop)

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
