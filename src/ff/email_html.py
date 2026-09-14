"""DecisionPacket -> phone-first HTML email.

Rendered straight from the packet (no markdown round-trip) so lists, tables and spacing are deterministic. Constraints:
Gmail strips <style>, so everything is inline; table-based layout; cellpadding/bgcolor/align attributes instead of per-cell
styles to keep the document small enough to paste as a tool argument (~≤60 KB); no images or web fonts; colors chosen to
survive Gmail's dark-mode inversion (no pure-black text, badges are tinted backgrounds with dark text).

Claude's prose comes in via `reads`: {"<league name>": {"read": "...", "paste": "...", "paste_to": "..."}}.
"""
from __future__ import annotations

from datetime import datetime
from html import escape as _e

from . import report

# palette: (background, text)
TONES = {
    "good": ("#d7f5e0", "#0b6b3a"),
    "warn": ("#fff1c2", "#7a5400"),
    "bad": ("#fde2e2", "#9b1c1c"),
    "info": ("#e6ecff", "#2b3f9e"),
    "move": ("#eee4ff", "#5b2ea6"),
    "grey": ("#e9ecef", "#4b5563"),
}
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
TEXT, MUTED, BORDER, PAGE, CARD, ZEBRA = "#1f2933", "#6b7280", "#e3e6ea", "#eef0f3", "#ffffff", "#f6f7f9"
LABELS = {"waiver": ("WAIVER", "info"), "waiver_up": ("WAIVER", "info"), "stream": ("STREAM", "info"),
          "lineup": ("LINEUP", "move"), "trade": ("TRADE", "good")}


def _badge(text: str, tone: str = "grey") -> str:
    bg, fg = TONES[tone]
    return (f'<span style="display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;font-weight:600;'
            f'background:{bg};color:{fg};white-space:nowrap">{_e(text)}</span>')


def _muted(text: str, size: int = 13) -> str:
    return f'<div style="color:{MUTED};font-size:{size}px;margin-top:4px">{text}</div>'


def _h(text: str, size: int = 15) -> str:
    return f'<div style="font-size:{size}px;font-weight:700;margin:14px 0 6px">{_e(text)}</div>'


def _table(headers: list[str], rows: list[list[str]], align: str = "", size: int = 13, hilite: int | None = None) -> str:
    """Compact table: cellpadding + bgcolor zebra, per-cell markup is just <td> or <td align=right>.
    `align` is one char per column: 'l' or 'r'. `hilite` = row index to tint."""
    align = align or "l" * len(headers)
    th = "".join(f'<th align="{"right" if a == "r" else "left"}" style="color:{MUTED};font-weight:600;font-size:11px;'
                 f'text-transform:uppercase;border-bottom:1px solid {BORDER}">{_e(h)}</th>' for h, a in zip(headers, align))
    body = []
    for i, r in enumerate(rows):
        bg = TONES["warn"][0] if i == hilite else (ZEBRA if i % 2 else CARD)
        body.append(f'<tr bgcolor="{bg}">' + "".join(f'<td{" align=right" if a == "r" else ""}>{c}</td>' for c, a in zip(r, align)) + "</tr>")
    return (f'<table width="100%" cellpadding="5" cellspacing="0" border="0" style="border-collapse:collapse;font-size:{size}px;margin:6px 0">'
            f"<tr>{th}</tr>{''.join(body)}</table>")


def _card(title: str, sub: str, body: str, accent: str = BORDER) -> str:
    return (f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 14px"><tr><td bgcolor="{CARD}" '
            f'style="border:1px solid {BORDER};border-top:4px solid {accent};border-radius:8px;padding:14px 16px">'
            f'<div style="font-size:18px;font-weight:700">{_e(title)}</div>{sub}{body}</td></tr></table>')


def _callout(label: str, text: str, tone: str = "info", quote: bool = False) -> str:
    bg, fg = TONES[tone]
    inner = f'<div style="font-size:14px;margin-top:3px{";font-style:italic" if quote else ""}">{_e(text)}</div>'
    return (f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:10px 0 0"><tr><td bgcolor="{bg}" '
            f'style="border-left:4px solid {fg};border-radius:0 6px 6px 0;padding:8px 12px">'
            f'<div style="font-size:11px;font-weight:700;color:{fg};text-transform:uppercase">{_e(label)}</div>{inner}</td></tr></table>')


# ---------- player status wording (model jargon -> plain words) ----------

def _status(p: dict) -> tuple[str, str] | None:
    """(label, tone) for a player's availability, or None when healthy."""
    s = p["sources"]
    st = (s.get("espn_status") or "").upper()
    sl = (s.get("sleeper_status") or "").upper()
    if p.get("bye"):
        return "BYE", "grey"
    if "OUT" in (st, sl) or st in ("INJURY_RESERVE", "IR", "SUSPENSION") or p["p_zero"] >= 0.95:
        return "OUT", "bad"
    if "DOUBTFUL" in (st, sl) or p["p_zero"] >= 0.6:
        return "DOUBTFUL", "warn"
    if "QUESTIONABLE" in (st, sl) or st == "DAY_TO_DAY" or p["p_zero"] >= 0.15:
        return "QUESTIONABLE", "warn"
    if sl in ("NA", "PUP", "SUS"):
        return sl, "grey"
    return None


SHORT = {"QUESTIONABLE": "Q", "DOUBTFUL": "D"}


def _status_cell(p: dict) -> str:
    bits = []
    st = _status(p)
    if p.get("locked"):
        bits.append(_badge("PLAYED", "grey"))
    elif st:
        bits.append(_badge(SHORT.get(st[0], st[0]), st[1]))
    g = p["sources"].get("grade")
    if g:
        tone = "good" if g.startswith("A") else ("info" if g.startswith("B") else ("warn" if g.startswith("C") else "grey"))
        bits.append(_badge(g, tone))
    notes = []
    if p["sources"].get("sleeper_notes") and st:
        notes.append(str(p["sources"]["sleeper_notes"]))
    if p["sources"].get("override_note"):
        notes.append(str(p["sources"]["override_note"]))
    elif any(f.startswith("llm:") for f in p.get("flags", [])):
        notes.append("adjusted from news")
    out = " ".join(bits)
    if notes:
        out += f'<div style="color:{MUTED};font-size:11px">{_e("; ".join(notes))}</div>'
    return out


def _why_clean(why: list[str]) -> str:
    """Waiver 'why' bullets without the fp:/llm: tokens (the grade shows as a badge instead)."""
    return " · ".join(w for w in why if not (w.startswith("fp:") or w.startswith("llm:")))


def _pct(x) -> str:
    return "?" if x is None else f"{x:.0f}%"


# ---------- sections ----------

def _stat_row(lg: dict) -> str:
    me = lg["odds"].get(str(lg["my_team_id"])) or {}
    lw = lg["lineup_win"]; opp = lg["opponent"]
    pw = lw.get("p_win")
    tone = "grey" if pw is None else ("good" if pw > 0.58 else ("warn" if pw < 0.42 else "grey"))
    final = (lg.get("week_state") or {}).get("phase") == "final"
    cells = [
        f"<b>{_e(lg['my_record'])}</b>",
        f"vs {_e(opp.get('name') or 'TBD')}",
        *([] if final else [f"Win {_badge(_pct(pw * 100 if pw is not None else None), tone)}"]),
        f"Playoffs <b>{_pct(me.get('playoff_pct'))}</b>",
        f"Title <b>{_pct(me.get('title_pct'))}</b>",
    ]
    return f'<div style="color:{MUTED};font-size:13px;margin-top:3px">{" &nbsp;·&nbsp; ".join(cells)}</div>'


def _todo_rows(lg: dict) -> str:
    rows = []
    for t in report.todos(lg):
        label, tone = LABELS[t["kind"]]
        if t["kind"] == "trade":
            tone = "good" if t.get("worth") else "grey"
            label = "TRADE" if t.get("worth") else "TRADE (reach)"
        if t["kind"] == "lineup" and t.get("moves"):
            body = "<b>In this order:</b><br>" + "<br>".join(
                _e(m).replace(" → ", ' <span style="color:%s">→</span> ' % MUTED) for m in t["moves"])
        else:
            body = _e(t["text"])
        rows.append(f'<tr><td valign="top" width="1" style="padding:6px 8px 6px 0">{_badge(label, tone)}</td>'
                    f'<td valign="top" style="padding:6px 0;font-size:14px;border-bottom:1px solid {BORDER}">{body}</td></tr>')
    return f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:8px">{"".join(rows)}</table>'


def _phase(lg: dict) -> str:
    pl = report.phase_line(lg)
    if not pl:
        return ""
    ph = lg["week_state"]["phase"]
    tone = "grey" if ph == "final" else "warn"
    return f'<div style="margin-top:6px">{_badge("FINAL" if ph == "final" else "IN PROGRESS", tone)} <span style="font-size:13px">{_e(pl.split(": ", 1)[1])}</span></div>'


def _league_action(lg: dict, r: dict) -> str:
    body = _phase(lg) + _todo_rows(lg)
    why = report.why_parts(lg)
    if why:
        body += _muted("Why: " + _e(" · ".join(why)))
    if r.get("read"):
        body += _callout("Claude's read", r["read"], "info")
    if r.get("paste"):
        body += _callout(f"Paste to {r.get('paste_to') or 'the rival'}", r["paste"], "good", quote=True)
    pw = lg["lineup_win"].get("p_win")
    accent = TONES["good"][1] if pw is not None and pw > 0.58 else (TONES["warn"][1] if pw is not None and pw < 0.42 else "#94a3b8")
    return _card(lg["league_name"], _stat_row(lg), body, accent)


def _shared(sh: dict) -> str:
    parts = []
    if sh["injury_watchlist"]:
        items = []
        for w in sh["injury_watchlist"]:
            tone = "bad" if w["status"] == "OUT" else "warn"
            s = f"{_badge(w['status'], tone)} <b>{_e(w['name'])}</b> <span style='color:{MUTED}'>({_e(w['pos'])}, {_e(w['league'])})</span>"
            if w.get("override_note"):
                s += f" — {_e(w['override_note'])}"
            items.append(s)
        parts.append(_h("Watch") + "<div style='font-size:13px;line-height:1.7'>" + "<br>".join(items) + "</div>")
    if sh["exposure"]:
        parts.append(_h("Exposure") + _muted(", ".join(f"<b>{_e(k)}</b> ({', '.join(map(_e, v))})" for k, v in sh["exposure"].items())))
    if not parts:
        return ""
    return _card("Across leagues", "", "".join(parts), "#94a3b8")


def _lineup_table(lg: dict) -> str:
    by_name = {p["name"]: p for p in lg["roster"]}
    rows = []
    for slot, names in lg["lineup_win"]["slots"].items():
        cells = []
        for n in names:
            if n.startswith("("):
                cells.append(_badge("EMPTY", "bad") + " " + _e(n))
                continue
            p = by_name.get(n)
            st = _status(p) if p else None
            if p and p.get("locked"):
                cells.append(_e(n) + f" <span style='color:{MUTED}'>{p.get('actual') or 0:.1f} pts</span> {_badge('PLAYED', 'grey')}")
                continue
            cells.append(_e(n) + (f" {_badge(SHORT.get(st[0], st[0]), st[1])}" if st else "") + (f" <span style='color:{MUTED}'>{p['mu']:.1f}</span>" if p else ""))
        rows.append([f"<b>{_e(slot)}</b>", ", ".join(cells)])
    return _table(["Slot", "Start"], rows, "ll")


def _league_detail(lg: dict) -> str:
    lw, opp = lg["lineup_win"], lg["opponent"]
    me = lg["odds"].get(str(lg["my_team_id"])) or {}
    acq = f"FAAB left ${lg['faab_remaining']}" if lg.get("faab_remaining") is not None else f"waiver priority #{lg.get('waiver_rank')}"
    sub = _muted(f"Week {lg['week']} · {_e(acq)} · {lg['weeks_remaining']} weeks left · expected wins {me.get('exp_wins', '?')}")
    body = _h("Matchup")
    pw = f" · P(win) <b>{lw['p_win']:.0%}</b>" if lw.get("p_win") is not None else ""
    body += _muted(f"You <b>{lw['mu']:.1f}</b> ± {lw['sd']:.0f} vs {_e(opp.get('name') or 'TBD')} <b>{opp.get('mu', '?')}</b> ± {opp.get('sd', '?')}{pw}"
                   f" · current ESPN lineup {lg['current_lineup_mu']}")
    body += _lineup_table(lg)
    if lg["lineup_diff"]:
        body += _muted("Pure-points lineup differs: " + _e("; ".join(f"{d['name']} in {d['in']} lineup ({d['ev']} ± {d['sd']})" for d in lg["lineup_diff"])), 12)
    body += _muted("Bench: " + _e(", ".join(lw["bench"])), 12)

    body += _h("Roster") + _muted("Wk = projected points this week · ROS = rest-of-season per game · Q/D = questionable/doubtful", 11)
    rows = [[_e(p["name"]), _e(p["pos"]), f"{p['mu']:.1f}", f"{p['mu_ros']:.1f}", _status_cell(p)] for p in lg["roster"]]
    body += _table(["Player", "Pos", "Wk", "ROS", "Status"], rows, "llrrl", 12)

    body += _h("Waivers")
    if lg["waivers"]:
        faab = lg.get("faab_remaining") is not None
        rows = []
        for w in lg["waivers"][:6]:
            d = (f"+{w['delta_over_starter']:.1f} at {w['slot']}" if w["delta_over_starter"] > 0 else f"{w['delta_over_starter']:.1f} vs {w['slot']}") if w["slot"] else "depth"
            name = f"<b>{_e(w['name'])}</b>" + (f"<div style='color:{MUTED};font-size:11px'>{_e(_why_clean(w['why']))}</div>" if _why_clean(w["why"]) else "")
            r = [name, _e(w["pos"]), f"{w['mu_week']:.1f}", f"{w['mu_ros']:.1f}", _e(d)]
            if faab:
                r.append(f"${w['bid']}")
            rows.append(r)
        body += _table(["Target", "Pos", "Wk", "ROS", "vs starter"] + (["Bid"] if faab else []), rows, "llrrl" + ("r" if faab else ""), 12)
    else:
        body += _muted("Nothing worth a claim.")
    if lg["handcuffs"]:
        body += _muted("Handcuffs: " + _e("; ".join(f"{h['handcuff']} for {h['starter']} ({'FA' if h['owner_team_id'] is None else 'owned'})" for h in lg["handcuffs"])), 12)

    body += _h("Trades")
    if lg["trades"]:
        rows = []
        for t in lg["trades"][:3]:
            worth = t["their_delta_ppw"] >= 0
            td = f" · title odds you {t['my_title_delta']:+.1f} / them {t['their_title_delta']:+.1f}" if "my_title_delta" in t else ""
            rows.append([_badge("SEND" if worth else "REACH", "good" if worth else "grey"),
                         f"Give <b>{_e(', '.join(t['give']))}</b> → get <b>{_e(', '.join(t['get']))}</b> from {_e(t['rival'])}"
                         f"<div style='color:{MUTED};font-size:11px'>you {t['my_delta_ppw']:+.1f} ppw / them {t['their_delta_ppw']:+.1f}{td} · {_e('; '.join(t['why']))}</div>"])
        body += _table(["", "Offer"], rows, "ll", 13)
    else:
        body += _muted("No mutually beneficial package found this week.")

    body += _h("League odds")
    ranked = sorted(lg["odds"].values(), key=lambda o: -o["title_pct"])
    show = [o for i, o in enumerate(ranked) if i < 5 or o["is_me"]]
    hil = next((i for i, o in enumerate(show) if o["is_me"]), None)
    rows = [[(f"<b>{_e(o['name'])}</b>" if o["is_me"] else _e(o["name"])), _e(o["record"]), f"{o['playoff_pct']:.0f}%", f"{o['title_pct']:.0f}%", f"{o['exp_wins']:.1f}"] for o in show]
    body += _table(["Team", "Rec", "Playoffs", "Title", "Exp W"], rows, "llrrr", 12, hil)
    if len(ranked) > len(show):
        body += _muted(f"…and {len(ranked) - len(show)} more (full table in the plain-text version)", 11)
    needs = [(lg["odds"].get(tid, {}).get("name", tid), [pos for pos, v in n.items() if v]) for tid, n in lg["rival_needs"].items()]
    needs = [(nm, ps) for nm, ps in needs if ps][:6]
    if needs:
        body += _muted("Rival needs: " + " · ".join(f"<b>{_e(nm)}</b> {_e(', '.join(ps))}" for nm, ps in needs), 12)
    return _card(lg["league_name"], sub, body, "#94a3b8")


def render_email(packet: dict, reads: dict | None = None) -> str:
    reads = reads or {}
    try:
        gen = datetime.fromisoformat(packet["generated"])
        when = gen.strftime("%a %b %-d")
    except ValueError:
        gen, when = None, packet["generated"][:10]
    week = packet["leagues"][0]["week"] if packet["leagues"] else "?"
    head = (f'<div style="font-size:22px;font-weight:800;margin:4px 0 2px">FF briefing</div>'
            f'<div style="color:{MUTED};font-size:13px;margin-bottom:14px">Week {week} · {_e(when)}</div>')
    actions = "".join(_league_action(lg, reads.get(lg["name"]) or {}) for lg in packet["leagues"])
    shared = _shared(packet["shared"])
    divider = (f'<div style="margin:22px 0 12px;border-top:2px dashed #c4c9d0"></div>'
               f'<div style="font-size:12px;font-weight:700;color:{MUTED};text-transform:uppercase;margin-bottom:10px">Full detail</div>')
    details = "".join(_league_detail(lg) for lg in packet["leagues"])
    if packet["shared"].get("usage_error"):
        details += _muted("Usage metrics unavailable this run.", 11)
    foot = _muted(f"Generated {_e(packet['generated'][:16].replace('T', ' '))} · numbers from ff, read from Claude · read-only against ESPN", 11)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark"></head>'
        f'<body style="margin:0;padding:0;background:{PAGE}">'
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PAGE}"><tr><td align="center" style="padding:12px 8px">'
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;font-family:{FONT};color:{TEXT};line-height:1.45">'
        f"<tr><td>{head}{actions}{shared}{divider}{details}{foot}</td></tr></table></td></tr></table></body></html>"
    )
