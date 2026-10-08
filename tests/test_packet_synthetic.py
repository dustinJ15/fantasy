"""End-to-end over the synthetic demo league: analyze_league -> report.render, no network."""
from datetime import UTC, datetime

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
    assert blk["settings"]["ir_slots"] == 1 and blk["settings"]["reg_season_weeks"] == 14
    hurt = {r["name"]: r for r in blk["injuries"]}
    ir_guy = next(p for p in blk["roster"] if p["sources"]["espn_status"] == "INJURY_RESERVE")
    assert ir_guy["weeks_out"] == 4 and ir_guy["mu_ros"] < ir_guy["mu_ros_active"] and hurt[ir_guy["name"]]["verdict"] == "ir"
    assert any(x["kind"] == "injury" for x in report.todos(blk))
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
    # overrides flow through, including the season horizon into the research list
    done = {str(ir_guy["espn_id"]): {"weeks_out": "season", "note": "torn ACL"}}
    blk3 = analyze_league(snap, FakeXW(), {}, {}, {}, {}, overrides=done, sims=100)
    gone = next(p for p in blk3["roster"] if p["espn_id"] == ir_guy["espn_id"])
    assert gone["mu_ros"] == 0 and gone["return_week"] is None and gone["sources"]["weeks_out_source"] == "override"
    assert {r["verdict"] for r in blk3["injuries"] if r["espn_id"] == ir_guy["espn_id"]} == {"ir"}
    pid = str(blk["roster"][0]["espn_id"])
    blk2 = analyze_league(snap, FakeXW(), {}, {}, {}, {}, overrides={pid: {"p_zero": 1.0}}, sims=100)
    assert blk2["roster"][-1]["espn_id"] == int(pid) or any(r["espn_id"] == int(pid) and r["p_zero"] == 1.0 for r in blk2["roster"])


def test_card_lists_every_worth_sending_trade(monkeypatch):
    """More than one sendable offer means more than one checklist row, capped at 3; reaches stay a single row."""
    monkeypatch.setattr("ff.packet.fantasycalc.by_espn_id", lambda **kw: {})
    blk = analyze_league(make_snapshot(), FakeXW(), {}, {}, {}, {}, overrides=None, sims=200)
    rows = [t for t in report.todos(blk) if t["kind"] == "trade"]
    pushed = [t for t in blk["trades"] if t.get("must_try")][:1]  # the one big package goes first, however it was ranked
    worth = pushed + [t for t in blk["trades"] if t["their_delta_ppw"] >= 0 and t not in pushed][:3 - len(pushed)]
    assert len(rows) <= 3
    if worth:
        assert len(rows) == len(worth) and all(r["worth"] for r in rows)
        assert [r["text"].split(" your ")[0] for r in rows] == [f"offer {t['rival']}" for t in worth]
    else:
        assert len(rows) <= 1 and not any(r["worth"] for r in rows)


def test_empty_offer_has_zero_title_delta(monkeypatch):
    """A3: trade and offer rows compare a re-sim against the baseline with common random numbers, so an offer that
    moves nobody reads 0.0 at any draw count; a re-sim on its own seed used to read up to +-1.5 title points."""
    monkeypatch.setattr("ff.packet.fantasycalc.by_espn_id", lambda **kw: {})
    snap = make_snapshot()
    null = {**snap["pending_trades"][0], "give": [], "get": []}
    snap["pending_trades"] = [null]
    for sims in (100, 300):
        blk = analyze_league(snap, FakeXW(), {}, {}, {}, {}, overrides=None, sims=sims)
        inc = blk["incoming_trades"]
        assert len(inc) == 1 and inc[0]["my_title_delta"] == 0.0 and inc[0]["their_title_delta"] == 0.0
        assert type(inc[0]["my_title_delta"]) is float


def _bench_best_rb(snap: dict, tid: int) -> tuple[dict, dict]:
    """Swap the rival's top RB to the bench and his fourth RB into the slot; returns (benched, promoted)."""
    rbs = sorted((r for r in snap["roster"] if r["fantasy_team_id"] == tid and r["pos"] == "RB"), key=lambda r: -r["proj_week"])
    best, scrub = rbs[0], rbs[-1]
    assert best["slot"] == "RB" and scrub["slot"] == "BE"
    best["slot"], scrub["slot"] = "BE", "RB"
    return best, scrub


def _fill_flex(snap: dict, tid: int) -> None:
    wr = sorted((r for r in snap["roster"] if r["fantasy_team_id"] == tid and r["pos"] == "WR" and r["slot"] == "BE"), key=lambda r: -r["proj_week"])[0]
    wr["slot"] = "RB/WR/TE"


def test_a_set_lineup_on_sunday_is_the_opponents_strength(monkeypatch):
    """A4: from Saturday on the rival's lineup is set and visible in each player's `slot`, so a rival who benched his
    best RB projects for less than the optimizer's guess; midweek, with a slot still open, the optimizer stands."""
    monkeypatch.setattr("ff.packet.fantasycalc.by_espn_id", lambda **kw: {})
    sunday, wednesday = datetime(2026, 10, 11, 14, tzinfo=UTC), datetime(2026, 10, 7, 14, tzinfo=UTC)
    snap = make_snapshot()
    opp = snap["matchups"][0]["away"]
    run = lambda s, now: analyze_league(s, FakeXW(), {}, {}, {}, {}, overrides=None, sims=100, now=now)
    full = run(snap, sunday)["opponent"]
    best, scrub = _bench_best_rb(snap, opp)
    benched = run(snap, sunday)["opponent"]
    assert benched["lineup"] == "set" and full["lineup"] == "set"
    drop = full["mu"] - benched["mu"]
    assert 0.5 * (best["proj_week"] - scrub["proj_week"]) < drop < 1.5 * (best["proj_week"] - scrub["proj_week"]), (full, benched)
    # midweek the flex is still empty (the demo never fills it), so the optimizer's lineup is the forecast
    mid = run(snap, wednesday)["opponent"]
    assert mid["lineup"] == "projected" and mid["mu"] > benched["mu"]
    # ...unless every starter slot is already filled: a set lineup is a set lineup whatever the day
    _fill_flex(snap, opp)
    mid_full = run(snap, wednesday)["opponent"]
    assert mid_full["lineup"] == "set" and mid_full["mu"] < mid["mu"]
    # fixtures and the demo pass no `now`: nothing changes with the calendar there
    assert run(snap, None)["opponent"]["lineup"] == "set"
