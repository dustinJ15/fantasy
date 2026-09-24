"""Build the versioned DecisionPacket: shared NFL context + one analysis block per league."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime

from .cache import HOUR, cached_json
from .config import PACKET_DIR, LeagueRef, env, leagues
from .ids import Crosswalk
from .model import usage as usage_mod
from .model.clock import apply_clock, week_state
from .model.injuries import decide as decide_injuries, fill_spot
from .model.lineup import compare, optimize
from .model.projections import PlayerProj, blend
from .model.sim import simulate
from .model.trades import drop_already_offered, evaluate, lineup_strength, needs, scan
from .model.vbd import replacement_levels
from .model.waivers import handcuffs, rank_free_agents
from .rulings import drop_recently_skipped, load_pushes, load_skips, mark_pushed
from .sources import espn, fantasycalc, sleeper, vegas, weather

PACKET_VERSION = 6
AMBIGUOUS = {"QUESTIONABLE", "DOUBTFUL", "PROBABLE", "DAY_TO_DAY"}
# ESPN and Sleeper spell one team differently; Sleeper's DEF projections are keyed by its own abbreviation.
SLEEPER_TEAM = {"WSH": "WAS"}


def league_snapshot(ref: LeagueRef, force: bool = False) -> dict:
    def fetch():
        lg = espn.connect(ref)
        week = lg.current_week
        return espn.snapshot(ref, lg, week)
    return cached_json(f"espn_{ref.name}", HOUR / 4, fetch, force)


def _projs(snap: dict, xw: Crosswalk, fp_index: dict, inj: dict, weeks_remaining: int, overrides: dict | None,
           sl_proj: dict | None = None, lines: dict | None = None, week: int | None = None,
           weekday: int | None = None) -> tuple[list[PlayerProj], list[PlayerProj]]:
    ppr = snap["settings"].get("ppr", 1.0)
    key = "pts_ppr" if ppr >= 0.75 else ("pts_half_ppr" if ppr > 0 else "pts_std")
    sl_proj, lines = sl_proj or {}, lines or {}

    def mk(rows):
        out = []
        for r in rows:
            fp = xw.fp_row(fp_index, r["espn_id"], r["name"], r["pos"])
            if r["pos"] == "D/ST":
                sp = sl_proj.get(f"DEF:{SLEEPER_TEAM.get(r['team'], r['team'])}")
            else:
                sid = xw.sleeper_id(r["espn_id"], r["name"], r["pos"])
                sp = sl_proj.get(sid) if sid else None
            spts = float(sp[key]) if sp and sp.get(key) is not None else None
            ln = lines.get(r["team"]) or {}
            out.append(blend(r, fp, inj.get(str(r["espn_id"])), weeks_remaining, overrides,
                             sleeper_pts=spts, implied_total=ln.get("implied"), week=week, weekday=weekday))
        return out
    return mk(snap["roster"]), mk(snap["free_agents"])


def injured_entry(p: dict, league: str) -> dict:
    """One row of `shared.injured`, the research list for return timelines: Claude's `weeks_out` override lands here."""
    src = p["sources"]
    return {"name": p["name"], "pos": p["pos"], "team": p["team"], "league": league, "espn_id": p["espn_id"],
            "espn_status": src.get("espn_status"), "sleeper_status": src.get("sleeper_status"),
            "sleeper_roster_status": src.get("sleeper_roster_status"), "body_part": src.get("body_part"), "notes": src.get("sleeper_notes"),
            "weeks_out": p["weeks_out"], "weeks_out_source": src.get("weeks_out_source"), "return_week": p.get("return_week"),
            "mu_ros_active": p.get("mu_ros_active"),
            "slot": p.get("slot"), "override_note": src.get("override_note")}


def _ms_iso(ms) -> str | None:
    return datetime.fromtimestamp(ms / 1000).isoformat(timespec="minutes") if ms else None


def _hours_left(ms, now=None) -> float | None:
    if not ms:
        return None
    if now is None or now.tzinfo is None:
        now = datetime.now(UTC)
    return round((datetime.fromtimestamp(ms / 1000, tz=UTC) - now).total_seconds() / 3600, 1)


def analyze_league(snap: dict, xw: Crosswalk, fp_index: dict, inj: dict, trending: dict, usage_sig: dict,
                   overrides: dict | None = None, sims: int = 3000, sl_proj: dict | None = None, lines: dict | None = None,
                   now=None, skips: dict | None = None, pushes: dict | None = None) -> dict:
    s = snap["settings"]
    week = snap["week"]
    slots = s["lineup_slots"]
    total_weeks = len(s["matchup_periods"])
    weeks_remaining = max(total_weeks - week + 1, 1)
    my_id = snap["my_team_id"]
    # `now` is only ever passed by the real build (and by tests that want a specific day); without it the
    # projections use the Friday sit-risk numbers, so fixtures and the demo do not change with the calendar.
    now_dt = now if (now is not None and getattr(now, "tzinfo", None) is not None) else datetime.now(UTC)
    rostered, fas = _projs(snap, xw, fp_index, inj, weeks_remaining, overrides, sl_proj, lines, week=week,
                           weekday=now_dt.weekday() if now is not None else None)
    apply_clock(rostered, snap["roster"], lines or {}, now)
    apply_clock(fas, snap["free_agents"], lines or {}, now, free_agents=True)
    pool = rostered + fas
    repl = replacement_levels(pool, slots, s["team_count"])
    by_team: dict[int, list[PlayerProj]] = defaultdict(list)
    for p in rostered:
        by_team[p.fantasy_team_id].append(p)
    teams = {t["team_id"]: t for t in snap["teams"]}

    # matchup + opponent
    opp_id = None
    for m in snap["matchups"]:
        if my_id in (m["home"], m["away"]):
            opp_id = m["away"] if m["home"] == my_id else m["home"]
    strength = {tid: lineup_strength(ps, slots) for tid, ps in by_team.items()}
    opp_mu, opp_var = strength.get(opp_id, (None, None))
    if opp_id:
        opp_week = optimize(by_team[opp_id], slots, objective="ev")
        opp_mu, opp_var = opp_week.mu, opp_week.var

    mine = by_team.get(my_id, [])
    ev_lu = optimize(mine, slots, objective="ev")
    win_lu = optimize(mine, slots, opp_mu=opp_mu, opp_var=opp_var) if opp_mu is not None else ev_lu
    current = {p.slot: [] for p in mine}
    for p in mine:
        current.setdefault(p.slot, []).append(p)
    current_starters = [p for p in mine if p.slot not in espn.NON_STARTER]
    cur_mu = sum(p.ev for p in current_starters)
    wstate = week_state(mine, by_team.get(opp_id, []), espn.NON_STARTER)
    for m in snap["matchups"]:
        if my_id in (m["home"], m["away"]) and (m.get("home_score") or m.get("away_score")):
            wstate["espn_my_score"] = m["home_score"] if m["home"] == my_id else m["away_score"]
            wstate["espn_opp_score"] = m["away_score"] if m["home"] == my_id else m["home_score"]

    # season sim
    ids = list(by_team.keys())
    records = {t: (teams[t]["wins"], teams[t]["losses"], teams[t]["points_for"]) for t in ids}
    remaining = []
    for w in range(week, s["reg_season_weeks"] + 1):
        pairs, seen = [], set()
        for t in ids:
            sched = teams[t]["schedule"]
            if w - 1 < len(sched):
                o = sched[w - 1]
                key = tuple(sorted((t, o))) if o else None
                if key and key not in seen:
                    seen.add(key); pairs.append((t, o))
        remaining.append(pairs)
    n_rounds = max(len(s["playoff_weeks"]), 1)
    odds = simulate(ids, records, strength, remaining, s["playoff_team_count"], n_rounds, n=sims)

    # waivers
    my_lineup_ros = optimize([p.ros() for p in mine], slots, objective="ev")
    my_lineup = my_lineup_ros.assignment
    # Dropping an IR occupant frees an IR slot, not a bench spot, so he is not the bench a pickup competes with.
    my_bench = [p for p in my_lineup_ros.bench if p.slot != "IR"]
    if s["faab"]:
        budget = s["faab_budget"] - teams[my_id]["faab_spent"] if my_id in teams else 0
        rival_max = max((s["faab_budget"] - t["faab_spent"] for tid, t in teams.items() if tid != my_id), default=None)
    else:
        budget, rival_max = 0, None
    waivers = rank_free_agents(fas, my_lineup, my_bench, repl, weeks_remaining, budget, trending, rival_max,
                               week_lineup=win_lu.assignment)
    my_rbs = [p for p in my_lineup.get("RB", [])]
    cuffs = handcuffs(my_rbs, pool)

    # trades
    values = fantasycalc.by_espn_id(num_teams=s["team_count"], ppr=s["ppr"])
    team_meta = {tid: {"name": t["name"], "wins": t["wins"], "losses": t["losses"]} for tid, t in teams.items()}
    by_id = {p.espn_id: p for ps in by_team.values() for p in ps}
    # The trade deadline closes the scan: the offers Dustin could still send are none.
    deadline_ms = int(s.get("trade_deadline_ms") or 0)
    trades_closed = bool(deadline_ms) and now_dt.timestamp() * 1000 > deadline_ms
    limits = s.get("position_limits") or {}
    trades = scan(my_id, by_team, slots, repl, team_meta, values, limits=limits) if (my_id and not trades_closed) else []
    trades = drop_already_offered(trades, snap.get("pending_trades"), by_id)
    trades = drop_recently_skipped(trades, skips or {}, snap["ref"]["name"], now_dt.date())
    trades = mark_pushed(trades, pushes or {}, snap["ref"]["name"], now_dt.date())
    # attach title-odds delta for the top few (re-sim is expensive; do 3)
    for c in trades[:3]:
        rid = c["rival_team_id"]
        give = {p.espn_id for p in mine if p.name in c["give"]}
        get = [p for p in by_team[rid] if p.name in c["get"]]
        cut = {d["name"] for d in c.get("drops") or []}
        new_mine = [p for p in mine if p.espn_id not in give and p.name not in cut] + get
        new_theirs = [p for p in by_team[rid] if p.name not in c["get"]] + [p for p in mine if p.espn_id in give]
        st2 = dict(strength); st2[my_id] = lineup_strength(new_mine, slots); st2[rid] = lineup_strength(new_theirs, slots)
        o2 = simulate(ids, records, st2, remaining, s["playoff_team_count"], n_rounds, n=1500, seed=11)
        c["my_title_delta"] = round(o2[my_id]["title_pct"] - odds[my_id]["title_pct"], 1)
        c["their_title_delta"] = round(o2[rid]["title_pct"] - odds[rid]["title_pct"], 1)

    # hurt players: IR / trade / drop / hold, from the waiver and trade results above
    me_odds = odds.get(my_id) or {}
    injuries = decide_injuries(mine, slots, week, weeks_remaining, s["reg_season_weeks"], me_odds.get("playoff_pct"),
                               s.get("ir_slots", 0), waivers, trades, values,
                               {p.espn_id for ps in win_lu.assignment.values() for p in ps}, repl, cuffs) if my_id else []

    # bench spots already open (a drop made, nobody added): name who fills each one, after the hurt-player rows
    roster_max = sum(slots.values()) + int(s.get("bench_slots") or 0)
    open_spots = max(roster_max - len([p for p in mine if p.slot != "IR"]), 0) if my_id and s.get("bench_slots") else 0
    used = {r["add"]["name"] for r in injuries if r.get("add")}
    open_adds = []
    for _ in range(open_spots):
        a = fill_spot(None, waivers, cuffs, used)
        if not a:
            break
        open_adds.append(a); used.add(a["name"])

    # offers other managers sent me (and mine still open), from ESPN's pending transactions
    incoming, outgoing = [], []
    for tx in snap.get("pending_trades") or []:
        rid = tx.get("rival_team_id")
        give = [by_id[i] for i in tx["give"] if i in by_id]
        get = [by_id[i] for i in tx["get"] if i in by_id]
        unmatched = [i for i in tx["give"] + tx["get"] if i not in by_id]
        base = {"id": tx["id"], "rival_team_id": rid, "rival": teams.get(rid, {}).get("name"),
                "proposed_iso": _ms_iso(tx.get("proposed_ts")), "expires_iso": _ms_iso(tx.get("expires_ts")),
                "hours_left": _hours_left(tx.get("expires_ts"), now), "proposed_ts": tx.get("proposed_ts"),
                "unmatched_ids": unmatched}
        if tx.get("direction") != "incoming" or rid is None:
            outgoing.append({**base, "give": [p.name for p in give], "get": [p.name for p in get]})
            continue
        ev = evaluate(my_id, rid, give, get, by_team, slots, repl, values, limits=limits)
        cut = {d["name"] for d in ev.get("drops") or []}
        new_mine = [p for p in mine if p.espn_id not in {g.espn_id for g in give} and p.name not in cut] + get
        new_theirs = [p for p in by_team.get(rid, []) if p.espn_id not in {g.espn_id for g in get}] + give
        st2 = dict(strength); st2[my_id] = lineup_strength(new_mine, slots); st2[rid] = lineup_strength(new_theirs, slots)
        o2 = simulate(ids, records, st2, remaining, s["playoff_team_count"], n_rounds, n=min(sims, 1500), seed=11)
        ev["my_title_delta"] = round(o2[my_id]["title_pct"] - odds[my_id]["title_pct"], 1)
        ev["their_title_delta"] = round(o2[rid]["title_pct"] - odds[rid]["title_pct"], 1)
        incoming.append({**base, **ev})
    incoming.sort(key=lambda t: t.get("proposed_ts") or 0, reverse=True)

    # usage signals + market values on my roster
    def enrich(p: PlayerProj) -> dict:
        d = p.to_dict()
        x = xw.lookup(p.espn_id, p.name, p.pos) or {}
        g = x.get("gsis_id")
        d["usage"] = usage_sig.get(g) if g else None
        v = values.get(str(p.espn_id))
        d["market"] = {"redraft_value": v["redraft_value"], "rank": v["overall_rank"], "trend_30d": v["trend_30d"]} if v else None
        d["odds_line"] = None
        return d

    rival_needs = {tid: needs(ps, slots, repl) for tid, ps in by_team.items() if tid != my_id}
    return {
        "name": snap["ref"]["name"], "league_name": s["name"], "week": week, "weeks_remaining": weeks_remaining,
        "settings": {k: s.get(k) for k in ("team_count", "lineup_slots", "faab", "faab_budget", "playoff_team_count", "playoff_weeks", "ppr",
                                           "reg_season_weeks", "ir_slots", "bench_slots", "trade_deadline_ms", "position_limits")},
        "trade_deadline_iso": _ms_iso(deadline_ms), "trades_closed": trades_closed,
        "my_team_id": my_id, "my_record": f"{teams[my_id]['wins']}-{teams[my_id]['losses']}" if my_id in teams else None,
        "week_state": wstate,
        "faab_remaining": budget if s["faab"] else None,
        "waiver_rank": teams[my_id]["waiver_rank"] if my_id in teams else None,
        "opponent": {"team_id": opp_id, "name": teams[opp_id]["name"] if opp_id in teams else None, "mu": round(opp_mu, 1) if opp_mu else None,
                     "sd": round(opp_var ** 0.5, 1) if opp_var else None},
        "roster": [enrich(p) for p in sorted(mine, key=lambda p: (-p.ev))],
        "current_lineup_mu": round(cur_mu, 1),
        "lineup_ev": ev_lu.to_dict(), "lineup_win": win_lu.to_dict(), "lineup_diff": compare(ev_lu, win_lu),
        "replacement": repl,
        "waivers": waivers, "handcuffs": cuffs, "trades": trades, "injuries": injuries,
        "open_spots": open_spots, "open_spot_adds": open_adds,
        "incoming_trades": incoming, "outgoing_trades": outgoing,
        "pending_trades_error": snap.get("pending_trades_error"),
        "odds": {str(tid): {**o, "name": teams[tid]["name"], "record": f"{teams[tid]['wins']}-{teams[tid]['losses']}", "is_me": tid == my_id} for tid, o in odds.items()},
        "rival_needs": {str(tid): {pos: ("hole" if v["hole"] else "surplus" if v["surplus"] else "") for pos, v in n.items() if pos not in ("K", "D/ST")} for tid, n in rival_needs.items()},
        "standings": sorted([{"name": t["name"], "record": f"{t['wins']}-{t['losses']}", "pf": round(t["points_for"], 1), "faab_left": (s["faab_budget"] - t["faab_spent"]) if s["faab"] else None, "waiver_rank": t["waiver_rank"], "is_me": tid == my_id}
                             for tid, t in teams.items()], key=lambda x: -x["pf"]),
    }


def build(only: str | None = None, overrides_path: str | None = None, force: bool = False, sims: int = 3000) -> dict:
    e = env()
    overrides = json.load(open(overrides_path)) if overrides_path else None
    xw = Crosswalk()
    fp_index = xw.fp_weekly_index()
    inj = sleeper.injury_table()
    trending = {}
    sl_players = sleeper.players()
    for t in sleeper.trending("add", 24, 100):
        eid = (sl_players.get(t["player_id"]) or {}).get("espn_id")
        if eid:
            trending[str(eid)] = t["count"]
    try:
        summary = usage_mod.season_summary(e.season)
        usage_sig = usage_mod.signals(summary)
    except Exception as exc:  # nflverse may lag early in the week
        usage_sig = {}
        usage_err = str(exc)
    else:
        usage_err = None
    # ESPN's un-parameterised scoreboard stays on last week until Tuesday night (fantasy leagues roll Tuesday morning),
    # so always ask for the league's week; otherwise the clock locks every player as already played.
    lines_by_week: dict[int, dict] = {}
    try:
        sl_proj = sleeper.projections(e.season, sleeper.state().get("week", 1))
    except Exception:
        sl_proj = {}

    skips, pushes = load_skips(), load_pushes()
    league_blocks, watch, injured, exposure = [], [], [], defaultdict(list)
    for ref in leagues(only):
        snap = league_snapshot(ref, force)
        wk = int(snap.get("week") or 0)
        if wk not in lines_by_week:
            lines_by_week[wk] = vegas.implied_totals(wk or None)
        lines = lines_by_week[wk]
        blk = analyze_league(snap, xw, fp_index, inj, trending, usage_sig, overrides, sims, sl_proj, lines,
                             now=datetime.now(UTC), skips=skips, pushes=pushes)
        for p in blk["roster"]:
            exposure[p["name"]].append(ref.name)
            st = (p["sources"].get("espn_status") or p["sources"].get("sleeper_status") or "").upper()
            if st in AMBIGUOUS:
                watch.append({"name": p["name"], "pos": p["pos"], "team": p["team"], "league": ref.name, "status": st,
                              "notes": p["sources"].get("sleeper_notes"), "espn_id": p["espn_id"], "p_zero": p["p_zero"],
                              "override_note": p["sources"].get("override_note"), "locked": p.get("locked", False)})
            if p.get("weeks_out", 0) >= 1 or p.get("slot") == "IR":
                injured.append(injured_entry(p, ref.name))
            ln = lines.get(p["team"])
            if ln:
                p["odds_line"] = {"opp": ln["opp"], "implied": ln["implied"], "spread": ln["spread"], "total": ln["total"], "kickoff": ln["kickoff"]}
                if not ln["indoor"]:
                    p["weather"] = weather.forecast(p["team"] if ln["home"] else ln["opp"], ln["kickoff"])
        league_blocks.append(blk)

    packet = {
        "version": PACKET_VERSION, "generated": datetime.now().isoformat(timespec="seconds"), "season": e.season,
        "shared": {
            "injury_watchlist": watch,
            "injured": injured,
            "exposure": {k: v for k, v in exposure.items() if len(v) > 1},
            "trending_adds": [{"espn_id": k, "count": v} for k, v in sorted(trending.items(), key=lambda kv: -kv[1])[:15]],
            "usage_error": usage_err, "unmatched_ids": xw.unmatched[:50],
            "pending_trades_error": {b["name"]: b["pending_trades_error"] for b in league_blocks if b.get("pending_trades_error")} or None,
            "incoming_trade_count": sum(len(b["incoming_trades"]) for b in league_blocks),
        },
        "leagues": league_blocks,
    }
    PACKET_DIR.mkdir(parents=True, exist_ok=True)
    out = PACKET_DIR / f"{date.today().isoformat()}.json"
    out.write_text(json.dumps(packet, indent=1, default=str))
    packet["_path"] = str(out)
    return packet
