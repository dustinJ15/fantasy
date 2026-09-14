"""Build the versioned DecisionPacket: shared NFL context + one analysis block per league."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime

from .cache import cached_json, HOUR
from .config import LeagueRef, PACKET_DIR, env, leagues
from .ids import Crosswalk
from .model import usage as usage_mod
from .model.lineup import compare, optimize
from .model.projections import PlayerProj, blend
from .model.sim import simulate
from .model.trades import lineup_strength, needs, scan
from .model.clock import apply_clock, week_state
from .model.vbd import replacement_levels, own_starter_value
from .model.waivers import handcuffs, rank_free_agents
from .sources import espn, fantasycalc, sleeper, vegas, weather

PACKET_VERSION = 3
AMBIGUOUS = {"QUESTIONABLE", "DOUBTFUL", "PROBABLE"}


def league_snapshot(ref: LeagueRef, force: bool = False) -> dict:
    def fetch():
        lg = espn.connect(ref)
        week = lg.current_week
        return espn.snapshot(ref, lg, week)
    return cached_json(f"espn_{ref.name}", HOUR / 4, fetch, force)


def _projs(snap: dict, xw: Crosswalk, fp_index: dict, inj: dict, weeks_remaining: int, overrides: dict | None,
           sl_proj: dict | None = None, lines: dict | None = None) -> tuple[list[PlayerProj], list[PlayerProj]]:
    ppr = snap["settings"].get("ppr", 1.0)
    key = "pts_ppr" if ppr >= 0.75 else ("pts_half_ppr" if ppr > 0 else "pts_std")
    sl_proj, lines = sl_proj or {}, lines or {}

    def mk(rows):
        out = []
        for r in rows:
            fp = xw.fp_row(fp_index, r["espn_id"], r["name"], r["pos"])
            if r["pos"] == "D/ST":
                sp = sl_proj.get(f"DEF:{r['team']}")
            else:
                sid = xw.sleeper_id(r["espn_id"], r["name"], r["pos"])
                sp = sl_proj.get(sid) if sid else None
            spts = float(sp[key]) if sp and sp.get(key) is not None else None
            ln = lines.get(r["team"]) or {}
            out.append(blend(r, fp, inj.get(str(r["espn_id"])), weeks_remaining, overrides,
                             sleeper_pts=spts, implied_total=ln.get("implied")))
        return out
    return mk(snap["roster"]), mk(snap["free_agents"])


def analyze_league(snap: dict, xw: Crosswalk, fp_index: dict, inj: dict, trending: dict, usage_sig: dict,
                   overrides: dict | None = None, sims: int = 3000, sl_proj: dict | None = None, lines: dict | None = None,
                   now=None) -> dict:
    s = snap["settings"]
    week = snap["week"]
    slots = s["lineup_slots"]
    total_weeks = len(s["matchup_periods"])
    weeks_remaining = max(total_weeks - week + 1, 1)
    my_id = snap["my_team_id"]
    rostered, fas = _projs(snap, xw, fp_index, inj, weeks_remaining, overrides, sl_proj, lines)
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
    my_bench = my_lineup_ros.bench
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
    trades = scan(my_id, by_team, slots, repl, team_meta, values) if my_id else []
    # attach title-odds delta for the top few (re-sim is expensive; do 3)
    for c in trades[:3]:
        rid = c["rival_team_id"]
        give = {p.espn_id for p in mine if p.name in c["give"]}
        get = [p for p in by_team[rid] if p.name in c["get"]]
        new_mine = [p for p in mine if p.espn_id not in give] + get
        new_theirs = [p for p in by_team[rid] if p.name not in c["get"]] + [p for p in mine if p.espn_id in give]
        st2 = dict(strength); st2[my_id] = lineup_strength(new_mine, slots); st2[rid] = lineup_strength(new_theirs, slots)
        o2 = simulate(ids, records, st2, remaining, s["playoff_team_count"], n_rounds, n=1500, seed=11)
        c["my_title_delta"] = round(o2[my_id]["title_pct"] - odds[my_id]["title_pct"], 1)
        c["their_title_delta"] = round(o2[rid]["title_pct"] - odds[rid]["title_pct"], 1)

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
        "settings": {k: s[k] for k in ("team_count", "lineup_slots", "faab", "faab_budget", "playoff_team_count", "playoff_weeks", "ppr")},
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
        "waivers": waivers, "handcuffs": cuffs, "trades": trades,
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
    lines = vegas.implied_totals()
    try:
        sl_proj = sleeper.projections(e.season, sleeper.state().get("week", 1))
    except Exception:
        sl_proj = {}

    league_blocks, watch, exposure = [], [], defaultdict(list)
    for ref in leagues(only):
        snap = league_snapshot(ref, force)
        blk = analyze_league(snap, xw, fp_index, inj, trending, usage_sig, overrides, sims, sl_proj, lines)
        for p in blk["roster"]:
            exposure[p["name"]].append(ref.name)
            st = (p["sources"].get("espn_status") or p["sources"].get("sleeper_status") or "").upper()
            if st in AMBIGUOUS:
                watch.append({"name": p["name"], "pos": p["pos"], "team": p["team"], "league": ref.name, "status": st,
                              "notes": p["sources"].get("sleeper_notes"), "espn_id": p["espn_id"], "p_zero": p["p_zero"],
                              "override_note": p["sources"].get("override_note"), "locked": p.get("locked", False)})
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
            "exposure": {k: v for k, v in exposure.items() if len(v) > 1},
            "trending_adds": [{"espn_id": k, "count": v} for k, v in sorted(trending.items(), key=lambda kv: -kv[1])[:15]],
            "usage_error": usage_err, "unmatched_ids": xw.unmatched[:50],
        },
        "leagues": league_blocks,
    }
    PACKET_DIR.mkdir(parents=True, exist_ok=True)
    out = PACKET_DIR / f"{date.today().isoformat()}.json"
    out.write_text(json.dumps(packet, indent=1, default=str))
    packet["_path"] = str(out)
    return packet
