"""The seams B12 cut into `report.todos`: the ledger is `ff.ledger`, every row kind has its own builder, and `todos`
is only the order over them. If the pieces fold back into one pass, this is the test that notices."""
import copy

import pytest

from ff import ledger, report
from tests.test_card import injury, league, player, trade
from tests.test_review_fixes import waiver


def _rich_league():
    """One league that puts a row of every kind on the card: an offer, the lineup, an IR move, a drop, a hold, a hurt player shipped in a trade, a waiver who starts, a waiver who upgrades, a streamer, an open offer and
    two packages, one of them pushed by the math."""
    stream = {**waiver("Backup K", pos="K", d_week=2.0, d_start=2.0), "streamer": True, "slot": "K"}
    offer = {**trade(["Their RB"], ["Bench WR"], mine=-1.0, theirs=2.0), "verdict": "decline", "hours_left": 20.0}
    return league(
        roster=[player("Starter WR", slot="WR"), player("Bench WR", ros=3.0), player("Bench B", ros=5.0), player("Bench C", ros=6.0),
                player("Hurt RB", pos="RB", ros=8.0), player("Sell RB", pos="RB", ros=9.0)],
        open_spots=1,
        injuries=[injury("Hurt RB", "ir", weeks_out=15, return_week=None, avail=0.0, fa=("Pickup", 1.2)),
                  injury("Done Guy", "drop", weeks_out=15, return_week=None, avail=0.0, fa=None),
                  injury("Ankle Guy", "hold"),
                  injury("Sell RB", "trade", trades=[{"rival": "Them", "get": ["Star"]}])],
        waivers=[waiver("Now Guy", d_week=3.0), waiver("Later Guy", d_week=0.5, d_start=1.5), stream],
        incoming_trades=[offer],
        outgoing_trades=[{"rival": "Them", "give": ["Sell RB"], "get": ["Star"], "hours_left": 30.0}],
        trades=[{**trade(["Kai"], ["Bench B"], mine=2.5, theirs=0.3), "must_try": True}, trade(["Star"], ["Sell RB"])],
    )


def test_the_ledger_is_its_own_module_and_report_only_re_exports_it():
    assert report._Spots is ledger.Spots
    assert report._drop_order is ledger.drop_order and report._drop_note is ledger.drop_note
    assert report._drop_cost is ledger.drop_cost and report._drop_candidate is ledger.drop_candidate


def test_todos_is_the_order_over_the_builders_and_one_shared_ledger():
    lg = _rich_league()
    rows = report.todos(copy.deepcopy(lg))
    kinds = [x["kind"] for x in rows]
    assert {"trade_in", "lineup", "injury", "waiver", "waiver_up", "stream", "sent", "trade", "hold"} <= set(kinds)

    # The same rows, built one kind at a time over one ledger, in the order Dustin clicks through ESPN.
    lg = copy.deepcopy(lg)
    spots = report._ledger(lg)
    assert isinstance(spots, ledger.Spots) and spots.reserved == {"Hurt RB", "Sell RB"} and spots.open == 1
    inj = report._injury_items(lg, spots)
    added = set()
    manual = report._offer_items(lg)
    manual += [i for i in inj if i["verdict"] in ("ir", "activate")]
    wv = report._waiver_items(lg, spots, added)
    manual += wv
    manual += report._cover_items(lg, spots, added)
    manual += report._stream_items(lg, spots, added)
    left = [i for i in inj if i["verdict"] == "drop" and i["name"] not in spots.dropped]
    manual += left
    report._depth_adds(lg, [i for i in inj if i["verdict"] == "ir"] + left, spots, added)
    manual += report._open_spot_items(lg, spots, added)
    manual += [report._lineup_item(lg, manual)]
    manual += report._sent_items(lg)
    manual += report._trade_items(lg, spots, report._pushed(lg))
    manual += [i for i in inj if i["verdict"] == "trade"]
    manual += [i for i in inj if i["kind"] == "hold"]
    assert rows == report._unique_ids(manual)

    # The ledger is what the builders shared: the first pickup took the open spot, the second the spot the IR move
    # frees, the Drop row nobody took counted its own drop, and the pushed package is the only one still flagged for
    # the rulings memory.
    assert spots.open == 0 and spots.freed == [] and spots.dropped == ["Done Guy"]
    assert "into the spot Hurt RB's IR move frees" in report.detail_line(next(x for x in rows if x["id"] == "waiver:later-guy"))
    assert [x["id"] for x in rows if x["kind"] == "trade"] == ["trade:kai", "trade:star"]
    assert [t.get("must_try", False) for t in lg["trades"]] == [True, False]


def claim(add="Claimed RB", drop="Bench A", bid=12, pos="RB"):
    """One entry of the league block's `pending_claims` (B20): a claim Dustin placed in the app."""
    return {"id": "c1", "add": add, "add_id": 9, "add_pos": pos, "drop": drop, "drop_id": 2, "bid": bid,
            "lands": "Wed 1:00 AM", "lands_ts": 1792566000000, "status": "PENDING"}


def test_a_claim_i_already_have_in_spends_its_drop_and_holds_its_add_before_any_row_prints():
    """B20: the 2026-10-20 card spent Grupe on a new claim when the claim Dustin had placed already dropped him. The
    ledger starts with the claim's drop spent and the add counted, so the next row that needs a spot names the next
    cheapest body, and a claim with no drop takes the open spot it will land in."""
    lg = league(roster=[player("Starter WR", slot="WR"), player("Bench A", ros=3.0), player("Bench B", ros=5.0)],
                settings={"lineup_slots": {"WR": 2}, "position_limits": {"RB": 6, "WR": 6}}, pending_claims=[claim()])
    spots = ledger.Spots(lg, 0, set())
    assert spots.dropped == ["Bench A"] and spots.counts["RB"] == 1 and spots.counts["WR"] == 2
    assert spots.take(adding="TE") == ("Bench B", "; drop Bench B")
    # the same claim bidding into the one open spot: the spot is his, the next add names the cheapest drop
    lg2 = copy.deepcopy(lg)
    lg2["pending_claims"] = [claim(drop=None)]
    spots2 = ledger.Spots(lg2, 1, set())
    assert spots2.open == 0 and spots2.dropped == [] and spots2.counts["RB"] == 1
    assert spots2.take(adding="TE")[0] == "Bench A"
    # a league block without the field (an older packet) is the ledger as before
    lg3 = copy.deepcopy(lg)
    del lg3["pending_claims"]
    assert ledger.Spots(lg3, 0, set()).dropped == []


# ---------- the third body at a one-starter position, and a body in an open offer of mine (2026-10-29) ----------

def _qb3_league(**kw):
    """A one-QB roster with three QBs and a WR5: by `mu_ros` alone the 15-a-game QB3 was never the cut."""
    return league(
        roster=[player("QB1", pos="QB", ros=20.0, slot="QB"), player("QB2", pos="QB", ros=17.0), player("QB3", pos="QB", ros=15.0),
                player("Starter WR", slot="WR"), player("WR Five", ros=5.0)],
        lineup_win={"slots": {"QB": ["QB1"], "WR": ["Starter WR"]}, "p_win": 0.6, "mu": 100.0, "sd": 20.0, "bench": []},
        waivers=[waiver("Now Guy", pos="WR", d_week=3.0)], **kw)


def test_a_qb3_in_a_one_qb_league_is_the_cheap_drop_ahead_of_a_wr5():
    lg = _qb3_league()
    assert ledger.depth_share(lg, next(p for p in lg["roster"] if p["name"] == "QB3")) == 0.1
    assert ledger.depth_share(lg, next(p for p in lg["roster"] if p["name"] == "QB2")) == 1.0  # the QB2 is bye and injury cover
    assert ledger.drop_order(lg) == ["QB3", "WR Five", "QB2"]
    row = report.todos(lg)
    text = report.row_line(next(x for x in row if x["id"] == "waiver:now-guy")) if hasattr(report, "row_line") else ""
    item = next(x for x in row if x["id"] == "waiver:now-guy")
    assert "; drop QB3" in item["text"]
    assert "QB3 behind QB1 and QB2, starts only if both are out" in report.detail_line(item)
    assert "trade bait" not in report.detail_line(item), text  # the WR5 was passed over for the QB3's depth, not his market


def test_a_superflex_league_prices_the_qb3_at_his_full_number():
    lg = _qb3_league()
    lg["settings"]["lineup_slots"] = {**lg["settings"]["lineup_slots"], "OP": 1}
    assert ledger.depth_share(lg, next(p for p in lg["roster"] if p["name"] == "QB3")) == 1.0
    assert ledger.drop_order(lg) == ["WR Five", "QB3", "QB2"]


def _offer_league(**offer):
    return league(
        roster=[player("Starter WR", slot="WR"), player("Bench WR", ros=3.0), player("Bench B", ros=3.5)],
        waivers=[waiver("Now Guy", pos="WR", d_week=3.0)],
        outgoing_trades=[{"rival": "Them", "give": ["Bench WR"], "get": ["Star"], "hours_left": 20.0, **offer}])


def test_a_body_in_an_open_offer_is_a_drop_whose_click_cancels_the_offer_first():
    """Oct 29: Rodgers sat in a 2-for-2 that was going nowhere and the card would not name him. ESPN refuses the drop
    while the offer is open, so the click is the cancel and then the drop; the Sent row turns into the reminder."""
    lg = _offer_league(my_delta_ppw=0.5, p_accept=0.3)
    held = ledger.offer_hold(lg, "Bench WR")
    assert held is not None and held[1] == pytest.approx(0.15)  # 30% of +0.5/wk forgone by cancelling
    assert ledger.drop_order(lg) == ["Bench WR", "Bench B"]
    rows = {x["id"]: x for x in report.todos(lg)}
    row = rows["waiver:now-guy"]
    assert row["text"].endswith("; cancel your offer to Them, then drop Bench WR") and row["drop"] == "Bench WR"
    detail = report.detail_line(row)
    assert "in your Bench WR for Star offer to Them: cancel it first, ESPN will not drop a player in a pending trade" in detail
    assert "30% to land for +0.5/wk, so cancelling forgoes ~0.1/wk" in detail
    sent = rows["sent:star"]
    assert sent["label"] == "Cancel" and sent["text"] == "cancel your Bench WR for Star offer to Them: the row above drops Bench WR"
    assert "ESPN will not drop a player in a pending trade" in report.detail_line(sent)
    for x in (row, sent):
        assert report.words(x["text"]) <= report.MAX_ROW_WORDS


def test_an_offer_likely_to_land_and_worth_a_lot_keeps_its_body_off_the_drop_list():
    lg = _offer_league(my_delta_ppw=2.0, p_accept=0.6)  # 1.2/wk forgone: Bench WR costs 4.2 against Bench B's 3.5
    assert ledger.drop_order(lg) == ["Bench B", "Bench WR"]
    rows = {x["id"]: x for x in report.todos(lg)}
    assert rows["waiver:now-guy"]["text"].endswith("; drop Bench B") and rows["sent:star"]["label"] == "Already sent"
    assert "60% to land for +2.0/wk" in report.detail_line(rows["sent:star"])


def test_an_unpriced_offer_holds_nothing_and_an_accepted_trade_is_not_an_offer():
    lg = _offer_league()  # a packet from before the offer was priced: the body is a plain drop, the click still cancels
    assert ledger.offer_hold(lg, "Bench WR") == (lg["outgoing_trades"][0], 0.0)
    row = {x["id"]: x for x in report.todos(lg)}["waiver:now-guy"]
    assert "cancel your offer to Them, then drop Bench WR" in row["text"] and "forgoes" not in report.detail_line(row)
    lg = _offer_league(accepted=True, my_delta_ppw=2.0, p_accept=0.9)
    assert ledger.offer_hold(lg, "Bench WR") is None


# ---------- the second upgrade row (2026-10-29) ----------

def _up(name, slot, d_start, mu_ros=None):
    w = {**waiver(name, pos=slot, d_week=0.0, d_start=d_start), "slot": slot, "week_slot": slot}
    if mu_ros is not None:
        w["mu_ros"] = mu_ros
    return w


def test_a_second_upgrade_row_prints_at_another_slot_when_the_spot_is_free():
    lg = league(waivers=[_up("Back A", "RB", 2.0), _up("Wide B", "WR", 1.5), _up("Back C", "RB", 1.2)], open_spots=2)
    rows = [x for x in report.todos(lg) if x["kind"] == "waiver_up"]
    assert [x["id"] for x in rows] == ["waiver:back-a", "waiver:wide-b"]
    assert "if he is gone, Back C (RB, +1.2/wk)" in report.detail_line(rows[0])   # the same-slot body is the first row's fallback
    assert "open bench spot" in report.detail_line(rows[1])


def test_a_second_body_at_the_same_slot_is_the_fallback_not_a_row():
    lg = league(waivers=[_up("Back A", "RB", 2.0), _up("Back C", "RB", 1.8)], open_spots=2)
    rows = [x for x in report.todos(lg) if x["kind"] == "waiver_up"]
    assert [x["id"] for x in rows] == ["waiver:back-a"] and "if he is gone, Back C" in report.detail_line(rows[0])


def test_a_second_upgrade_row_needs_to_out_value_its_drop_by_the_margin():
    roster = [player("Starter WR", slot="WR"), player("Bench WR", ros=6.0), player("Bench B", ros=6.5)]
    lg = league(roster=roster, waivers=[_up("Back A", "RB", 2.0, mu_ros=12.0), _up("Wide B", "WR", 1.5, mu_ros=7.0)])
    rows = [x for x in report.todos(lg) if x["kind"] == "waiver_up"]
    assert [x["id"] for x in rows] == ["waiver:back-a"]   # Wide B at 7.0 over Bench B's 6.5 is not worth the cut
    lg = league(roster=roster, waivers=[_up("Back A", "RB", 2.0, mu_ros=12.0), _up("Wide B", "WR", 1.5, mu_ros=8.0)])
    rows = [x for x in report.todos(lg) if x["kind"] == "waiver_up"]
    assert [x["id"] for x in rows] == ["waiver:back-a", "waiver:wide-b"]
    assert rows[0]["drop"] == "Bench WR" and rows[1]["drop"] == "Bench B" and "; drop Bench B" in rows[1]["text"]
    # with no rest-of-season number on the wire body, only a free spot prints him
    lg = league(roster=roster, waivers=[_up("Back A", "RB", 2.0), _up("Wide B", "WR", 1.5)])
    assert [x["id"] for x in report.todos(lg) if x["kind"] == "waiver_up"] == ["waiver:back-a"]
