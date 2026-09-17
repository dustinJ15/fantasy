from ff.model.trades import evaluate, scan
from tests.conftest import P


def test_scan_finds_need_matching_trade(slots):
    # I have 3 good RBs and a bad TE; rival has a great TE and weak RBs.
    mine = [P(1, "QB", "QB", 20, tid=1), P(2, "RB1", "RB", 16, tid=1), P(3, "RB2", "RB", 15, tid=1), P(4, "RB3", "RB", 14, tid=1),
            P(5, "WR1", "WR", 14, tid=1), P(6, "WR2", "WR", 12, tid=1), P(21, "WR3", "WR", 10, tid=1), P(7, "TE", "TE", 3, tid=1), P(8, "K", "K", 8, tid=1), P(9, "D", "D/ST", 7, tid=1)]
    theirs = [P(11, "QB", "QB", 20, tid=2), P(12, "RB1", "RB", 8, tid=2), P(13, "RB2", "RB", 6, tid=2),
              P(15, "WR1", "WR", 14, tid=2), P(16, "WR2", "WR", 12, tid=2), P(17, "WR3", "WR", 11, tid=2), P(18, "TEgood", "TE", 12, tid=2), P(22, "TE2", "TE", 6, tid=2), P(19, "K", "K", 8, tid=2), P(20, "D", "D/ST", 7, tid=2)]
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    out = scan(1, {1: mine, 2: theirs}, slots, repl, {2: {"name": "Rival", "wins": 0, "losses": 2}}, values={})
    assert out, "expected at least one candidate"
    top = out[0]
    assert "TEgood" in top["get"] and any(g.startswith("RB") for g in top["give"])
    assert top["my_delta_ppw"] > 0 and top["their_delta_ppw"] > -1.5


def test_scan_prefers_rival_gain_and_penalizes_two_for_one_lowball(slots):
    from tests.conftest import P
    mine = [P(1, "QB", "QB", 20, tid=1), P(2, "RB1", "RB", 16, tid=1), P(3, "RB2", "RB", 15, tid=1), P(4, "RB3", "RB", 14, tid=1),
            P(5, "WR1", "WR", 14, tid=1), P(6, "WR2", "WR", 12, tid=1), P(21, "WR3", "WR", 10, tid=1), P(7, "TE", "TE", 3, tid=1), P(8, "K", "K", 8, tid=1), P(9, "D", "D/ST", 7, tid=1)]
    theirs = [P(11, "QB", "QB", 20, tid=2), P(12, "RB1", "RB", 8, tid=2), P(13, "RB2", "RB", 6, tid=2),
              P(15, "WR1", "WR", 14, tid=2), P(16, "WR2", "WR", 12, tid=2), P(17, "WR3", "WR", 11, tid=2), P(18, "TEgood", "TE", 12, tid=2), P(22, "TE2", "TE", 6, tid=2), P(19, "K", "K", 8, tid=2), P(20, "D", "D/ST", 7, tid=2)]
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    # market values: their TE is a star; my RBs are mid. Asking for the star with two mids must be filtered (>1.2x).
    values = {"18": {"redraft_value": 5000}, "2": {"redraft_value": 2000}, "3": {"redraft_value": 1900}, "4": {"redraft_value": 1800}}
    out = scan(1, {1: mine, 2: theirs}, slots, repl, {2: {"name": "Rival", "wins": 0, "losses": 2}}, values=values)
    assert all(not ("TEgood" in c["get"] and len(c["give"]) == 2 and c["market_get"] > c["market_give"] * 1.2) for c in out)
    # ranking: candidates are sorted by score, which weights the rival's gain first
    assert out == sorted(out, key=lambda c: -c["score"])
    assert all("motivated" not in w for c in out for w in c["why"])  # 0-2 is too early to call a rival desperate


def _rosters():
    mine = [P(1, "QB", "QB", 20, tid=1), P(2, "RB1", "RB", 16, tid=1), P(3, "RB2", "RB", 15, tid=1), P(4, "RB3", "RB", 14, tid=1),
            P(5, "WR1", "WR", 14, tid=1), P(6, "WR2", "WR", 12, tid=1), P(21, "WR3", "WR", 10, tid=1), P(7, "TE", "TE", 3, tid=1), P(8, "K", "K", 8, tid=1), P(9, "D", "D/ST", 7, tid=1)]
    theirs = [P(11, "QB", "QB", 20, tid=2), P(12, "RB1", "RB", 8, tid=2), P(13, "RB2", "RB", 6, tid=2),
              P(15, "WR1", "WR", 14, tid=2), P(16, "WR2", "WR", 12, tid=2), P(17, "WR3", "WR", 11, tid=2), P(18, "TEgood", "TE", 12, tid=2), P(22, "TE2", "TE", 6, tid=2), P(19, "K", "K", 8, tid=2), P(20, "D", "D/ST", 7, tid=2)]
    return mine, theirs


def test_evaluate_accepts_offer_that_fixes_my_hole(slots):
    mine, theirs = _rosters()
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    by_id = {p.espn_id: p for p in mine + theirs}
    # they offer their star TE for my third RB: big lineup gain for me, market roughly even
    out = evaluate(1, 2, [by_id[4]], [by_id[18]], {1: mine, 2: theirs}, slots, repl, values={"4": {"redraft_value": 2000}, "18": {"redraft_value": 2100}})
    assert out["verdict"] == "accept" and out["my_delta_ppw"] > 0.75 and "fills my TE hole" in out["why"]


def test_evaluate_declines_lowball(slots):
    mine, theirs = _rosters()
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    by_id = {p.espn_id: p for p in mine + theirs}
    # they want my RB1 for their backup TE: hurts my lineup and the market gap is huge
    out = evaluate(1, 2, [by_id[2]], [by_id[22]], {1: mine, 2: theirs}, slots, repl, values={"2": {"redraft_value": 5000}, "22": {"redraft_value": 500}})
    assert out["verdict"] == "decline" and out["my_delta_ppw"] < 0
    assert any(w.startswith("market says I give more") for w in out["why"])


def test_evaluate_counter_on_close_call(slots):
    mine, theirs = _rosters()
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    by_id = {p.espn_id: p for p in mine + theirs}
    # WR3 for WR3: nothing moves for either lineup
    out = evaluate(1, 2, [by_id[21]], [by_id[17]], {1: mine, 2: theirs}, slots, repl, values={})
    assert out["verdict"] == "counter" and abs(out["my_delta_ppw"]) < 0.75


def test_hole_means_below_replacement_not_merely_close(slots):
    """A 1-QB league's replacement QB is nearly a starter, so 'close to replacement' is not a hole."""
    from ff.model.trades import needs
    mine, _ = _rosters()
    repl = {"QB": 19.8, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}  # QB1 (20.0) sits just above replacement
    n = needs(mine, slots, repl)
    assert not n["QB"]["hole"]
    assert n["TE"]["hole"]  # TE starter is 3.0 against a replacement of 5.0: a real hole


def test_scan_never_leaves_a_slot_unfillable(slots):
    mine, theirs = _rosters()
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    out = scan(1, {1: mine, 2: theirs}, slots, repl, {2: {"name": "Rival", "wins": 0, "losses": 2}}, values={})
    for c in out:
        assert not ("QB" in c["give"] and "QB" not in c["get"]), f"trades away the only QB: {c}"


def test_depth_flags_thin_positions_and_unfillable_slots(slots):
    from ff.model.trades import depth
    mine, _ = _rosters()
    ok, thin = depth(mine, slots)
    assert ok and "TE" in thin and "QB" in thin  # one of each: startable, but no backup
    assert "RB" not in thin  # three RBs, and the flex can cover anyway
    assert not depth([p for p in mine if p.pos != "QB"], slots)[0]


def test_scan_flags_and_penalizes_a_trade_that_costs_my_last_backup(slots):
    """Shipping the spare QB is allowed, but it has to say so and carry a score penalty.

    A backup QB is worth nothing in my own optimal lineup, so such a package only ever clears the gain filter when the
    rival is the one starving at QB — which is exactly the situation where it is tempting and worth a warning.
    """
    mine, theirs = _rosters()
    mine = mine + [P(30, "QB2", "QB", 18, tid=1)]        # a backup to lose
    theirs = [p for p in theirs if p.pos != "QB"] + [P(31, "QBbad", "QB", 4, tid=2)]  # rival is starving at QB
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    out = scan(1, {1: mine, 2: theirs}, slots, repl, {2: {"name": "Rival", "wins": 0, "losses": 2}}, values={})
    shipped_backup = [c for c in out if "QB2" in c["give"] and not any(g == "QB" for g in c["get"])]
    assert shipped_backup, "expected at least one package that moves the spare QB"
    for c in shipped_backup:
        assert "leaves me no backup QB" in c["why"]
        assert c["score"] < round(c["their_delta_ppw"] + 0.5 * min(c["my_delta_ppw"], 3), 2)


def test_evaluate_declines_an_offer_for_my_only_qb(slots):
    mine, theirs = _rosters()
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    by_id = {p.espn_id: p for p in mine + theirs}
    star = P(99, "RBstar", "RB", 30, tid=2)
    theirs = theirs + [star]
    # a genuinely juicy RB for my only QB: still a decline, because the QB slot goes empty
    out = evaluate(1, 2, [by_id[1]], [star], {1: mine, 2: theirs}, slots, repl, values={})
    assert out["verdict"] == "decline"
    assert "leaves me unable to fill a starting slot" in out["why"]
