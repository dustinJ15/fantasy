"""The 2026-09-23 review: wrong instructions the live card produced that morning, each pinned here."""
import json
from datetime import UTC, date, datetime

import pytest

from ff import report, rulings
from ff.model.injuries import decide
from ff.model.lineup import optimize
from ff.model.projections import blend
from tests.conftest import P
from tests.test_card import by_id, ids, injury, league, player


# ---------- lineup: no-op swaps ----------

def test_optimizer_keeps_starters_in_the_slots_they_already_hold(slots):
    """Same starters, so no moves: Henderson stays in the flex and Tuten at RB instead of swapping for nothing."""
    ps = [P(1, "QB1", "QB", 20), P(2, "Jeanty", "RB", 18), P(3, "Tuten", "RB", 12), P(4, "Henderson", "RB", 14),
          P(5, "WR1", "WR", 14), P(6, "WR2", "WR", 12), P(7, "TE1", "TE", 9), P(8, "K", "K", 8), P(9, "D", "D/ST", 7)]
    cur = {"QB1": "QB", "Jeanty": "RB", "Tuten": "RB", "Henderson": "RB/WR/TE", "WR1": "WR", "WR2": "WR", "TE1": "TE", "K": "K", "D": "D/ST"}
    for p in ps:
        p.slot = cur[p.name]
    L = optimize(ps, slots, objective="ev")
    assert L.assignment["RB/WR/TE"][0].name == "Henderson" and {p.name for p in L.assignment["RB"]} == {"Jeanty", "Tuten"}
    lg = league(roster=[{**player(p.name, pos=p.pos, slot=p.slot), "mu_ros": p.mu} for p in ps], lineup_win=L.to_dict())
    assert by_id(lg)["lineup"]["moves"] == []


def test_optimizer_still_moves_a_bench_player_in_when_he_is_better(slots):
    ps = [P(1, "QB1", "QB", 20), P(2, "RB1", "RB", 18), P(3, "RB2", "RB", 12), P(4, "RB3", "RB", 14),
          P(5, "WR1", "WR", 14), P(6, "WR2", "WR", 12), P(7, "TE1", "TE", 9), P(8, "K", "K", 8), P(9, "D", "D/ST", 7), P(10, "WR3", "WR", 5)]
    cur = {"QB1": "QB", "RB1": "RB", "RB2": "RB", "WR3": "RB/WR/TE", "WR1": "WR", "WR2": "WR", "TE1": "TE", "K": "K", "D": "D/ST", "RB3": "BE"}
    for p in ps:
        p.slot = cur[p.name]
    L = optimize(ps, slots, objective="ev")
    names = {s: [p.name for p in v] for s, v in L.assignment.items()}
    assert names["RB"] == ["RB1", "RB2"] and names["RB/WR/TE"] == ["RB3"]  # the two RBs stay put, RB3 takes the flex


# ---------- projections ----------

ROW = {"espn_id": 1, "name": "X", "pos": "WR", "team": "KC", "eligible": ["WR"], "slot": "BE", "fantasy_team_id": 1,
       "proj_week": 12.0, "proj_season": 150.0, "bye": False}


def test_a_questionable_on_his_bye_is_not_a_missed_game():
    p = blend({**ROW, "bye": True, "injury_status": "QUESTIONABLE", "proj_week": 0.0}, None, None, 15, None, week=3)
    assert p.weeks_out == 0.3 and p.return_week is None and p.p_zero == 1.0  # the bye still zeroes this week


def test_questionable_is_lighter_early_in_the_week_until_claude_says_otherwise():
    q = {**ROW, "injury_status": "QUESTIONABLE"}
    assert blend(q, None, None, 15, None, weekday=1).p_zero == 0.15   # Tuesday: last week's tag
    assert blend(q, None, None, 15, None, weekday=4).p_zero == 0.30   # Friday: the real one
    assert blend(q, None, None, 15, None).p_zero == 0.30              # no day given: Friday number
    assert blend(q, None, None, 15, {"1": {"p_zero": 0.5}}, weekday=1).p_zero == 0.5


def test_day_to_day_is_a_designation_and_waiver_status_rides_along():
    p = blend({**ROW, "injury_status": "DAY_TO_DAY", "waiver_status": "WAIVERS"}, None, None, 15, None)
    assert p.p_zero == 0.15 and "espn:DAY_TO_DAY" in p.flags and p.sources["waiver_status"] == "WAIVERS"


def test_missing_espn_status_is_none_not_a_list():
    from ff.sources.espn import _status

    class Fake:
        injuryStatus = []
    assert _status(Fake()) is None
    Fake.injuryStatus = "OUT"
    assert _status(Fake()) == "OUT"


# ---------- the roster-spot ledger ----------

def test_an_activation_takes_the_drop_row_with_it_instead_of_spending_it_twice():
    """Daniels comes off IR and Dart is the cut: one click, one drop, not "drop Dart" on two rows."""
    lg = league(roster=[player("Starter WR", slot="WR"), player("Dart", pos="QB", ros=0.8), player("Bench WR", ros=3.0)],
                injuries=[injury("Daniels", "activate", pos="QB", weeks_out=1, return_week=4, fa=None),
                          {**injury("Dart", "drop", pos="QB", weeks_out=1, return_week=4, fa=("Concepcion", 0.0)), "hold_value": 0.0}])
    lg["injuries"][0]["espn_status"] = "QUESTIONABLE"
    rows = by_id(lg)
    assert "injury:dart" not in rows
    text = rows["injury:daniels"]["text"]
    assert text.startswith("move Daniels (QB) off IR, ESPN lists him questionable") and "drop Dart (QB, out ~1 wk" in text
    assert "Concepcion" not in text


def test_an_activation_uses_an_open_spot_before_naming_a_drop():
    lg = league(roster=[player("Starter WR", slot="WR"), player("Bench WR", ros=3.0)],
                injuries=[injury("Daniels", "activate", pos="QB", weeks_out=1, return_week=4, fa=None)], open_spots=1, open_spot_adds=[])
    assert "open bench spot" in by_id(lg)["injury:daniels"]["text"] and "drop" not in by_id(lg)["injury:daniels"]["text"]


def waiver(name, pos="RB", d_week=3.0, d_start=0.0, on_waivers=False):
    return {"name": name, "pos": pos, "team": "GB", "streamer": False, "delta_week": d_week, "week_slot": "RB", "delta_over_starter": d_start,
            "slot": "RB", "bid": 0, "on_waivers": on_waivers}


def test_a_waiver_add_uses_the_open_spot_and_the_open_spot_row_does_not_repeat_him():
    lg = league(waivers=[waiver("Bassett")], open_spots=1, open_spot_adds=[{"name": "Bassett", "pos": "RB", "kind": "upgrade", "why": "+7.7/wk"}])
    rows = ids(lg)
    assert rows.count("waiver:bassett") == 1
    text = by_id(lg)["waiver:bassett"]["text"]
    assert "open bench spot" in text and "drop" not in text


def test_two_pickups_name_two_different_drops():
    lg = league(roster=[player("Starter WR", slot="WR"), player("Bench A", ros=3.0), player("Bench B", ros=5.0)],
                waivers=[waiver("Now Guy", d_week=3.0), waiver("Later Guy", d_week=0.0, d_start=2.0)])
    rows = by_id(lg)
    assert rows["waiver:now-guy"]["text"].endswith("; drop Bench A") and rows["waiver:later-guy"]["text"].endswith("; drop Bench B")


def test_a_player_headed_to_ir_is_never_the_drop_for_a_pickup():
    lg = league(roster=[player("Starter WR", slot="WR"), player("Stash", ros=0.5), player("Bench B", ros=5.0)],
                injuries=[injury("Stash", "ir", weeks_out=15, return_week=None, avail=0.0, fa=("Pickup", 1.2))],
                waivers=[waiver("Now Guy", d_week=3.0)])
    assert by_id(lg)["waiver:now-guy"]["text"].endswith("; drop Bench B")


def test_a_pickup_the_injury_row_already_adds_is_not_a_second_row():
    lg = league(roster=[player("Starter WR", slot="WR"), player("Stash", ros=0.5), player("Bench B", ros=5.0)],
                injuries=[injury("Stash", "ir", weeks_out=15, return_week=None, avail=0.0, fa=("Now Guy", 1.2))],
                waivers=[waiver("Now Guy", d_week=3.0)])
    assert ids(lg).count("waiver:now-guy") == 0 and "then add Now Guy" in by_id(lg)["injury:stash"]["text"]


# ---------- claim vs add ----------

def test_a_player_on_waivers_is_a_claim_with_the_priority_spelled_out():
    lg = league(waivers=[waiver("Bassett", on_waivers=True)], waiver_rank=7, faab_remaining=None)
    assert by_id(lg)["waiver:bassett"]["text"].startswith("claim (waivers, you are priority #7) Bassett (RB)")
    lg = league(waivers=[waiver("Bassett", on_waivers=False)], waiver_rank=7)
    assert by_id(lg)["waiver:bassett"]["text"].startswith("add Bassett (RB)")


# ---------- trade deadline and skipped-trade memory ----------

def test_the_deadline_closes_the_trade_rows():
    lg = league(trades=[], trades_closed=True, trade_deadline_iso="2026-11-18T22:00")
    row = by_id(lg)["deadline"]
    assert "trade deadline passed (2026-11-18)" in row["text"]


def test_the_scan_stops_at_the_deadline(monkeypatch):
    from ff.packet import analyze_league
    from tests.test_packet_synthetic import FakeXW, make_snapshot
    monkeypatch.setattr("ff.packet.fantasycalc.by_espn_id", lambda **kw: {})
    snap = make_snapshot()
    snap["settings"]["trade_deadline_ms"] = 1_000
    blk = analyze_league(snap, FakeXW(), {}, {}, {}, {}, sims=100, now=datetime(2026, 11, 20, tzinfo=UTC))
    assert blk["trades"] == [] and blk["trades_closed"] is True
    snap["settings"]["trade_deadline_ms"] = 4_000_000_000_000
    blk = analyze_league(snap, FakeXW(), {}, {}, {}, {}, sims=100, now=datetime(2026, 11, 20, tzinfo=UTC))
    assert blk["trades_closed"] is False


def test_a_skipped_trade_is_remembered_for_two_weeks(tmp_path):
    path = tmp_path / "skipped_trades.json"
    lg = league(trades=[{"rival": "Them", "give": ["A"], "get": ["Kai"], "my_delta_ppw": 1.0, "their_delta_ppw": 0.5, "why": [], "sendable": True}])
    packet = {"leagues": [lg]}
    reads = {"L1": {"items": {"trade:kai": {"verdict": "skip", "note": "not selling A"}}}}
    assert rulings.record_skips(packet, reads, path, today=date(2026, 9, 23)) == ["L1|Kai"]
    skips = rulings.load_skips(path)
    assert skips["L1|Kai"]["note"] == "not selling A"
    cands = [{"get": ["Kai"], "give": ["A"]}, {"get": ["Other"], "give": ["A"]}]
    assert [c["get"] for c in rulings.drop_recently_skipped(cands, skips, "L1", today=date(2026, 9, 30))] == [["Other"]]
    assert len(rulings.drop_recently_skipped(cands, skips, "L1", today=date(2026, 10, 30))) == 2   # memory expires
    assert len(rulings.drop_recently_skipped(cands, skips, "L2", today=date(2026, 9, 30))) == 2    # per league
    assert rulings.record_skips(packet, {"L1": {"items": {"trade:kai": "do"}}}, path, today=date(2026, 9, 23)) == []


# ---------- pushes: keep asking about a great trade ----------

def big(get="Star", give=("A",), mine=2.5, title=None, **kw):
    t = {"rival": "Them", "give": list(give), "get": [get], "my_delta_ppw": mine, "their_delta_ppw": 0.5, "why": [], "sendable": True,
         "must_try": mine >= 2.0, **kw}
    if title is not None:
        t["my_title_delta"] = title
    return t


def test_the_math_flags_a_big_package_and_the_card_puts_it_first():
    lg = league(trades=[{**big("Meh", mine=1.0), "must_try": False}, big("Star", mine=2.5)])
    rows = ids(lg)
    assert rows.index("trade:star") < rows.index("trade:meh")
    row = by_id(lg)["trade:star"]
    assert row["label"] == "Trade (do this one)" and row["push"] and "first ask" in row["text"] and "skip it with a reason" in row["text"]


def test_a_push_survives_the_three_row_cap():
    trades = [{**big(f"P{i}", give=(f"G{i}",), mine=1.0), "must_try": False} for i in range(3)] + [big("Star", give=("Z",), mine=2.5)]
    assert "trade:star" in ids(league(trades=trades))


def test_claude_can_push_a_row_and_lint_wants_a_reason():
    from tests.test_card import packet
    lg = league(trades=[{**big("Star", mine=1.0), "must_try": False}])
    p = packet(lg)
    assert any("needs a note" in w for w in report.read_lint(p, {"L1": {"items": {"trade:star": "push"}}}))
    assert report.read_lint(p, {"L1": {"items": {"trade:star": {"verdict": "push", "note": "Allen wins leagues"}}}}) == []
    assert any("trade rows only" in w for w in report.read_lint(p, {"L1": {"items": {"lineup": {"verdict": "push", "note": "x"}}}}))


def test_a_push_is_remembered_counted_and_closed_by_sending_or_skipping(tmp_path):
    path = tmp_path / "pushed.json"
    lg = league(trades=[{**big("Star", mine=1.0), "must_try": False}])
    packet = {"leagues": [lg]}
    reads = {"L1": {"items": {"trade:star": {"verdict": "push", "note": "Allen wins leagues"}}}}
    assert rulings.record_pushes(packet, reads, path, today=date(2026, 9, 23)) == ["L1|Star: opened"]
    pushes = rulings.load_pushes(path)
    assert pushes["L1|Star"]["status"] == "open" and pushes["L1|Star"]["note"] == "Allen wins leagues"
    # the next morning the scan produces it again: it comes back marked, day 2, with the reason
    cands = rulings.mark_pushed([{"get": ["Star"], "give": ["A"]}, {"get": ["Other"]}], pushes, "L1", today=date(2026, 9, 24))
    assert cands[0]["pushed"]["days"] == 2 and cands[0]["pushed"]["note"] == "Allen wins leagues" and "pushed" not in cands[1]
    lg2 = league(trades=[{**big("Star", mine=1.0), "must_try": False, "pushed": cands[0]["pushed"]}])
    assert "asked 2 mornings running" in by_id(lg2)["trade:star"]["text"] and "Allen wins leagues" in by_id(lg2)["trade:star"]["text"]
    assert rulings.record_pushes({"leagues": [lg2]}, {}, path, today=date(2026, 9, 24)) == []  # still open, nothing new
    # Dustin sent it: the package is among his pending offers
    lg3 = {**lg2, "outgoing_trades": [{"rival": "Them", "give": ["A"], "get": ["Star"], "hours_left": 20}]}
    assert rulings.record_pushes({"leagues": [lg3]}, {}, path, today=date(2026, 9, 25)) == ["L1|Star: sent"]
    assert rulings.load_pushes(path)["L1|Star"]["status"] == "sent"
    assert "pushed" not in rulings.mark_pushed([{"get": ["Star"]}], rulings.load_pushes(path), "L1")[0]
    # a fresh push, then a skip with a reason closes it
    assert rulings.record_pushes(packet, reads, path, today=date(2026, 9, 26)) == ["L1|Star: opened"]
    ev = rulings.record_rulings(packet, {"L1": {"items": {"trade:star": {"verdict": "skip", "note": "not selling A"}}}},
                                tmp_path / "skips.json", path, today=date(2026, 9, 27))
    assert ev == ["skip L1|Star", "push L1|Star: skipped"]
    assert rulings.load_pushes(path)["L1|Star"]["status"] == "skipped"


def test_a_pushed_row_wears_the_badge_in_the_email(monkeypatch):
    from ff.email_html import render_email
    from tests.test_email_html import _packet
    p = _packet(monkeypatch)
    lg = p["leagues"][0]
    assert lg["trades"], "fixture should offer a trade"
    for t in lg["trades"]:
        t["must_try"] = False
    lg["trades"][0]["pushed"] = {"since": "2026-09-20", "days": 4, "note": "Allen wins leagues", "source": "claude"}
    html = render_email(p, {})
    assert "TRADE (DO IT)" in html and "asked 4 mornings running" in html and "Allen wins leagues" in html


def test_only_one_package_is_pushed_at_a_time_and_alternatives_are_not_both_pushed():
    trades = [big("Star", give=("A",), mine=2.5), big("Other", give=("A",), mine=2.2)]
    rows = by_id(league(trades=trades))
    assert rows["trade:star"]["push"] and not rows["trade:other"]["push"]
