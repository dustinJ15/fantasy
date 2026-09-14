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
    """Explicit moves to get from the current ESPN slots to the recommended lineup, as an ordered chain:
    'X: bench -> FLEX' or 'Y: WR -> FLEX', with slots freed in an order that works in the app."""
    cur = {p["name"]: p["slot"] for p in lg["roster"]}
    rec = {n: s for s, names in lg["lineup_win"]["slots"].items() for n in names if not n.startswith("(")}
    moves = []
    # starters who are dropped entirely
    for n, s in cur.items():
        if s not in NON_STARTER and n not in rec:
            moves.append(f"{n}: {s} → bench")
    # starters changing slot
    for n, s in rec.items():
        if cur.get(n) not in NON_STARTER and cur.get(n) != s:
            moves.append(f"{n}: {cur[n]} → {s}")
    # bench players coming in
    for n, s in rec.items():
        if cur.get(n) in NON_STARTER:
            moves.append(f"{n}: bench → {s}")
    empties = [s for s, names in lg["lineup_win"]["slots"].items() if any(n.startswith("(") for n in names)]
    if empties:
        moves.append("EMPTY SLOT: " + ", ".join(empties) + " (no healthy player; pick one up)")
    return moves


def _drop_candidate(lg: dict) -> str | None:
    """Weakest bench player by ROS value who isn't a K/DST starter or injured stash worth keeping."""
    starters = {n for names in lg["lineup_win"]["slots"].values() for n in names}
    bench = [p for p in lg["roster"] if p["name"] not in starters and p["pos"] not in ("K", "D/ST")]
    if not bench:
        return None
    return min(bench, key=lambda p: p["mu_ros"])["name"]


def phase_line(lg: dict) -> str | None:
    """One plain sentence about where the week stands, or None before kickoff."""
    ws = lg.get("week_state") or {}
    ph = ws.get("phase", "pre")
    if ph == "pre":
        return None
    me, op = ws.get("espn_my_score", ws.get("my_points")), ws.get("espn_opp_score", ws.get("opp_points"))
    if ph == "final":
        res = "W" if (me or 0) > (op or 0) else ("L" if (me or 0) < (op or 0) else "T")
        return f"Week {lg['week']} final: {res} {me}–{op}"
    left = ws.get("my_left") or []
    ol = ws.get("opp_left") or []
    return (f"Week {lg['week']} in progress: you {me}, them {op} · you have {len(left)} left ({', '.join(left) or 'none'}), "
            f"they have {len(ol)} left")


def trade_tag(t: dict) -> str:
    return "worth sending" if t["their_delta_ppw"] >= 0 else "a reach, send only if bored"


def todos(lg: dict) -> list[dict]:
    """The literal things to do today in one league. Each item: {kind, label, text, moves?}.
    kind ∈ waiver | waiver_up | stream | lineup | trade. Shared by the markdown and HTML renderers."""
    out = []
    starts = [w for w in lg["waivers"] if not w["streamer"] and w.get("delta_week", 0) >= 1.5]
    ups = [w for w in lg["waivers"] if not w["streamer"] and w["delta_over_starter"] >= 1.0 and w not in starts]
    drop = _drop_candidate(lg)
    for w in starts[:1]:
        out.append({"kind": "waiver", "label": "Waiver",
                    "text": f"add {w['name']} ({w['pos']}) and start him at {w['week_slot']} (+{w['delta_week']:.0f} pts this week)" + (f"; drop {drop}" if drop else "")})
    for w in ups[:1]:
        out.append({"kind": "waiver_up", "label": "Waiver (upgrade)",
                    "text": f"add {w['name']} ({w['pos']}), +{w['delta_over_starter']:.1f}/wk over your {w['slot']}" + (f"; drop {drop}" if drop else "")})
    for w in [w for w in lg["waivers"] if w["streamer"] and w["delta_over_starter"] >= 1.5][:1]:
        out.append({"kind": "stream", "label": "Stream", "text": f"swap in {w['name']} at {w['pos']} (+{w['delta_over_starter']:.1f} this week)"})
    ph = (lg.get("week_state") or {}).get("phase", "pre")
    ch = _lineup_changes(lg) if ph != "final" else []
    if ph == "final":
        out.append({"kind": "lineup", "label": "Lineup", "moves": [],
                    "text": f"week {lg['week']} is over; set next week's lineup once ESPN rolls to week {lg['week'] + 1} (Tuesday)"})
    elif ch:
        out.append({"kind": "lineup", "label": "Lineup (in order)" if ph == "pre" else "Lineup (only unplayed slots)", "text": " · ".join(ch), "moves": ch})
    else:
        out.append({"kind": "lineup", "label": "Lineup", "text": "leave as is" if ph == "pre" else "nothing left to change", "moves": []})
    if lg["trades"]:
        t = lg["trades"][0]
        out.append({"kind": "trade", "label": f"Trade ({trade_tag(t)})", "worth": t["their_delta_ppw"] >= 0,
                    "text": f"offer {t['rival']} your {', '.join(t['give'])} for {', '.join(t['get'])} (+{t['my_delta_ppw']:.1f} pts/wk for you, {t['their_delta_ppw']:+.1f} for them)"})
    return out


def why_parts(lg: dict) -> list[str]:
    """Short reasons behind the checklist: risky starters and the game script."""
    lw = lg["lineup_win"]
    starters = {n for names in lw["slots"].values() for n in names}
    flagged = [p for p in lg["roster"] if p["name"] in starters and not p.get("locked") and (p["p_zero"] >= 0.15 or p["bye"])]
    why = []
    if flagged:
        why.append("; ".join(f"{p['name']} {p['p_zero']:.0%} to sit" for p in flagged))
    ph = (lg.get("week_state") or {}).get("phase", "pre")
    if lw.get("p_win") is not None and ph != "final":
        why.append(game_script(lw["p_win"]) + (f" ({lw['p_win']:.0%} with what's left)" if ph == "in_progress" else ""))
    return why


def game_script(p_win: float) -> str:
    return "underdog, favor upside" if p_win < 0.42 else ("favorite, play it safe" if p_win > 0.58 else "coin flip")


def watch_line(w: dict) -> str:
    """One watchlist entry with the override note (Claude's research) if there is one."""
    s = f"{w['name']} {w['status'].title()} ({w['league']})"
    return s + (f" — {w['override_note']}" if w.get("override_note") else "")


AI_TELLS = [
    ("—", "em dash; use a comma or a period"),
    (r"\bnot (?:just |only |merely )?\w[\w' ]{0,30}, but\b", "'not X, but Y' reframe"),
    (r"\b(worth noting|that said|ultimately|it's important to|in today's|game-changer|leverage|robust|seamless|delve)\b", "stock AI phrase"),
    (r"\b(projection|projected|model|points per week|ppw|Claude)\b", "paste message mentions the model or numbers"),
]


def voice_lint(reads: dict) -> list[str]:
    """Flag the well-known AI-writing tells in Claude's prose so the routine can rewrite before sending.
    The last pattern only applies to the paste message (a real person receives it)."""
    import re
    out = []
    for lg, r in reads.items():
        for field in ("read", "paste"):
            txt = (r or {}).get(field) or ""
            if not txt:
                continue
            for pat, why in AI_TELLS[:3] + (AI_TELLS[3:] if field == "paste" else []):
                if re.search(pat, txt, flags=re.I):
                    out.append(f"{lg}.{field}: {why}")
            if field == "paste" and len(txt) > 280:
                out.append(f"{lg}.paste: too long for a chat message ({len(txt)} chars)")
    return out


def action_card(packet: dict, reads: dict | None = None) -> str:
    """Checklist-first: literal things to do today per league, then a one-line why and Claude's read."""
    L = [f"# FF briefing — {packet['generated'][:10]}", ""]
    sh = packet["shared"]; reads = reads or {}
    for lg in packet["leagues"]:
        me = lg["odds"].get(str(lg["my_team_id"])) or {}
        opp = lg["opponent"]; lw = lg["lineup_win"]
        pw = f"{lw['p_win']:.0%}" if lw.get("p_win") is not None else "?"
        final = (lg.get("week_state") or {}).get("phase") == "final"
        L.append(f"## {lg['league_name']}")
        L.append(f"_{lg['my_record']} · vs {opp.get('name')}{'' if final else ' · win ' + pw} · playoffs {me.get('playoff_pct', '?')}% · title {me.get('title_pct', '?')}%_")
        pl = phase_line(lg)
        if pl:
            L.append(f"**{pl}**")
        L.append("")
        for x in todos(lg):
            L.append(f"- **{x['label']}:** {x['text']}")
        L.append("")
        why = why_parts(lg)
        if why:
            L.append("_Why: " + " · ".join(why) + "_")
        r = reads.get(lg["name"]) or {}
        if r.get("read"):
            L.append(f"**Claude's read:** {r['read']}")
        if r.get("paste"):
            L.append(f"**Paste to {r.get('paste_to') or 'the rival'}:** \"{r['paste']}\"")
        L.append("")
    if sh["injury_watchlist"]:
        L.append("**Watch:** " + "; ".join(watch_line(w) for w in sh["injury_watchlist"]))
    if sh["exposure"]:
        L.append("**Exposure:** " + ", ".join(f"{k} ({len(v)}x)" for k, v in sh["exposure"].items()))
    return "\n".join(line if (not line or line.startswith("#") or line.startswith("- ")) else line + "  " for line in L)


def render(packet: dict, detail: bool = True, reads: dict | None = None) -> str:
    """Action card first; full tables after a divider (omit with detail=False)."""
    head = action_card(packet, reads)
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
            risk = "already played this week" if w.get("locked") else f"{w['p_zero']:.0%} chance to sit"
            L.append(f"- **{w['name']}** ({w['pos']}, {w['team']}) — {w['status']} in *{w['league']}*; {risk}" + (f"; {w['notes']}" if w.get("notes") else "") + (f"; {w['override_note']}" if w.get("override_note") else ""))
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
        L.append(f"Record {lg['my_record']} · {acq} · weeks remaining {lg['weeks_remaining']}  ")
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
            L.append("")
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
