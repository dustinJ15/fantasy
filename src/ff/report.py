"""Render a DecisionPacket to markdown. Works with no LLM."""
from __future__ import annotations

import re


def slug(text: str) -> str:
    """Stable, typeable id fragment: 'Jameson Williams' -> 'jameson-williams'."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(text).lower())).strip("-")


def _flags(p: dict) -> str:
    f = [x for x in p.get("flags", []) if not x.startswith("fp:")]
    g = p["sources"].get("grade")
    if g:
        f.append(g)
    if (p.get("weeks_out") or 0) >= 1:
        f.append(f"out ~{p['weeks_out']:.0f}w" + (f", back wk {p['return_week']}" if p.get("return_week") else " (season)"))
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
    """Weakest bench player by rest-of-season value, skipping K/DST and the IR slot.

    `mu_ros` already nets out the games a hurt player will miss, so a season-ender is the cheapest cut and a
    four-week stash is not. The IR occupant is skipped because dropping him frees an IR slot, not a bench spot.
    """
    starters = {n for names in lg["lineup_win"]["slots"].values() for n in names}
    bench = [p for p in lg["roster"] if p["name"] not in starters and p["pos"] not in ("K", "D/ST") and p.get("slot") != "IR"]
    if not bench:
        return None
    return min(bench, key=lambda p: p["mu_ros"])["name"]


# Below this many starters still to play, naming them is the point (Monday morning: two guys decide the week).
# Above it the names are a roster dump — the count is the whole signal.
NAME_LEFT_AT = 3


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
    who = f" ({', '.join(left)})" if 0 < len(left) <= NAME_LEFT_AT else ""
    return f"Week {lg['week']} in progress: you {me} – {op} · {len(left)} starters left{who} vs their {len(ol)}"


def sendable(t: dict) -> bool:
    """Worth putting in front of a rival: helps them too, and I am not overpaying at market value."""
    return bool(t.get("sendable", t["their_delta_ppw"] >= 0))


def trade_tag(t: dict) -> str:
    return "worth sending" if sendable(t) else "a reach, send only if bored"


VERDICT_WORD = {"accept": "ACCEPT", "decline": "DECLINE", "counter": "COUNTER"}


def incoming_line(t: dict) -> str:
    """One sentence on an offer someone sent me: what moves, what it does for each side, when it expires."""
    td = f", title odds {t['my_title_delta']:+.1f}" if t.get("my_title_delta") is not None else ""
    left = f"; expires in {t['hours_left']:.0f}h" if t.get("hours_left") is not None else ""
    return (f"{t['rival']} offers {', '.join(t['get']) or 'nothing'} for your {', '.join(t['give']) or 'nothing'}: "
            f"{t['my_delta_ppw']:+.1f} pts/wk for you, {t['their_delta_ppw']:+.1f} for them{td}{left}")


# Slots the flex cannot cover, so the last healthy body at the position is the whole slot.
COVER_POS = ("QB", "TE", "K", "D/ST")
# Chance of sitting at which a starter needs a contingency plan rather than a note.
RISKY_TO_SIT = 0.4
# The model's why-vocabulary is first person ("leaves me no backup QB"); the checklist is addressed to Dustin.
TO_DUSTIN = (("leaves me ", "leaves you "), ("market says I give", "market says you give"), ("for me", "for you"))


def _to_dustin(s: str) -> str:
    for a, b in TO_DUSTIN:
        s = s.replace(a, b)
    return s


def _cover_items(lg: dict) -> list[dict]:
    """A starter at a slot the flex cannot cover is in real doubt and nothing healthy sits behind him.

    The optimizer never proposes this: a backup kicker is worth ~nothing in expectation, so he loses every ranking
    we have right up to the Sunday his starter is scratched and the slot scores zero. It is still a button to press.
    """
    slots = lg["settings"]["lineup_slots"]
    rec = lg["lineup_win"]["slots"]
    by_name = {p["name"]: p for p in lg["roster"]}
    starters = {n for ns in rec.values() for n in ns}
    out = []
    for pos in COVER_POS:
        if not slots.get(pos):
            continue
        risky = [by_name[n] for n in rec.get(pos, []) if n in by_name and not by_name[n].get("locked")
                 and (by_name[n]["p_zero"] >= RISKY_TO_SIT or by_name[n]["bye"])]
        if not risky:
            continue
        if any(p["pos"] == pos and p["name"] not in starters and p["mu_ros"] > 0 and p["p_zero"] < RISKY_TO_SIT
               for p in lg["roster"]):
            continue  # a healthy body on the bench already covers it
        who = risky[0]
        fa = next((w for w in lg["waivers"] if w["pos"] == pos), None)
        risk = "on bye" if who["bye"] else f"{who['p_zero']:.0%} to sit"
        plan = f"add {fa['name']} ({fa['team']}) before kickoff" if fa else "grab a startable one off the wire before kickoff"
        out.append({"kind": "cover", "id": f"cover:{slug(pos)}", "label": f"Cover {pos}",
                    "text": f"{who['name']} is {risk} and he is your only {pos}; {plan}"})
    return out


INJURY_LABEL = {"ir": "Hurt (IR)", "hold": "Hurt (hold)", "drop": "Hurt (drop)", "trade": "Hurt (trade)", "activate": "Back (activate)"}
# Verdicts that move a player off the roster or out the door: Claude has to rule on them, like trade rows.
INJURY_NEEDS_RULING = ("drop", "trade")


def _weeks(r: dict) -> str:
    if r.get("return_week") is None and (r.get("avail_ros") or 0) == 0:
        return "the season"
    return f"~{r['weeks_out']:.0f} wk{'s' if r['weeks_out'] >= 1.5 else ''}"


def _injury_items(lg: dict, drop: str | None) -> list[dict]:
    """One row per hurt player, the verb decided by `model.injuries`; this only puts words on the numbers."""
    out = []
    for r in lg.get("injuries") or []:
        who, v = f"{r['name']} ({r['pos']})", r["verdict"]
        if v == "hold" and r["weeks_out"] < 2:
            continue  # out one game and worth keeping: the lineup row already handles him, this would be the injury report
        back = f" (back wk {r['return_week']})" if r.get("return_week") else ""
        fa = r.get("best_fa")
        if v == "ir":
            text = f"{who} is out {_weeks(r)}{back}; move him to IR"
            if r.get("ir_occupant"):
                text += f" in place of {r['ir_occupant']}"
            elif fa and fa["delta_over_starter"] > 0:
                text += f", then add {fa['name']} on the freed spot"
        elif v == "activate":
            text = f"{who} is back; move him off IR" + (f" and drop {drop}" if drop and drop != r["name"] else "")
        elif v == "drop":
            text = f"{who} is out {_weeks(r)} and worth ~{r['hold_value']:.0f} pts the rest of the way; drop him"
            if fa and fa["delta_over_starter"] > 0:
                text += f" for {fa['name']} (+{fa['delta_over_starter']:.1f}/wk)"
        elif v == "trade":
            t = r["trades"][0]
            text = f"{who} is out {_weeks(r)}{back}; the offer to {t['rival']} for {', '.join(t['get'])} ships him, else hold"
        else:
            games = f"{r['back_eff']:.0f} game{'s' if r['back_eff'] >= 1.5 else ''}"
            text = f"{who} is out {_weeks(r)}{back} for {games} at ~{r['mu_ros_active']:.0f}/g"
            text += f"; {r['why'][0]}, hold him" if r.get("why") else "; hold him"
        out.append({"kind": "injury", "id": f"injury:{slug(r['name'])}", "label": INJURY_LABEL[v], "verdict": v, "text": text,
                    "trade_ids": [f"trade:{slug('-'.join(t['get']))}" for t in r.get("trades") or []]})
    return out


def todos(lg: dict) -> list[dict]:
    """The literal things to do today in one league. Each item: {id, kind, label, text, moves?}.
    kind ∈ trade_in | sent | waiver | waiver_up | stream | cover | injury | lineup | trade. Shared by both renderers.

    `id` is stable for a given packet, so reads.json can rule on one row by name instead of arguing with the
    whole card in prose. Player names make the ids readable and are unique within a league.
    """
    out = []
    for t in lg.get("incoming_trades") or []:
        out.append({"kind": "trade_in", "id": f"offer:{slug('-'.join(t['get']) or t['rival'] or 'offer')}",
                    "label": f"Incoming offer ({VERDICT_WORD[t['verdict']]})", "verdict": t["verdict"],
                    "text": incoming_line(t)})
    # Offers I already sent are the reason half the "why didn't it know that" moments happen: without them the card
    # re-proposes a deal that is sitting in the rival's inbox with a day left on it.
    for t in lg.get("outgoing_trades") or []:
        left = f", {t['hours_left']:.0f}h left" if t.get("hours_left") is not None else ""
        out.append({"kind": "sent", "id": f"sent:{slug('-'.join(t['get']) or t['rival'] or 'sent')}", "label": "Already sent",
                    "text": f"your {', '.join(t['give']) or 'nothing'} for {', '.join(t['get']) or 'nothing'} is still "
                            f"waiting on {t['rival'] or 'them'}{left}"})
    starts = [w for w in lg["waivers"] if not w["streamer"] and w.get("delta_week", 0) >= 1.5]
    ups = [w for w in lg["waivers"] if not w["streamer"] and w["delta_over_starter"] >= 1.0 and w not in starts]
    drop = _drop_candidate(lg)
    for w in starts[:1]:
        out.append({"kind": "waiver", "id": f"waiver:{slug(w['name'])}", "label": "Waiver",
                    "text": f"add {w['name']} ({w['pos']}) and start him at {w['week_slot']} (+{w['delta_week']:.0f} pts this week)" + (f"; drop {drop}" if drop else "")})
    for w in ups[:1]:
        out.append({"kind": "waiver_up", "id": f"waiver:{slug(w['name'])}", "label": "Waiver (upgrade)",
                    "text": f"add {w['name']} ({w['pos']}), +{w['delta_over_starter']:.1f}/wk over your {w['slot']}" + (f"; drop {drop}" if drop else "")})
    for w in [w for w in lg["waivers"] if w["streamer"] and w["delta_over_starter"] >= 1.5][:1]:
        out.append({"kind": "stream", "id": f"stream:{slug(w['name'])}", "label": "Stream",
                    "text": f"swap in {w['name']} at {w['pos']} (+{w['delta_over_starter']:.1f} this week)"})
    out += _cover_items(lg)
    out += _injury_items(lg, drop)
    ph = (lg.get("week_state") or {}).get("phase", "pre")
    ch = _lineup_changes(lg) if ph != "final" else []
    if ph == "final":
        out.append({"kind": "lineup", "id": "lineup", "label": "Lineup", "moves": [],
                    "text": f"week {lg['week']} is over; set next week's lineup once ESPN rolls to week {lg['week'] + 1} (Tuesday)"})
    elif ch:
        out.append({"kind": "lineup", "id": "lineup", "label": "Lineup (in order)" if ph == "pre" else "Lineup (only unplayed slots)",
                    "text": " · ".join(ch), "moves": ch})
    else:
        out.append({"kind": "lineup", "id": "lineup", "label": "Lineup",
                    "text": "leave as is" if ph == "pre" else "nothing left to change", "moves": []})
    # Every offer that helps both sides is a thing I could actually send today, so list them (capped at 3 so the card
    # stays a checklist). A "reach" only helps me, so at most one of those, and only when there is nothing better.
    worth = [t for t in lg["trades"] if sendable(t)][:3]
    for t in worth or lg["trades"][:1]:
        # Depth and market warnings ride along with the row: the card is the whole HTML email, so a caveat that only
        # reached the detail tables would never be seen on a phone.
        warn = [_to_dustin(w) for w in t["why"] if w.startswith("leaves me") or w.startswith("market says I")]
        them = "neutral for them" if abs(t["their_delta_ppw"]) < 0.05 else f"{t['their_delta_ppw']:+.1f} for them"
        out.append({"kind": "trade", "id": f"trade:{slug('-'.join(t['get']))}", "label": f"Trade ({trade_tag(t)})",
                    "worth": sendable(t), "rival": t.get("rival"), "give": list(t["give"]), "warn": warn,
                    "text": f"offer {t['rival'] or 'them'} your {', '.join(t['give'])} for {', '.join(t['get'])} "
                            f"(+{t['my_delta_ppw']:.1f} pts/wk for you, {them})"})
    return out


RULINGS = ("do", "skip", "amend")


def apply_reads(items: list[dict], r: dict | None) -> list[dict]:
    """Merge Claude's per-row verdicts from reads.json into the checklist.

    The card is the model's math and the read is judgment, and they are allowed to disagree — but the email has to
    end with one answer per row, not a card saying do it and a paragraph underneath saying don't. `skip` strikes the
    row and prints the reason on it; `amend` keeps it with the correction attached.
    """
    ruling = (r or {}).get("items") or {}
    for it in items:
        v = ruling.get(it["id"])
        if isinstance(v, str):
            v = {"verdict": v}
        v = v or {}
        it["ruling"] = (v.get("verdict") or "").lower() or None
        it["ruling_note"] = v.get("note")
    # Trades that ship the same player are alternatives, not a to-do list, and the card has to say so. Computed
    # after the rulings because a skipped row is no longer an alternative to anything: if two of three are struck,
    # the survivor is just the move.
    committed: dict[str, None] = {}
    for it in items:
        if it["kind"] != "trade" or it.get("ruling") == "skip":
            continue
        dup = next((g for g in it.get("give") or [] if g in committed), None)
        if dup:
            it["warn"] = [*it.get("warn", []), f"ships the same {dup} as the offer above, so these are alternatives, pick one"]
        committed.update(dict.fromkeys(it.get("give") or []))
    return items


# Sit risk worth a line in the card. An untouched Questionable sits at exactly 0.30, so anything at or below that is
# a designation rather than a decision, and listing them all just reprints the injury report beside the checklist.
# Above it means the research (or a bye) actually moved the number.
SIT_RISK_SHOWN = 0.35


def why_parts(lg: dict) -> list[str]:
    """Short reasons behind the checklist: the starters actually in doubt, and the game script when it moved a slot."""
    lw = lg["lineup_win"]
    starters = {n for names in lw["slots"].values() for n in names}
    flagged = [p for p in lg["roster"] if p["name"] in starters and not p.get("locked") and (p["p_zero"] >= SIT_RISK_SHOWN or p["bye"])]
    flagged.sort(key=lambda p: -p["p_zero"])
    why = []
    if flagged:
        why.append("; ".join(f"{p['name']} " + ("on bye" if p["bye"] else f"{p['p_zero']:.0%} to sit") for p in flagged[:2]))
    ph = (lg.get("week_state") or {}).get("phase", "pre")
    # P(win) is already a badge at the top of the card. The game script only earns a line when it actually changed
    # something: that is exactly when the P(win) lineup differs from the plain highest-points one.
    if lg.get("lineup_diff") and lw.get("p_win") is not None and ph != "final":
        why.append(game_script(lw["p_win"]) + ", so this is not the highest-points lineup")
    return why


def game_script(p_win: float) -> str:
    return "underdog, favor upside" if p_win < 0.42 else ("favorite, play it safe" if p_win > 0.58 else "coin flip")


def watchlist(packet: dict) -> list[dict]:
    """Cross-league injury watch, one row per player instead of one per (player, league).

    Only two kinds of row survive: someone in this week's lineup, and someone the research actually turned up
    something on. A bare designation on a bench player is the injury report, not a briefing.
    """
    starters = {lg["name"]: {n for ns in lg["lineup_win"]["slots"].values() for n in ns} for lg in packet["leagues"]}
    rows: dict[str, dict] = {}
    for w in packet["shared"]["injury_watchlist"]:
        if w.get("locked"):
            continue  # already played this week; nothing to decide
        starting = w["name"] in starters.get(w["league"], set())
        if not starting and not w.get("override_note"):
            continue
        r = rows.get(w["name"])
        if r is None:
            r = rows[w["name"]] = {**w, "leagues": []}
            r["starting"] = False
        r["leagues"].append(w["league"])
        r["starting"] = r["starting"] or starting
        r["override_note"] = r.get("override_note") or w.get("override_note")
        r["p_zero"] = max(r.get("p_zero") or 0.0, w.get("p_zero") or 0.0)
    return sorted(rows.values(), key=lambda r: (not r["starting"], -(r["p_zero"] or 0.0), r["name"]))


def injured_list(packet: dict) -> list[dict]:
    """Cross-league return timelines, one row per player, longest absence first."""
    rows: dict[str, dict] = {}
    for w in packet["shared"].get("injured") or []:
        r = rows.get(w["name"])
        if r is None:
            r = rows[w["name"]] = {**w, "leagues": []}
        r["leagues"].append(w["league"])
        r["override_note"] = r.get("override_note") or w.get("override_note")
        if (w.get("weeks_out") or 0) > (r.get("weeks_out") or 0):
            r["weeks_out"], r["return_week"] = w["weeks_out"], w.get("return_week")  # the longer absence sets the date
    return sorted(rows.values(), key=lambda r: (-(r["weeks_out"] or 0), r["name"]))


def watch_line(w: dict) -> str:
    """One watchlist entry with the override note (Claude's research) if there is one."""
    s = f"{w['name']} {w['status'].title()} ({', '.join(w.get('leagues') or [w['league']])})"
    return s + (f" — {w['override_note']}" if w.get("override_note") else "")


def injured_line(w: dict) -> str:
    when = "the season" if w.get("return_week") is None and (w.get("weeks_out") or 0) >= 4 else f"~{w['weeks_out']:.0f} wk{'s' if w['weeks_out'] >= 1.5 else ''}"
    back = f", back wk {w['return_week']}" if w.get("return_week") else ""
    s = f"{w['name']} out {when}{back} ({', '.join(w.get('leagues') or [w['league']])})"
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
        for field in ("read", "paste", "reply"):
            txt = (r or {}).get(field) or ""
            if not txt:
                continue
            for pat, why in AI_TELLS[:3] + (AI_TELLS[3:] if field in ("paste", "reply") else []):
                if re.search(pat, txt, flags=re.I):
                    out.append(f"{lg}.{field}: {why}")
            if field in ("paste", "reply") and len(txt) > 280:
                out.append(f"{lg}.{field}: too long for a chat message ({len(txt)} chars)")
    return out


def item_line(x: dict) -> str:
    """One checklist row for the markdown body, with Claude's ruling folded into it rather than argued below it."""
    label, text = x["label"], x["text"]
    if x.get("ruling") == "skip":
        label, text = f"~~{label}~~", f"~~{text}~~"
    line = f"**{label}:** {text}"
    if x.get("warn") and x.get("ruling") != "skip":
        line += f" — {'; '.join(x['warn'])}"
    if x.get("ruling_note"):
        line += f" — **{'skip' if x.get('ruling') == 'skip' else 'note'}:** {x['ruling_note']}"
    return line


def read_lint(packet: dict, reads: dict | None) -> list[str]:
    """Check reads.json against the checklist it is ruling on: typo'd ids silently do nothing, and a trade row with
    no ruling is the old failure mode — three offers on the card and a paragraph that only picks one."""
    reads = reads or {}
    out = []
    ids_by_league = {lg["name"]: {x["id"]: x for x in todos(lg)} for lg in packet["leagues"]}
    for name in reads:
        if name not in ids_by_league:
            out.append(f"{name}: no league by that name in the packet ({', '.join(ids_by_league) or 'none'})")
    for name, known in ids_by_league.items():
        ruled = (reads.get(name) or {}).get("items") or {}
        for key, v in ruled.items():
            if key not in known:
                out.append(f"{name}.items['{key}']: no such row; ids are {', '.join(known)}")
                continue
            verdict = (v if isinstance(v, str) else (v or {}).get("verdict") or "").lower()
            if verdict not in RULINGS:
                out.append(f"{name}.items['{key}']: verdict must be one of {', '.join(RULINGS)}, got '{verdict}'")
            elif verdict != "do" and not (isinstance(v, dict) and v.get("note")):
                out.append(f"{name}.items['{key}']: '{verdict}' needs a note saying why")
        for key, x in known.items():
            if x["kind"] == "trade" and key not in ruled:
                out.append(f"{name}.items['{key}']: trade row has no ruling (do / skip / amend)")
            if x["kind"] == "injury" and x.get("verdict") in INJURY_NEEDS_RULING and key not in ruled:
                out.append(f"{name}.items['{key}']: {x['verdict']} verdict on a hurt player has no ruling (do / skip / amend)")
    return out


def action_card(packet: dict, reads: dict | None = None, show_ids: bool | None = None) -> str:
    """Checklist-first: literal things to do today per league, then a one-line why and Claude's read.

    `show_ids` prints each row's reads.json key. It defaults to on exactly when there are no reads yet, which is the
    draft the routine reads before writing its rulings; the copy that reaches Dustin never carries them.
    """
    L = [f"# FF briefing — {packet['generated'][:10]}", ""]
    sh = packet["shared"]
    show_ids = (not reads) if show_ids is None else show_ids
    reads = reads or {}
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
        r = reads.get(lg["name"]) or {}
        for x in apply_reads(todos(lg), r):
            L.append(f"- {item_line(x)}" + (f"  `[{x['id']}]`" if show_ids else ""))
        L.append("")
        why = why_parts(lg)
        if why:
            L.append("_Why: " + " · ".join(why) + "_")
        if r.get("read"):
            L.append(f"**Claude's read:** {r['read']}")
        if r.get("paste"):
            L.append(f"**Paste to {r.get('paste_to') or 'the rival'}:** \"{r['paste']}\"")
        if r.get("reply"):
            L.append(f"**Reply to {r.get('reply_to') or 'the offer'}:** \"{r['reply']}\"")
        L.append("")
    watch = watchlist(packet)
    if watch:
        L.append("**Watch:** " + "; ".join(watch_line(w) for w in watch))
    hurt = injured_list(packet)
    if hurt:
        L.append("**Out:** " + "; ".join(injured_line(w) for w in hurt))
    if sh["exposure"]:
        L.append("**Exposure:** " + ", ".join(f"{k} ({len(v)}x)" for k, v in sh["exposure"].items()))
    return "\n".join(line if (not line or line.startswith("#") or line.startswith("- ")) else line + "  " for line in L)


def offer_card(packet: dict, reads: dict | None = None) -> str:
    """Just the incoming offers (for the alert email): verdict line, why, and Claude's reply, per league with an offer."""
    reads = reads or {}
    L = [f"# FF trade offer — {packet['generated'][:10]}", ""]
    for lg in packet["leagues"]:
        if not lg.get("incoming_trades"):
            continue
        L.append(f"## {lg['league_name']}")
        L.append("")
        for t in lg["incoming_trades"]:
            L.append(f"- **{VERDICT_WORD[t['verdict']]}:** {incoming_line(t)}. {'; '.join(t['why']) or 'even swap on paper'}")
        L.append("")
        r = reads.get(lg["name"]) or {}
        if r.get("read"):
            L.append(f"**Claude's read:** {r['read']}")
        if r.get("reply"):
            L.append(f"**Reply to {r.get('reply_to') or 'the offer'}:** \"{r['reply']}\"")
        L.append("")
    if len(L) == 2:
        L.append("No incoming offers pending.")
    return "\n".join(line if (not line or line.startswith("#") or line.startswith("- ")) else line + "  " for line in L)


def render(packet: dict, detail: bool = True, reads: dict | None = None, only_incoming: bool = False) -> str:
    """Action card first; full tables after a divider (omit with detail=False). only_incoming: just the offer card."""
    if only_incoming:
        return offer_card(packet, reads)
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
    if sh.get("pending_trades_error"):
        L.append(f"> could not read pending trades: {sh['pending_trades_error']}\n")

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

        L.append("\n## Incoming offers")
        if lg.get("incoming_trades"):
            for t in lg["incoming_trades"]:
                mk = f" · market {t['market_get']} for {t['market_give']}" if t.get("market_give") and t.get("market_get") else ""
                L.append(f"- **{VERDICT_WORD[t['verdict']]}** — {incoming_line(t)}{mk}. {'; '.join(t['why']) or 'even swap on paper'}")
        else:
            L.append("None pending.")
        if lg.get("outgoing_trades"):
            L.append("Your open offers: " + "; ".join(f"{', '.join(t['give'])} for {', '.join(t['get'])} to {t['rival']}" for t in lg["outgoing_trades"]))

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
        for _tid, o in sorted(lg["odds"].items(), key=lambda kv: -kv[1]["title_pct"]):
            L.append(f"| {'**' if o['is_me'] else ''}{o['name']}{'**' if o['is_me'] else ''} | {o['record']} | {o['playoff_pct']} | {o['title_pct']} | {o['exp_wins']} |")
        L.append("\nRival needs: " + "; ".join(f"{lg['odds'].get(tid, {}).get('name', tid)}: " + ", ".join(f"{pos} {v}" for pos, v in n.items() if v) for tid, n in lg["rival_needs"].items()))
    return "\n".join(L)
