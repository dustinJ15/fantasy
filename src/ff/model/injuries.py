"""What to do with a hurt player: IR-stash, trade, drop, or hold.

One verdict per rostered player with an injury horizon, from numbers the packet already has: his per-game value on
return against the lineup I would field without him plus what he is worth as depth, the best free agent's value on the
same scale, whether an IR slot makes the stash free, and remaining weeks weighted by my playoff odds (a week-15 return
is worth almost nothing to a team at 20% and almost a full week to a team at 90%). Claude supplies `weeks_out`; nothing
here reads prose.
"""
from __future__ import annotations

from dataclasses import replace

from .lineup import optimize
from .projections import SLEEPER_ROSTER_MULTI_WEEK, PlayerProj
from .vbd import own_starter_value

# ESPN lets these designations into the IR slot in a default league (IR always; OUT since 2020). A league can be
# stricter; the snapshot cannot tell, so this is the one constant to change if the app refuses the move.
IR_ELIGIBLE = {"INJURY_RESERVE", "IR", "OUT"}
# A drop is final and a rival can claim him; a hold is re-evaluated tomorrow. So the free agent has to beat him by a
# margin: 3 season points, or a quarter of what he is still worth, whichever is larger.
DROP_MARGIN = 3.0
DROP_RATIO = 0.25
NOT_DROPPABLE = ("K", "D/ST")
ONE_STARTER = ("QB", "K", "D/ST")
# A bench player is mostly insurance: he starts in the weeks a starter is hurt or on bye. Count a quarter of his margin
# over the wire (the position's replacement level) for that, on top of any lineup spot he wins outright. Without this
# term a hurt backup and the best pickup both score 0 against the starting lineup and the rule can never drop anyone.
DEPTH_WEIGHT = 0.25
# The IR slot is for a real absence. Stashing a one-week Out means activating him next week and dropping someone then.
IR_MIN_WEEKS = 2


def week_weights(week: int, weeks_remaining: int, reg_season_weeks: int, playoff_pct: float | None) -> dict[int, float]:
    """Weight of each remaining matchup week: 1 in the regular season, my playoff odds in the playoffs."""
    pp = (playoff_pct or 0.0) / 100.0
    return {t: (1.0 if t <= reg_season_weeks else pp) for t in range(week, week + max(weeks_remaining, 1))}


def ir_eligible(p: PlayerProj) -> bool:
    st = (p.sources.get("espn_status") or "").upper()
    return st in IR_ELIGIBLE or (p.sources.get("sleeper_roster_status") or "") in SLEEPER_ROSTER_MULTI_WEEK


def _hold_ppw(p: PlayerProj, roster: list[PlayerProj], slots: dict[str, int], repl: dict[str, float]) -> float:
    """His per-game value on return: over the weakest starter in the rest-of-season lineup I field without him, plus
    his depth value over the wire."""
    without = optimize([q.ros() for q in roster if q.espn_id != p.espn_id], slots, objective="ev").assignment
    healthy = replace(p, mu_ros=p.mu_ros_active)
    d, _ = own_starter_value(healthy, without)
    return max(d, 0.0) + DEPTH_WEIGHT * max((p.mu_ros_active or 0.0) - repl.get(p.pos, 0.0), 0.0)


def fa_ppw(w: dict) -> float:
    """A free agent's per-week value on the same scale as `_hold_ppw`: lineup upgrade plus depth over replacement."""
    return max(w.get("delta_over_starter") or 0.0, 0.0) + DEPTH_WEIGHT * max(w.get("vorp") or 0.0, 0.0)


def _best_fa(p: PlayerProj, waivers: list[dict]) -> dict | None:
    """Best free agent for the spot he would free: one who fills a slot he could, else the best overall."""
    skill = [w for w in waivers if not w.get("streamer")]
    fit = [w for w in skill if w.get("slot") in p.eligible or w.get("pos") == p.pos]
    pool = fit or skill
    return max(pool, key=fa_ppw) if pool else None


def fill_spot(p: PlayerProj | None, waivers: list[dict], handcuffs: list[dict], used: set[str]) -> dict | None:
    """Who takes the bench spot an IR move or a drop frees (`p` is the player leaving), or an already open one
    (`p` is None). Being below the wire is the right bar for cutting him and the wrong one for filling the spot: an
    empty slot is worth less than any body. Order: a pickup who would start or beats replacement, else a free-agent
    handcuff for one of my RB1s, else the best body at his position by the waiver score, else the best body on the
    wire. `used` keeps two spots from naming the same player."""
    skill = [w for w in waivers if not w.get("streamer") and w["name"] not in used]
    # Like for like only at the flex positions. A backup at a one-starter position (QB, K, D/ST) is near-worthless
    # in a bench spot, so losing one is no reason to add another; the best skill body on the wire is.
    fit = [w for w in skill if p is not None and p.pos not in ONE_STARTER
           and (w.get("slot") in p.eligible or w.get("pos") == p.pos)]
    best = max(fit or skill, key=fa_ppw) if (fit or skill) else None
    if best and fa_ppw(best) > 0:
        return {"name": best["name"], "pos": best["pos"], "kind": "upgrade", "why": f"+{fa_ppw(best):.1f}/wk"}
    cuff = max((h for h in handcuffs if h.get("owner_team_id") is None and h["handcuff"] not in used),
               key=lambda h: h.get("est_value", 0), default=None)
    if cuff:
        return {"name": cuff["handcuff"], "pos": "RB", "kind": "handcuff", "why": f"handcuff for {cuff['starter']}"}
    by_score = lambda w: (w.get("score", 0), w.get("mu_ros", 0))  # the waiver score ties at the trend cap; per-game breaks it
    body = max(fit, key=by_score, default=None) or max(skill, key=by_score, default=None)
    if body:
        return {"name": body["name"], "pos": body["pos"], "kind": "depth", "why": "best body on the wire, depth only"}
    return None


def decide(mine: list[PlayerProj], slots: dict[str, int], week: int, weeks_remaining: int, reg_season_weeks: int,
           playoff_pct: float | None, ir_slots: int, waivers: list[dict], trades: list[dict], values: dict[str, dict],
           starters_week: set[int], repl: dict[str, float] | None = None, handcuffs: list[dict] | None = None) -> list[dict]:
    """One entry per hurt player (weeks_out >= 1, or already in the IR slot), most valuable first.

    `repl` is the league's replacement level per position (`vbd.replacement_levels`), the floor for depth value.
    `handcuffs` is `waivers.handcuffs` output; a free-agent one is the first choice for a freed bench spot."""
    repl = repl or {}
    handcuffs = handcuffs or []
    weights = week_weights(week, weeks_remaining, reg_season_weeks, playoff_pct)
    w_eff = sum(weights.values())
    hurt = [p for p in mine if p.weeks_out >= 1 or p.slot == "IR"]
    if not hurt:
        return []
    on_ir = [p for p in mine if p.slot == "IR"]
    ir_open = max(ir_slots - len(on_ir), 0)

    calc: dict[int, dict] = {}
    for p in hurt:
        back_eff = sum(v for t, v in weights.items() if p.return_week is not None and t >= p.return_week)
        hold_ppw = _hold_ppw(p, mine, slots, repl)
        fa = _best_fa(p, waivers)
        drop_ppw = fa_ppw(fa) if fa else 0.0
        calc[p.espn_id] = {"back_eff": back_eff, "hold_ppw": hold_ppw, "hold_value": hold_ppw * back_eff,
                           "fa": fa, "drop_value": drop_ppw * w_eff}

    # The open IR slots go to the stashes worth the most, not to whoever is listed first: a one-week Out never takes
    # the slot from a four-week IR player. Ties (two dead spots) go to the better player when healthy.
    stashable = [p for p in hurt if p.slot != "IR" and ir_eligible(p) and p.weeks_out >= IR_MIN_WEEKS]
    stashable.sort(key=lambda q: (-calc[q.espn_id]["hold_value"], -(q.mu_ros_active or 0)))
    to_ir = {p.espn_id for p in stashable[:ir_open]}
    stash_ids = {p.espn_id for p in stashable}
    swappable = list(on_ir)  # occupants not yet promised to someone
    # The cheapest cut, for the drop rows: not this week's starters, not K/DST, not anyone in or headed to the IR slot.
    droppable = [p for p in mine if p.espn_id not in starters_week and p.pos not in NOT_DROPPABLE and p.slot != "IR"
                 and p.espn_id not in to_ir]
    cheapest = min(droppable, key=lambda p: p.mu_ros) if droppable else None

    out = []
    for p in sorted(hurt, key=lambda q: -(q.mu_ros_active or 0)):
        c = calc[p.espn_id]
        v = values.get(str(p.espn_id)) or {}
        sends = [t for t in trades if t.get("sendable") and p.name in (t.get("give") or [])]
        row = {
            "espn_id": p.espn_id, "name": p.name, "pos": p.pos, "slot": p.slot, "weeks_out": p.weeks_out,
            "return_week": p.return_week, "avail_ros": p.avail_ros, "mu_ros_active": p.mu_ros_active,
            "hold_ppw": round(c["hold_ppw"], 2), "hold_value": round(c["hold_value"], 1), "drop_value": round(c["drop_value"], 1),
            "back_eff": round(c["back_eff"], 1), "w_eff": round(w_eff, 1),
            "ir_eligible": ir_eligible(p), "ir_open": ir_open, "ir_occupant": None,
            "best_fa": ({"name": c["fa"]["name"], "pos": c["fa"]["pos"], "delta_over_starter": c["fa"]["delta_over_starter"],
                         "ppw": round(fa_ppw(c["fa"]), 2)} if c["fa"] else None),
            "trades": [{"rival": t.get("rival"), "get": list(t.get("get") or [])} for t in sends],
            "market": ({"redraft_value": v.get("redraft_value"), "trend_30d": v.get("trend_30d")} if v else None),
            "why": [],
        }
        why = row["why"]
        gap = c["drop_value"] - c["hold_value"]
        margin = max(DROP_MARGIN, DROP_RATIO * c["hold_value"])
        # A dead roster spot needs no pickup to justify the drop: out for the season, back only after my season is
        # over, or below the wire when he is back (he would not start and a free agent as good is always there).
        dead = ("out for the season, dead roster spot" if p.avail_ros == 0
                else "back only after my season is decided, dead roster spot" if c["back_eff"] <= 0
                else "no better than the wire when he is back, dead roster spot" if c["hold_value"] <= 0 else None)
        row["espn_status"] = p.sources.get("espn_status")
        if p.slot == "IR":
            # ESPN decides when a stash has to leave the slot: the moment his designation is no longer one the IR
            # slot accepts, the roster is flagged and lineup moves are blocked until he is activated. A guessed
            # return week is not that signal: an Out defaults to one week, which used to print "he is back" on
            # every player still listed Out.
            if not ir_eligible(p):
                row["verdict"] = "activate"
                why.append(f"ESPN lists him {(row['espn_status'] or 'active').replace('_', ' ').lower()}, the IR slot has to be cleared")
            else:
                continue  # stashed and still out: nothing to do
        elif p.espn_id in to_ir:
            row["verdict"] = "ir"; why.append("IR slot open, the stash is free")
        elif p.espn_id in stash_ids and swappable:
            # Swap with the occupant when he is worth less the rest of the way.
            occ = min(swappable, key=lambda q: calc.get(q.espn_id, {}).get("hold_value", q.mu_ros * w_eff))
            occ_val = calc.get(occ.espn_id, {}).get("hold_value", occ.mu_ros * w_eff)
            if occ_val < c["hold_value"]:
                row["verdict"] = "ir"; row["ir_occupant"] = occ.name
                swappable.remove(occ)
                why.append(f"{occ.name} is worth less the rest of the way ({occ_val:.0f} vs {c['hold_value']:.0f} pts)")
        if "verdict" not in row:
            if sends:
                row["verdict"] = "trade"; why.append("a rival takes him in a package that helps me")
            elif c["fa"] and gap >= margin and cheapest is not None and cheapest.espn_id == p.espn_id:
                row["verdict"] = "drop"
                why.append(f"{c['fa']['name']} adds {c['drop_value']:.0f} pts the rest of the way vs {c['hold_value']:.0f} for him")
            elif dead and (cheapest is None or cheapest.espn_id == p.espn_id or p.espn_id not in {q.espn_id for q in droppable}):
                row["verdict"] = "drop"; why.append(dead)
            else:
                row["verdict"] = "hold"
                if dead:
                    why.append(f"{dead}, but {cheapest.name} is the cheaper drop")
                elif c["fa"] and gap >= margin:
                    why.append(f"{cheapest.name} is the cheaper drop" if cheapest else "nobody else to drop")
                elif not c["fa"]:
                    why.append(f"worth {c['hold_value']:.0f} pts on return and nothing on the wire to add")
                else:
                    why.append(f"worth {c['hold_value']:.0f} pts on return vs {c['drop_value']:.0f} from {c['fa']['name']}")
        out.append(row)
    # Every freed spot gets a name. An IR swap frees nothing (the occupant comes back to the bench).
    used: set[str] = set()
    for row in out:
        row["add"] = None
        if row["verdict"] in ("ir", "drop") and not row.get("ir_occupant"):
            row["add"] = fill_spot(next(p for p in hurt if p.espn_id == row["espn_id"]), waivers, handcuffs, used)
            if row["add"]:
                used.add(row["add"]["name"])
    return out
