"""HTML email renderer over the synthetic league: structure, reads, no leaked jargon, size."""
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
    for todo in report.todos(p["leagues"][0]):
        if not todo.get("moves"):
            assert todo["text"][:30] in html
    for jargon in ("p_zero", "fp:", "llm:", "espn:", "sleeper:"):
        assert jargon not in html
    assert len(html) < 80_000
    assert "Full detail" in html and "League odds" in html
    # no reads -> no callouts
    bare = render_email(p)
    assert "Claude" not in bare.split("Full detail")[0].replace("read from Claude", "")


def test_markdown_lists_render(monkeypatch):
    p = _packet(monkeypatch)
    md = report.render(p, reads={"L9": {"read": "hold"}})
    head = md.split("---")[0]
    lines = head.splitlines()
    first = next(i for i, l in enumerate(lines) if l.startswith("- "))
    assert lines[first - 1] == ""  # blank line so markdown makes a real list
    assert "**Claude's read:** hold" in head
    assert "p_zero=" not in md
