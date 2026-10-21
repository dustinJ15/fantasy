"""The seams B12 cut into `report.todos`: the ledger is `ff.ledger`, every row kind has its own builder, and `todos`
is only the order over them. If the pieces fold back into one pass, this is the test that notices."""
import copy

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
