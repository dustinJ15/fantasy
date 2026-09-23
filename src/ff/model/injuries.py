"""What to do with a hurt player: IR-stash, trade, drop, or hold.

One verdict per rostered player with an injury horizon, from numbers the packet already has: his per-game value on
return against the lineup I would field without him, the best free agent's value over the same lineup, whether an IR
slot makes the stash free, and remaining weeks weighted by my playoff odds (a week-15 return is worth almost nothing
to a team at 20% and almost a full week to a team at 90%). Claude supplies `weeks_out`; nothing here reads prose.
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


def week_weights(week: int, weeks_remaining: int, reg_season_weeks: int, playoff_pct: float | None) -> dict[int, float]:
    """Weight of each remaining matchup week: 1 in the regular season, my playoff odds in the playoffs."""
    pp = (playoff_pct or 0.0) / 100.0
    return {t: (1.0 if t <= reg_season_weeks else pp) for t in range(week, week + max(weeks_remaining, 1))}


def ir_eligible(p: PlayerProj) -> bool:
    st = (p.sources.get("espn_status") or "").upper()
    return st in IR_ELIGIBLE or (p.sources.get("sleeper_roster_status") or "") in SLEEPER_ROSTER_MULTI_WEEK


def _hold_ppw(p: PlayerProj, roster: list[PlayerProj], slots: dict[str, int]) -> float:
    """His per-game value on return over the weakest starter in the rest-of-season lineup I field without him."""
    without = optimize([q.ros() for q in roster if q.espn_id != p.espn_id], slots, objective="ev").assignment
    healthy = replace(p, mu_ros=p.mu_ros_active)
    d, _ = own_starter_value(healthy, without)
    return max(d, 0.0)


def _best_fa(p: PlayerProj, waivers: list[dict]) -> dict | None:
    """Best free agent for the spot he would free: one who fills a slot he could, else the best overall."""
    skill = [w for w in waivers if not w.get("streamer")]
    fit = [w for w in skill if w.get("slot") in p.eligible or w.get("pos") == p.pos]
    pool = fit or skill
    return max(pool, key=lambda w: w.get("delta_over_starter", 0)) if pool else None


def decide(mine: list[PlayerProj], slots: dict[str, int], week: int, weeks_remaining: int, reg_season_weeks: int,
           playoff_pct: float | None, ir_slots: int, waivers: list[dict], trades: list[dict], values: dict[str, dict],
           starters_week: set[int]) -> list[dict]:
    """One entry per hurt player (weeks_out >= 1, or already in the IR slot), most valuable first."""
    weights = week_weights(week, weeks_remaining, reg_season_weeks, playoff_pct)
    w_eff = sum(weights.values())
    hurt = [p for p in mine if p.weeks_out >= 1 or p.slot == "IR"]
    if not hurt:
        return []
    on_ir = [p for p in mine if p.slot == "IR"]
    ir_open = max(ir_slots - len(on_ir), 0)
    droppable = [p for p in mine if p.espn_id not in starters_week and p.pos not in NOT_DROPPABLE and p.slot != "IR"]
    cheapest = min(droppable, key=lambda p: p.mu_ros) if droppable else None

    calc: dict[int, dict] = {}
    for p in hurt:
        back_eff = sum(v for t, v in weights.items() if p.return_week is not None and t >= p.return_week)
        hold_ppw = _hold_ppw(p, mine, slots)
        fa = _best_fa(p, waivers)
        drop_ppw = max(fa["delta_over_starter"], 0.0) if fa else 0.0
        calc[p.espn_id] = {"back_eff": back_eff, "hold_ppw": hold_ppw, "hold_value": hold_ppw * back_eff,
                           "fa": fa, "drop_value": drop_ppw * w_eff}

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
            "best_fa": ({"name": c["fa"]["name"], "pos": c["fa"]["pos"], "delta_over_starter": c["fa"]["delta_over_starter"]}
                        if c["fa"] else None),
            "trades": [{"rival": t.get("rival"), "get": list(t.get("get") or [])} for t in sends],
            "market": ({"redraft_value": v.get("redraft_value"), "trend_30d": v.get("trend_30d")} if v else None),
            "why": [],
        }
        why = row["why"]
        gap = c["drop_value"] - c["hold_value"]
        margin = max(DROP_MARGIN, DROP_RATIO * c["hold_value"])
        if p.slot == "IR":
            if p.return_week is not None and p.return_week <= week + 1:
                row["verdict"] = "activate"; why.append("back this week, the IR slot has to be cleared")
            else:
                continue  # stashed and still out: nothing to do
        elif row["ir_eligible"] and ir_open > 0:
            row["verdict"] = "ir"; why.append("IR slot open, the stash is free")
            ir_open -= 1  # the next hurt player down the list does not get the same slot
        elif row["ir_eligible"] and on_ir:
            # Swap with the occupant when he is worth less the rest of the way.
            occ = min(on_ir, key=lambda q: calc.get(q.espn_id, {}).get("hold_value", q.mu_ros * w_eff))
            occ_val = calc.get(occ.espn_id, {}).get("hold_value", occ.mu_ros * w_eff)
            if occ_val < c["hold_value"]:
                row["verdict"] = "ir"; row["ir_occupant"] = occ.name
                why.append(f"{occ.name} is worth less the rest of the way ({occ_val:.0f} vs {c['hold_value']:.0f} pts)")
        if "verdict" not in row:
            if sends:
                row["verdict"] = "trade"; why.append("a rival takes him in a package that helps me")
            elif p.avail_ros == 0 and (cheapest is None or cheapest.espn_id == p.espn_id or p.espn_id not in {q.espn_id for q in droppable}):
                row["verdict"] = "drop"; why.append("out for the season, dead roster spot")
            elif c["fa"] and gap >= margin and cheapest is not None and cheapest.espn_id == p.espn_id:
                row["verdict"] = "drop"
                why.append(f"{c['fa']['name']} adds {c['drop_value']:.0f} pts the rest of the way vs {c['hold_value']:.0f} for him")
            else:
                row["verdict"] = "hold"
                if c["fa"] and gap >= margin:
                    why.append(f"{cheapest.name} is the cheaper drop" if cheapest else "nobody else to drop")
                else:
                    why.append(f"worth {c['hold_value']:.0f} pts on return vs {c['drop_value']:.0f} from the best pickup")
        out.append(row)
    return out
