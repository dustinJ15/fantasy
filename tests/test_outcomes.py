"""The offer outcome log (rulings.record_outcomes / history), the fallback on a trade row, the counter on an offer."""
from datetime import date

from ff.model.trades import evaluate, scan
from ff.rulings import history, load_outcomes, record_outcomes
from tests.conftest import P


def _packet(outgoing, roster_names=("Keeper",), error=None):
    return {"leagues": [{"name": "L1", "outgoing_trades": list(outgoing), "pending_trades_error": error,
                         "roster": [{"name": n} for n in roster_names]}]}


def offer(oid, give, get, rid=4, expires="2026-10-09T12:00"):
    return {"id": oid, "rival": "Hawk Tua", "rival_team_id": rid, "give": list(give), "get": list(get), "expires_iso": expires}


def test_an_offer_is_opened_when_seen_and_closed_by_what_happened(tmp_path):
    path = tmp_path / "offer_outcomes.json"
    d1, d2 = date(2026, 10, 7), date(2026, 10, 8)
    assert record_outcomes(_packet([offer("a", ["Montgomery"], ["Dak"]), offer("b", ["Coker"], ["Warren"], rid=5)]), path, d1) == ["L1|a: opened", "L1|b: opened"]
    # next morning: 'a' is gone and Dak is on my roster (accepted); 'b' is gone, nothing moved, not yet expired (declined)
    events = record_outcomes(_packet([], roster_names=("Dak", "Coker")), path, d2)
    assert sorted(events) == ["L1|a: accepted", "L1|b: declined"]
    outs = load_outcomes(path)
    assert outs["L1|a"]["status"] == "accepted" and outs["L1|b"]["closed"] == "2026-10-08"


def test_an_offer_past_its_expiry_closes_as_expired_and_an_unreadable_list_closes_nothing(tmp_path):
    path = tmp_path / "o.json"
    record_outcomes(_packet([offer("c", ["X"], ["Y"], expires="2026-10-08T12:00")]), path, date(2026, 10, 7))
    assert record_outcomes(_packet([], error="ESPN said no"), path, date(2026, 10, 10)) == []
    assert record_outcomes(_packet([]), path, date(2026, 10, 10)) == ["L1|c: expired"]
    assert record_outcomes(_packet([]), path, date(2026, 10, 11)) == []  # closed once


def test_history_gives_a_prior_after_two_answers_and_flags_a_fresh_no():
    outs = {"L1|1": {"league": "L1", "rival_team_id": 4, "status": "declined", "closed": "2026-10-06"},
            "L1|2": {"league": "L1", "rival_team_id": 4, "status": "accepted", "closed": "2026-09-20"},
            "L1|3": {"league": "L1", "rival_team_id": 5, "status": "expired", "closed": "2026-09-01"},
            "L2|9": {"league": "L2", "rival_team_id": 4, "status": "declined", "closed": "2026-10-06"}}
    h = history(outs, "L1", date(2026, 10, 7))
    assert h[4] == {"n": 2, "recent_decline": True, "prior": 0.5}
    assert h[5] == {"n": 1, "recent_decline": False, "prior": None}
    assert 9 not in h and "L2" not in str(h)


def _rosters():
    mine = [P(1, "QB", "QB", 20, tid=1), P(2, "RB1", "RB", 16, tid=1), P(3, "RB2", "RB", 15, tid=1), P(4, "RB3", "RB", 14, tid=1),
            P(5, "WR1", "WR", 14, tid=1), P(6, "WR2", "WR", 12, tid=1), P(21, "WR3", "WR", 10, tid=1), P(7, "TE", "TE", 3, tid=1), P(8, "K", "K", 8, tid=1), P(9, "D", "D/ST", 7, tid=1)]
    theirs = [P(11, "QB", "QB", 20, tid=2), P(12, "RB1", "RB", 8, tid=2), P(13, "RB2", "RB", 6, tid=2),
              P(15, "WR1", "WR", 14, tid=2), P(16, "WR2", "WR", 12, tid=2), P(17, "WR3", "WR", 11, tid=2), P(18, "TEgood", "TE", 12, tid=2), P(22, "TE2", "TE", 6, tid=2), P(19, "K", "K", 8, tid=2), P(20, "D", "D/ST", 7, tid=2)]
    return mine, theirs


REPL = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}


def test_a_fresh_no_from_the_rival_lowers_every_package_to_him(slots):
    mine, theirs = _rosters()
    meta = {2: {"name": "Rival", "wins": 2, "losses": 2}}
    cold = scan(1, {1: mine, 2: theirs}, slots, REPL, meta, values={})
    warm = scan(1, {1: mine, 2: theirs}, slots, REPL, meta, values={}, history={2: {"recent_decline": True, "prior": None}})
    by = {tuple(c["get"]): c for c in warm}
    for c in cold:
        w = by.get(tuple(c["get"]))
        assert w is None or w["p_accept"] < c["p_accept"]
        if w:
            assert any("turned one down" in r for r in w["accept_why"])


def test_the_row_carries_a_fallback_package_for_the_same_ask(slots):
    """Two packages for his TE: the one that gains me more leads, the one he is likelier to take is the fallback."""
    mine, theirs = _rosters()
    values = {"2": {"redraft_value": 3000}, "3": {"redraft_value": 2800}, "4": {"redraft_value": 2200}, "18": {"redraft_value": 2500}}
    out = scan(1, {1: mine, 2: theirs}, slots, REPL, {2: {"name": "Rival", "wins": 2, "losses": 2}}, values)
    rows = [c for c in out if c["get"] == ["TEgood"]]
    assert rows and rows[0].get("fallback"), rows
    fb = rows[0]["fallback"]
    assert fb["give"] != rows[0]["give"] and fb["p_accept"] > rows[0]["p_accept"] and fb["text"].startswith("if he says no, offer ")


def test_a_counter_names_the_one_swap_that_makes_it_a_yes(slots):
    """He offers his good TE for my RB1 at a price that is a lowball to me; the counter swaps in my RB3, fair both ways."""
    mine, theirs = _rosters()
    by_id = {p.espn_id: p for p in mine + theirs}
    values = {"2": {"redraft_value": 3500}, "3": {"redraft_value": 3000}, "4": {"redraft_value": 2600}, "18": {"redraft_value": 2500}}
    out = evaluate(1, 2, [by_id[2]], [by_id[18]], {1: mine, 2: theirs}, slots, REPL, values)
    assert out["verdict"] == "counter"
    assert out["counter"] and out["counter"]["get"] == ["TEgood"] and out["counter"]["give"] in (["RB3"], ["RB2"])
    assert out["counter"]["my_delta_ppw"] >= 0.75 and out["counter"]["fair_his"] >= 0.9
    accepted = evaluate(1, 2, [by_id[4]], [by_id[18]], {1: mine, 2: theirs}, slots, REPL, values)
    assert accepted["verdict"] == "accept" and accepted["counter"] is None
