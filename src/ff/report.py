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


def action_card(packet: dict) -> str:
    """The short version: what to do today, per league. Meant to be read on a phone."""
    L = [f"# FF briefing — {packet['generated'][:10]}", ""]
    sh = packet["shared"]
    for lg in packet["leagues"]:
        me = lg["odds"].get(str(lg["my_team_id"])) or {}
        opp = lg["opponent"]; lw = lg["lineup_win"]
        L.append(f"## {lg['league_name']} — Week {lg['week']} · {lg['my_record']} · playoffs {me.get('playoff_pct', '?')}% · title {me.get('title_pct', '?')}%")
        pw = f" · P(win) {lw['p_win']:.0%}" if lw.get("p_win") is not None else ""
        L.append(f"vs **{opp.get('name')}** ({lw['mu']:.0f} vs {opp.get('mu') or 0:.0f} proj){pw}")
        ch = _lineup_changes(lg)
        L.append("**Lineup:** " + ("; ".join(ch) if ch else "no changes needed"))
        starters = {n for names in lw["slots"].values() for n in names}
        flagged = [p for p in lg["roster"] if p["name"] in starters and (p["p_zero"] >= 0.15 or p["bye"])]
        if flagged:
            L.append("**Starter risk:** " + "; ".join(f"{p['name']} (p_sit {p['p_zero']:.0%}{', ' + p['sources']['sleeper_notes'] if p['sources'].get('sleeper_notes') else ''})" for p in flagged))
        ws = [w for w in lg["waivers"] if not w["streamer"]][:2]
        if ws:
            L.append("**Pickups:** " + "; ".join(f"{w['name']} ({w['pos']}, {w['mu_ros']:.1f}/g" + (f", +{w['delta_over_starter']:.1f} at {w['slot']}" if w['delta_over_starter'] > 0 else ", depth") + ")" for w in ws))
        st = [w for w in lg["waivers"] if w["streamer"]][:1]
        if st:
            L.append(f"**Stream:** {st[0]['name']} ({st[0]['pos']}, +{st[0]['delta_over_starter']:.1f} this week)")
        if lg["trades"]:
            t = lg["trades"][0]
            td = f", title odds {t['my_title_delta']:+.1f} me / {t['their_title_delta']:+.1f} them" if "my_title_delta" in t else ""
            L.append(f"**Trade to pitch:** give {', '.join(t['give'])} for {', '.join(t['get'])} ({t['rival']}; {t['my_delta_ppw']:+.1f} ppw me, {t['their_delta_ppw']:+.1f} them{td})")
        L.append("")
    if sh["injury_watchlist"]:
        L.append("**Watch:** " + "; ".join(f"{w['name']} {w['status'].title()} ({w['league']})" for w in sh["injury_watchlist"]))
    if sh["exposure"]:
        L.append("**Exposure:** " + ", ".join(f"{k} ({len(v)}x)" for k, v in sh["exposure"].items()))
    # two trailing spaces = markdown hard line break, so the card renders line-by-line in HTML too
    return "\n".join(line if (not line or line.startswith("#")) else line + "  " for line in L)


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
        for slot, names in lw["slots"].items():
            L.append(f"- {slot}: {', '.join(names)}")
        if lg["lineup_diff"]:
            L.append(f"Differs from the pure-points lineup ({le['mu']}): " + "; ".join(f"{d['name']} in {d['in']} lineup ({d['ev']} ± {d['sd']})" for d in lg["lineup_diff"]))
        L.append(f"Bench: {', '.join(lw['bench'])}")

        L.append("\n## My roster")
        L.append("| player | pos | slot | wk μ | sd | p0 | ROS/g | flags | usage | mkt |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for p in lg["roster"]:
            u = p.get("usage") or {}
            uf = "; ".join(u.get("flags", [])) if u else ""
            m = p.get("market") or {}
            L.append(f"| {p['name']} | {p['pos']} | {p['slot']} | {p['mu']} | {p['sd']} | {p['p_zero']} | {p['mu_ros']} | {_flags(p)} | {uf} | {m.get('redraft_value','')} |")

        L.append("\n## Waivers")
        if lg["waivers"]:
            faab = lg.get("faab_remaining") is not None
            L.append("| target | pos | wk μ | ROS/g | vs my starter | " + ("bid | " if faab else "") + "why |")
            L.append("|---|---|---|---|---|" + ("---|" if faab else "") + "---|")
            for w in lg["waivers"]:
                d = (f"+{w['delta_over_starter']:.1f} at {w['slot']}" if w['delta_over_starter'] > 0 else f"depth ({w['delta_over_starter']:.1f} vs {w['slot']})") if w['slot'] else "depth"
                L.append(f"| {w['name']} | {w['pos']} | {w['mu_week']} | {w['mu_ros']} | {d} | " + (f"${w['bid']} | " if faab else "") + f"{'; '.join(w['why'][:4])} |")
        else:
            L.append("Nothing worth a claim.")
        if lg["handcuffs"]:
            L.append("Handcuffs: " + "; ".join(f"{h['handcuff']} for {h['starter']} ({'FA' if h['owner_team_id'] is None else 'owned'})" for h in lg["handcuffs"]))

        L.append("\n## Trade candidates")
        if lg["trades"]:
            for t in lg["trades"][:6]:
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
