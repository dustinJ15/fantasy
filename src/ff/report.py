"""Render a DecisionPacket to markdown. Works with no LLM."""
from __future__ import annotations


def _flags(p: dict) -> str:
    f = [x for x in p.get("flags", []) if not x.startswith("fp:")]
    g = p["sources"].get("grade")
    if g:
        f.append(g)
    return ", ".join(f)


NON_STARTER = {"BE", "IR", "", "FA"}


def _lineup_changes(lg: dict) -> list[str]:
    """Players to move, comparing the current ESPN slots with the recommended lineup."""
    cur = {p["name"]: p["slot"] for p in lg["roster"]}
    rec = {n: s for s, names in lg["lineup_win"]["slots"].items() for n in names if not n.startswith("(")}
    ins = [f"{n} → {s}" for n, s in rec.items() if cur.get(n) in NON_STARTER]
    outs = [n for n, s in cur.items() if s not in NON_STARTER and n not in rec]
    empties = [s for s, names in lg["lineup_win"]["slots"].items() if any(n.startswith("(") for n in names)]
    out = []
    if ins: out.append("Start: " + ", ".join(ins))
    if outs: out.append("Bench: " + ", ".join(outs))
    if empties: out.append("EMPTY SLOT: " + ", ".join(empties) + " (no healthy player; pick one up)")
    return out


def _drop_candidate(lg: dict) -> str | None:
    """Weakest bench player by ROS value who isn't a K/DST starter or injured stash worth keeping."""
    starters = {n for names in lg["lineup_win"]["slots"].values() for n in names}
    bench = [p for p in lg["roster"] if p["name"] not in starters and p["pos"] not in ("K", "D/ST")]
    if not bench:
        return None
    return min(bench, key=lambda p: p["mu_ros"])["name"]


def action_card(packet: dict) -> str:
    """Checklist-first: literal things to do today per league, then a one-line why."""
    L = [f"# FF briefing — {packet['generated'][:10]}", ""]
    sh = packet["shared"]
    for lg in packet["leagues"]:
        me = lg["odds"].get(str(lg["my_team_id"])) or {}
        opp = lg["opponent"]; lw = lg["lineup_win"]
        pw = f"{lw['p_win']:.0%}" if lw.get("p_win") is not None else "?"
        L.append(f"## {lg['league_name']}")
        L.append(f"_{lg['my_record']} · vs {opp.get('name')} · win {pw} · playoffs {me.get('playoff_pct', '?')}% · title {me.get('title_pct', '?')}%_")
        todo = []
        # Waiver: anyone who should START this week, or a clear ROS upgrade
        starts = [w for w in lg["waivers"] if not w["streamer"] and w.get("delta_week", 0) >= 1.5]
        ups = [w for w in lg["waivers"] if not w["streamer"] and w["delta_over_starter"] >= 1.0 and w not in starts]
        drop = _drop_candidate(lg)
        for w in starts[:1]:
            todo.append(f"**Waiver:** add {w['name']} ({w['pos']}) and start him at {w['week_slot']} (+{w['delta_week']:.0f} pts this week)" + (f"; drop {drop}" if drop else ""))
        for w in ups[:1]:
            todo.append(f"**Waiver (upgrade):** add {w['name']} ({w['pos']}), +{w['delta_over_starter']:.1f}/wk over your {w['slot']}" + (f"; drop {drop}" if drop else ""))
        st = [w for w in lg["waivers"] if w["streamer"] and w["delta_over_starter"] >= 1.5][:1]
        for w in st:
            todo.append(f"**Stream:** swap in {w['name']} at {w['pos']} (+{w['delta_over_starter']:.1f} this week)")
        ch = _lineup_changes(lg)
        if ch:
            todo.append("**Lineup:** " + "; ".join(ch))
        else:
            todo.append("**Lineup:** leave as is")
        if lg["trades"]:
            t = lg["trades"][0]
            tag = "worth sending" if t["their_delta_ppw"] >= -0.3 else "a reach, send only if bored"
            todo.append(f"**Trade ({tag}):** offer {t['rival']} your {', '.join(t['give'])} for {', '.join(t['get'])} (+{t['my_delta_ppw']:.1f} pts/wk for you, {t['their_delta_ppw']:+.1f} for them)")
        for x in todo:
            L.append(f"- {x}")
        starters = {n for names in lw["slots"].values() for n in names}
        flagged = [p for p in lg["roster"] if p["name"] in starters and (p["p_zero"] >= 0.15 or p["bye"])]
        why = []
        if flagged:
            why.append("; ".join(f"{p['name']} {p['p_zero']:.0%} to sit" for p in flagged))
        if lw.get("p_win") is not None:
            why.append("underdog, favor upside" if lw["p_win"] < 0.42 else ("favorite, play it safe" if lw["p_win"] > 0.58 else "coin flip"))
        if why:
            L.append("_Why: " + " · ".join(why) + "_")
        L.append("")
    if sh["injury_watchlist"]:
        L.append("**Watch:** " + "; ".join(f"{w['name']} {w['status'].title()} ({w['league']})" for w in sh["injury_watchlist"]))
    if sh["exposure"]:
        L.append("**Exposure:** " + ", ".join(f"{k} ({len(v)}x)" for k, v in sh["exposure"].items()))
    return "\n".join(line if (not line or line.startswith("#") or line.startswith("- ")) else line + "  " for line in L)


def render(packet: dict, detail: bool = True) -> str:
    """Action card first; full tables after a divider (omit with detail=False)."""
    head = action_card(packet)
    if not detail:
        return head
    return head + "\n\n---\n\n_Full detail below._\n\n" + render_detail(packet)


def render_detail(packet: dict) -> str:
    L = []
    sh = packet["shared"]
    L.append(f"# Detail — {packet['generated'][:10]}\n")
    if sh["injury_watchlist"]:
        L.append("## Injury watchlist (ambiguous designations on my rosters)")
        for w in sh["injury_watchlist"]:
            L.append(f"- **{w['name']}** ({w['pos']}, {w['team']}) — {w['status']} in *{w['league']}*; p_zero={w['p_zero']}" + (f"; {w['notes']}" if w.get("notes") else ""))
        L.append("")
    if sh["exposure"]:
        L.append("## Exposure (held in 2+ leagues)")
        L.append(", ".join(f"{k} ({', '.join(v)})" for k, v in sh["exposure"].items()))
        L.append("")
    if sh.get("usage_error"):
        L.append(f"> usage metrics unavailable: {sh['usage_error']}\n")

    for lg in packet["leagues"]:
        L.append(f"\n---\n# {lg['league_name']} (`{lg['name']}`) — Week {lg['week']}")
        acq = f"FAAB left ${lg['faab_remaining']}" if lg.get("faab_remaining") is not None else f"waiver priority #{lg.get('waiver_rank')}"
        L.append(f"Record {lg['my_record']} · {acq} · weeks remaining {lg['weeks_remaining']}")
        me = lg["odds"].get(str(lg["my_team_id"])) or {}
        if me:
            L.append(f"Playoff odds **{me['playoff_pct']}%** · title odds **{me['title_pct']}%** · expected wins {me['exp_wins']}")
        opp = lg["opponent"]
        if opp.get("name"):
            L.append(f"\n## Matchup vs {opp['name']} (their proj {opp['mu']} ± {opp['sd']})")
        lw, le = lg["lineup_win"], lg["lineup_ev"]
        L.append(f"Recommended lineup (max P(win){' = ' + str(lw['p_win']) if lw.get('p_win') is not None else ''}), proj {lw['mu']} ± {lw['sd']}; current ESPN lineup proj {lg['current_lineup_mu']}")
        L.append("")
        for slot, names in lw["slots"].items():
            L.append(f"- {slot}: {', '.join(names)}")
        if lg["lineup_diff"]:
            L.append(f"Differs from the pure-points lineup ({le['mu']}): " + "; ".join(f"{d['name']} in {d['in']} lineup ({d['ev']} ± {d['sd']})" for d in lg["lineup_diff"]))
        L.append("")
        L.append(f"Bench: {', '.join(lw['bench'])}")

        L.append("\n## My roster (this week μ · ROS/g · flags)")
        L.append("| player | pos | wk μ | ROS/g | flags |")
        L.append("|---|---|---|---|---|")
        for p in lg["roster"]:
            L.append(f"| {p['name']} | {p['pos']} | {p['mu']} | {p['mu_ros']} | {_flags(p)} |")

        L.append("\n## Waivers")
        if lg["waivers"]:
            faab = lg.get("faab_remaining") is not None
            L.append("| target | pos | wk μ | ROS/g | vs my starter | " + ("bid | " if faab else "") + "why |")
            L.append("|---|---|---|---|---|" + ("---|" if faab else "") + "---|")
            for w in lg["waivers"][:6]:
                d = (f"+{w['delta_over_starter']:.1f} at {w['slot']}" if w['delta_over_starter'] > 0 else f"depth ({w['delta_over_starter']:.1f} vs {w['slot']})") if w['slot'] else "depth"
                L.append(f"| {w['name']} | {w['pos']} | {w['mu_week']} | {w['mu_ros']} | {d} | " + (f"${w['bid']} | " if faab else "") + f"{'; '.join(w['why'][:4])} |")
        else:
            L.append("Nothing worth a claim.")
        if lg["handcuffs"]:
            L.append("Handcuffs: " + "; ".join(f"{h['handcuff']} for {h['starter']} ({'FA' if h['owner_team_id'] is None else 'owned'})" for h in lg["handcuffs"]))

        L.append("\n## Trade candidates")
        if lg["trades"]:
            for t in lg["trades"][:3]:
                td = f" · title odds me {t.get('my_title_delta', '?'):+} / them {t.get('their_title_delta', '?'):+}" if "my_title_delta" in t else ""
                L.append(f"- **Give {', '.join(t['give'])} → get {', '.join(t['get'])}** from {t['rival']}: me {t['my_delta_ppw']:+.1f} ppw, them {t['their_delta_ppw']:+.1f} ppw{td}. {'; '.join(t['why'])}")
        else:
            L.append("No mutually beneficial package found this week.")

        L.append("\n## League odds")
        L.append("| team | record | playoff % | title % | exp wins |")
        L.append("|---|---|---|---|---|")
        for tid, o in sorted(lg["odds"].items(), key=lambda kv: -kv[1]["title_pct"]):
            L.append(f"| {'**' if o['is_me'] else ''}{o['name']}{'**' if o['is_me'] else ''} | {o['record']} | {o['playoff_pct']} | {o['title_pct']} | {o['exp_wins']} |")
        L.append("\nRival needs: " + "; ".join(f"{lg['odds'].get(tid, {}).get('name', tid)}: " + ", ".join(f"{pos} {v}" for pos, v in n.items() if v) for tid, n in lg["rival_needs"].items()))
    return "\n".join(L)
