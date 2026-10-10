"""The seams B12 cut into `report.todos`: the ledger is `ff.ledger`, every row kind has its own builder, and `todos`
is only the order over them. If the pieces fold back into one pass, this is the test that notices."""
import copy

from ff import ledger, report
from tests.test_card import injury, league, player, trade
from tests.test_review_fixes import waiver


def _rich_league():
    """One league that puts a row of every kind on the card: an offer, the lineup, an IR move with its add, a drop, a
    hold, a hurt player shipped in a trade, a waiver who starts, a waiver who upgrades, a streamer, an open offer and
    two packages, one of them pushed by the math."""
    stream = {**waiver("Backup K", pos="K", d_week=0.0, d_start=2.0), "streamer": True, "slot": "K"}
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
    spots.reserved |= {r["name"] for r in lg["injuries"] if r["verdict"] == "drop" and r.get("add")}
    added = {r["add"]["name"] for r in lg["injuries"] if r.get("add")}
    manual = report._offer_items(lg)
    manual += [i for i in inj if i["verdict"] in ("ir", "activate")]
    wv = report._waiver_items(lg, spots, added)
    manual += wv
    manual += report._stream_items(lg)
    manual += report._cover_items(lg, spots, added)
    manual += [i for i in inj if i["verdict"] == "drop"]
    manual += report._open_spot_items(lg, spots, added)
    manual += [report._lineup_item(lg, [i["pickup"] for i in wv if i.get("pickup")])]
    manual += report._sent_items(lg)
    manual += report._trade_items(lg, spots, report._pushed(lg))
    manual += [i for i in inj if i["verdict"] == "trade"]
    manual += [i for i in inj if i["kind"] == "hold"]
    assert rows == report._unique_ids(manual)

    # The ledger is what the builders shared: the first pickup took the open spot, the second named the cheapest drop,
    # and the pushed package is the only one still flagged for the rulings memory.
    assert spots.open == 0 and spots.dropped == ["Bench WR"]
    assert [x["id"] for x in rows if x["kind"] == "trade"] == ["trade:kai", "trade:star"]
    assert [t.get("must_try", False) for t in lg["trades"]] == [True, False]
