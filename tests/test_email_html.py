"""HTML email renderer over the synthetic league: structure, reads, no leaked jargon, size."""
from html import escape

from ff import report
from ff.email_html import render_email
from ff.packet import analyze_league
from tests.test_packet_synthetic import FakeXW, make_snapshot


def _packet(monkeypatch):
    monkeypatch.setattr("ff.packet.fantasycalc.by_espn_id", lambda **kw: {})
    snap = make_snapshot()
    snap["settings"]["name"] = "Bill & Ted's League"
    snap["teams"][1]["name"] = "O'Brien's Boys"
    blk = analyze_league(snap, FakeXW(), {}, {}, {}, {}, overrides=None, sims=200)
    blk["name"] = "L9"
    watch = [{"name": blk["roster"][0]["name"], "pos": "RB", "team": "GB", "league": "L9", "status": "QUESTIONABLE",
              "notes": None, "espn_id": 1, "p_zero": 0.3, "override_note": "limited Friday, expected to play"}]
    return {"version": 3, "generated": "2026-09-10T07:00:00", "season": 2026,
            "shared": {"injury_watchlist": watch, "exposure": {"RB1_0": ["L9", "L8"]}, "trending_adds": [], "usage_error": None, "unmatched_ids": []},
            "leagues": [blk]}


def test_render_email(monkeypatch):
    p = _packet(monkeypatch)
    reads = {"L9": {"read": "Coin flip, lineup is fine.", "paste": "Want to swap RBs?", "paste_to": "O'Brien's Boys"}}
    html = render_email(p, reads)
    assert "Bill &amp; Ted&#x27;s League" in html and "O&#x27;Brien&#x27;s Boys" in html
    assert "Coin flip, lineup is fine." in html and "Want to swap RBs?" in html and "Paste to O&#x27;Brien" in html
    assert "limited Friday, expected to play" in html
    assert "move him to IR" in html and ">IR<" in html  # the hurt-player row, with its verdict as the badge
    for todo in report.todos(p["leagues"][0]):
        if not todo.get("moves"):
            assert escape(todo["text"])[:30] in html
    for jargon in ("p_zero", "fp:", "llm:", "espn:", "sleeper:"):
        assert jargon not in html
    # default: action cards only, small enough to transcribe into a mail tool
    assert len(html) < 20_000
    assert "Full detail" not in html and "League odds" not in html
    assert "OFFER" in html
    assert "white-space:nowrap" in html  # "ACCEPT OFFER" badge must never wrap onto two lines
    # every closing </tr>/</table>/</div> ends a line, so no read chunk can split a tag
    assert "</tr><" not in html and "</table><" not in html and "</div><" not in html
    assert max(len(ln) for ln in html.splitlines()) < 2_000
    # --full keeps the old appendix
    detailed = render_email(p, reads, full=True)
    assert "Full detail" in detailed and "League odds" in detailed
    assert "Offers on the table" in detailed and "SENT" in detailed
    # the detail always lives in the plain-text part
    assert "League odds" in report.render(p, reads=reads)
    # alert-tier email: only the offer, with the reply callout
    short = render_email(p, {"L9": {"reply": "how about RB2 straight up?", "reply_to": "Team 2"}}, only_incoming=True)
    assert "FF trade offer" in short and "how about RB2 straight up?" in short and "Waivers" not in short
    assert len(short) < 20_000
    # no reads -> no callouts
    bare = render_email(p)
    assert "Claude" not in bare.replace("read from Claude", "")


def test_markdown_lists_render(monkeypatch):
    p = _packet(monkeypatch)
    md = report.render(p, reads={"L9": {"read": "hold"}})
    head = md.split("---")[0]
    lines = head.splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith("- "))
    assert lines[first - 1] == ""  # blank line so markdown makes a real list
    assert "**Claude's read:** hold" in head
    assert "p_zero=" not in md


def test_voice_lint_flags_ai_tells():
    reads = {"L1": {"read": "It's not the lineup — it's the matchup. Not a bad spot, but a risky one.", "paste": "Per my model you gain 2.1 ppw. Worth noting this is robust."},
             "L2": {"read": "Coin flip, leave it.", "paste": "hey, any interest in Rice + Montgomery for Henry? you're thin at WR. no worries if not"}}
    warns = report.voice_lint(reads)
    assert any(w.startswith("L1.read") and "em dash" in w for w in warns)
    assert any("not X, but Y" in w for w in warns)
    assert any(w.startswith("L1.paste") and "model" in w for w in warns)
    assert not any(w.startswith("L2") for w in warns)


def test_depth_warning_reaches_both_renderers(monkeypatch):
    """A 'leaves me no backup QB' caveat is useless if it only lands in the detail tables the HTML no longer carries."""
    p = _packet(monkeypatch)
    lg = p["leagues"][0]
    assert lg["trades"], "the demo league should produce at least one candidate"
    lg["trades"][0]["why"].append("leaves me no backup QB")  # the caveat the scan attaches when a package ships the spare QB
    warns = [w for t in report.todos(lg) for w in (t.get("warn") or [])]
    assert warns
    html, md = render_email(p), report.render(p)
    for w in warns:
        assert escape(w) in html, f"missing from the card: {w}"
        assert w in md, f"missing from the plain text: {w}"


def test_a_skipped_row_is_struck_through_with_its_reason(monkeypatch):
    """The whole point of the rulings: the email ends with one answer per row, not a card saying do it and a
    paragraph underneath saying don't."""
    p = _packet(monkeypatch)
    lg = p["leagues"][0]
    trade_ids = [t["id"] for t in report.todos(lg) if t["kind"] == "trade"]
    assert trade_ids, "fixture should offer at least one trade to rule on"
    reads = {"L9": {"items": {trade_ids[0]: {"verdict": "skip", "note": "he is in a boot, not this week"}}}}
    html = render_email(p, reads)
    assert "line-through" in html and "SKIP" in html
    assert escape("he is in a boot, not this week") in html


def test_the_paste_message_rides_on_the_trade_it_belongs_to(monkeypatch):
    p = _packet(monkeypatch)
    lg = p["leagues"][0]
    trades = [t for t in report.todos(lg) if t["kind"] == "trade"]
    assert trades, "fixture should offer at least one trade for the message to attach to"
    reads = {"L9": {"paste": "any interest in this one?", "paste_to": trades[0]["rival"]}}
    html = render_email(p, reads)
    assert html.count("any interest in this one?") == 1
    # the message sits inside the checklist, above the "Why" line, not adrift at the bottom of the card
    assert html.index("any interest in this one?") < html.index("Why:")


def test_title_odds_are_not_in_the_action_card(monkeypatch):
    p = _packet(monkeypatch)
    html = render_email(p, {})
    assert "Playoffs" in html and "Title" not in html
