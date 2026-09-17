"""End-to-end over the synthetic demo league: analyze_league -> report.render, no network."""
from ff import demo, report
from ff.packet import PACKET_VERSION, analyze_league

FakeXW = demo.FakeCrosswalk
make_snapshot = demo.make_snapshot


def test_end_to_end_synthetic(monkeypatch):
    monkeypatch.setattr("ff.packet.fantasycalc.by_espn_id", lambda **kw: {})
    snap = make_snapshot()
    blk = analyze_league(snap, FakeXW(), {}, {}, {}, {}, overrides=None, sims=300)
    assert blk["my_team_id"] == 1
    assert sum(len(v) for v in blk["lineup_win"]["slots"].values()) == 9
    assert blk["lineup_win"]["p_win"] is not None
    assert abs(sum(o["title_pct"] for o in blk["odds"].values()) - 100) < 2
    assert blk["waivers"] and all(w["bid"] <= blk["faab_remaining"] for w in blk["waivers"])
    packet = {"version": PACKET_VERSION, "generated": "2026-09-10T07:00:00", "season": 2026,
              "shared": {"injury_watchlist": [], "exposure": {}, "trending_adds": [], "usage_error": None, "unmatched_ids": []},
              "leagues": [blk]}
    md = report.render(packet)
    assert "Demo League" in md and "## Waivers" in md and "## League odds" in md and "Lineup" in md
    # incoming offer: evaluated, first in the checklist, outgoing listed separately
    inc = blk["incoming_trades"]
    by_id = {r["espn_id"]: r["name"] for r in snap["roster"]}
    offer = snap["pending_trades"][0]
    give, get = [by_id[i] for i in offer["give"]], [by_id[i] for i in offer["get"]]
    rival2, rival3 = snap["teams"][1]["name"], snap["teams"][2]["name"]
    assert len(inc) == 1 and inc[0]["verdict"] in ("accept", "decline", "counter") and inc[0]["rival"] == rival2
    assert inc[0]["give"] == give and inc[0]["get"] == get and "my_title_delta" in inc[0]
    assert len(blk["outgoing_trades"]) == 1 and blk["outgoing_trades"][0]["rival"] == rival3
    first = report.todos(blk)[0]
    assert first["kind"] == "trade_in" and f"{rival2} offers {get[0]} for your {give[0]}, {give[1]}" in first["text"]
    assert "## Incoming offers" in md and "Your open offers" in md
    short = report.render(packet, reads={"demo": {"reply": "thanks but no", "reply_to": rival2}}, only_incoming=True)
    assert short.startswith("# FF trade offer") and f"Reply to {rival2}" in short and "## Waivers" not in short
    # overrides flow through
    pid = str(blk["roster"][0]["espn_id"])
    blk2 = analyze_league(snap, FakeXW(), {}, {}, {}, {}, overrides={pid: {"p_zero": 1.0}}, sims=100)
    assert blk2["roster"][-1]["espn_id"] == int(pid) or any(r["espn_id"] == int(pid) and r["p_zero"] == 1.0 for r in blk2["roster"])


def test_card_lists_every_worth_sending_trade(monkeypatch):
    """More than one sendable offer means more than one checklist row, capped at 3; reaches stay a single row."""
    monkeypatch.setattr("ff.packet.fantasycalc.by_espn_id", lambda **kw: {})
    blk = analyze_league(make_snapshot(), FakeXW(), {}, {}, {}, {}, overrides=None, sims=200)
    rows = [t for t in report.todos(blk) if t["kind"] == "trade"]
    worth = [t for t in blk["trades"] if t["their_delta_ppw"] >= 0][:3]
    assert len(rows) <= 3
    if worth:
        assert len(rows) == len(worth) and all(r["worth"] for r in rows)
        assert [r["text"].split(" your ")[0] for r in rows] == [f"offer {t['rival']}" for t in worth]
    else:
        assert len(rows) <= 1 and not any(r["worth"] for r in rows)
