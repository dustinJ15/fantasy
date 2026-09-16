"""Rival roster scan and trade candidate generation, evaluated by both-side lineup delta and title-odds delta."""
from __future__ import annotations

from itertools import combinations

from .lineup import optimize
from .projections import PlayerProj

POS_ORDER = ("QB", "RB", "WR", "TE", "K", "D/ST")


def lineup_strength(roster: list[PlayerProj], slots: dict[str, int]) -> tuple[float, float]:
    """(mu, var) of the E[points]-optimal lineup using rest-of-season per-game expectations."""
    ros = [p.ros(min(p.p_zero, 0.15) if not (p.bye or p.locked) else 0.05) for p in roster]
    L = optimize(ros, slots, objective="ev")
    return L.mu, L.var


def needs(roster: list[PlayerProj], slots: dict[str, int], repl: dict[str, float]) -> dict:
    """Per-position surplus/hole: starters' avg value over replacement, and count of startable depth."""
    ros = [p.ros() for p in roster]
    L = optimize(ros, slots, objective="ev")
    starters = {p.espn_id for ps in L.assignment.values() for p in ps}
    out = {}
    for pos in POS_ORDER:
        ps = sorted([p for p in ros if p.pos == pos], key=lambda p: -p.mu)
        st = [p for p in ps if p.espn_id in starters]
        bench = [p for p in ps if p.espn_id not in starters]
        weakest_starter = min((p.mu for p in st), default=None)
        best_bench = max((p.mu for p in bench), default=None)
        out[pos] = {
            "weakest_starter": weakest_starter, "best_bench": best_bench,
            "hole": weakest_starter is not None and weakest_starter < repl.get(pos, 0) + 1.0,
            "surplus": best_bench is not None and best_bench > repl.get(pos, 0) + 3.0,
        }
    return out


def _swap(roster: list[PlayerProj], out_ids: set[int], incoming: list[PlayerProj]) -> list[PlayerProj]:
    return [p for p in roster if p.espn_id not in out_ids] + list(incoming)


def scan(my_id: int, rosters: dict[int, list[PlayerProj]], slots: dict[str, int], repl: dict[str, float],
         team_meta: dict[int, dict], values: dict[str, dict], max_per_rival: int = 3, top: int = 10) -> list[dict]:
    """
    For each rival: try 1-for-1 and 2-for-1 packages where my surplus meets their hole.

    Ranking is acceptance-first: a trade only has value if the rival says yes, and rivals (a) overvalue what they
    own, (b) infer that an offer favors the offerer, and (c) remember lowballs in a repeated game with coworkers.
    So among trades that help me by >= 0.75 ppw, sort by the rival's gain, cap the market-value ask at ~1.2x, and
    only favor 2-for-1s when the one player they get is the best piece in the deal (consolidation, which people accept).
    """
    mine = rosters[my_id]
    my_mu0, _ = lineup_strength(mine, slots)
    my_needs = needs(mine, slots, repl)
    cands = []
    # tradeable assets: skip K/DST
    my_assets = sorted([p for p in mine if p.pos not in ("K", "D/ST") and p.mu_ros > 0], key=lambda p: -p.mu_ros)[:10]
    for rid, theirs in rosters.items():
        if rid == my_id:
            continue
        their_mu0, _ = lineup_strength(theirs, slots)
        their_needs = needs(theirs, slots, repl)
        their_assets = sorted([p for p in theirs if p.pos not in ("K", "D/ST") and p.mu_ros > 0], key=lambda p: -p.mu_ros)[:10]
        rival_cands = []
        packages = [((a,), (b,)) for a in my_assets for b in their_assets]
        packages += [((a1, a2), (b,)) for a1, a2 in combinations(my_assets, 2) for b in their_assets[:5]]
        for give, get in packages:
            # crude pre-filter on market value to avoid absurd asks
            gv = sum(values.get(str(p.espn_id), {}).get("redraft_value", 0) or 0 for p in give)
            rv = sum(values.get(str(p.espn_id), {}).get("redraft_value", 0) or 0 for p in get)
            if gv and rv and (rv > gv * 1.2 or gv > rv * 2.2):
                continue
            new_mine = _swap(mine, {p.espn_id for p in give}, get)
            new_theirs = _swap(theirs, {p.espn_id for p in get}, give)
            my_mu1, _ = lineup_strength(new_mine, slots)
            their_mu1, _ = lineup_strength(new_theirs, slots)
            d_me, d_them = my_mu1 - my_mu0, their_mu1 - their_mu0
            # Must help me and be at least roughly neutral for them (win-win or need-matching),
            # otherwise it's a dump nobody accepts.
            if d_me < 0.75 or d_them < -0.75:
                continue
            why = []
            for p in get:
                if my_needs.get(p.pos, {}).get("hole") and f"fills my {p.pos} hole" not in why: why.append(f"fills my {p.pos} hole")
            for p in give:
                if their_needs.get(p.pos, {}).get("hole") and f"fills their {p.pos} hole" not in why: why.append(f"fills their {p.pos} hole")
            meta = team_meta.get(rid, {})
            games = meta.get("wins", 0) + meta.get("losses", 0)
            if games >= 4 and meta.get("losses", 0) >= meta.get("wins", 0) + 2: why.append("rival is losing (motivated)")
            # 2-for-1: consolidation (they get the single best player) is accepted; two mid pieces for a star is a lowball
            consol = 0.0
            if len(give) > len(get):
                best_give = max((values.get(str(p.espn_id), {}).get("redraft_value", 0) or 0) for p in give)
                consol = 0.5 if rv >= best_give else -0.75
                if rv >= best_give and "consolidates value for them" not in why: why.append("consolidates value for them")
            rival_cands.append({
                "rival_team_id": rid, "rival": meta.get("name"), "give": [p.name for p in give], "get": [p.name for p in get],
                "my_delta_ppw": round(d_me, 2), "their_delta_ppw": round(d_them, 2),
                "market_give": gv, "market_get": rv, "why": why,
                "score": round(d_them + 0.5 * min(d_me, 3) + consol, 2),
            })
        rival_cands.sort(key=lambda c: -c["score"])
        seen_get, kept = set(), []
        for c in rival_cands:
            k = tuple(sorted(c["get"]))
            if k in seen_get:
                continue
            seen_get.add(k); kept.append(c)
            if len(kept) >= max_per_rival:
                break
        cands += kept
    cands.sort(key=lambda c: -c["score"])
    return cands[:top]


def evaluate(my_id: int, rival_id: int, give: list[PlayerProj], get: list[PlayerProj], rosters: dict[int, list[PlayerProj]],
             slots: dict[str, int], repl: dict[str, float], values: dict[str, dict]) -> dict:
    """
    Score an offer someone sent me: `give` leaves my roster, `get` joins it. Any size, K/DST allowed.

    Verdict is lineup-delta first (same both-sides math as scan), with FantasyCalc redraft value as a lowball check:
    accept when it clearly helps my starting lineup and the market side isn't a fleece; decline when it hurts or the
    market gap is large; everything else is a counter (close enough that the right tweak makes it a yes).
    """
    mine, theirs = rosters.get(my_id, []), rosters.get(rival_id, [])
    my_mu0, _ = lineup_strength(mine, slots)
    their_mu0, _ = lineup_strength(theirs, slots)
    new_mine = _swap(mine, {p.espn_id for p in give}, get)
    new_theirs = _swap(theirs, {p.espn_id for p in get}, give)
    my_mu1, _ = lineup_strength(new_mine, slots)
    their_mu1, _ = lineup_strength(new_theirs, slots)
    d_me, d_them = my_mu1 - my_mu0, their_mu1 - their_mu0
    gv = sum(values.get(str(p.espn_id), {}).get("redraft_value", 0) or 0 for p in give)
    rv = sum(values.get(str(p.espn_id), {}).get("redraft_value", 0) or 0 for p in get)
    market_ratio = (rv / gv) if gv and rv else None

    my_needs, their_needs = needs(mine, slots, repl), needs(theirs, slots, repl)
    why = []
    for p in get:
        if my_needs.get(p.pos, {}).get("hole"): why.append(f"fills my {p.pos} hole")
    for p in give:
        if their_needs.get(p.pos, {}).get("hole"): why.append(f"fills their {p.pos} hole")
    new_needs = needs(new_mine, slots, repl)
    for pos, n in new_needs.items():
        if n["hole"] and not my_needs.get(pos, {}).get("hole"): why.append(f"opens a {pos} hole for me")
    if len(give) > len(get):
        why.append("2-for-1: I consolidate, they get depth")
    elif len(get) > len(give):
        why.append("1-for-2: I take on depth and need a roster spot")
    if market_ratio is not None:
        if market_ratio < 0.8: why.append(f"market says I give more ({rv} vs {gv})")
        elif market_ratio > 1.2: why.append(f"market says I get more ({rv} vs {gv})")
    why = list(dict.fromkeys(why))

    if d_me <= -0.5 or (market_ratio is not None and market_ratio < 0.65):
        verdict = "decline"
    elif d_me >= 0.75 and (market_ratio is None or market_ratio >= 0.8):
        verdict = "accept"
    else:
        verdict = "counter"
    return {
        "give": [p.name for p in give], "get": [p.name for p in get],
        "my_delta_ppw": round(d_me, 2), "their_delta_ppw": round(d_them, 2),
        "market_give": gv, "market_get": rv, "why": why, "verdict": verdict,
    }
