import pytest

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


def test_an_out_for_the_season_body_is_not_a_backup(slots):
    """A QB with no rest-of-season expectation is on the roster but cannot start, so he is not depth."""
    from ff.model.trades import depth
    mine, _ = _rosters()
    healthy_backup = mine + [P(30, "QB2", "QB", 15, tid=1)]
    assert "QB" not in depth(healthy_backup, slots)[1]
    shelved = mine + [P(30, "QB2", "QB", 15, ros=0.0, tid=1)]
    ok, thin = depth(shelved, slots)
    assert ok and "QB" in thin, "an IR'd QB should not hide that I am one injury from an empty slot"


def test_scan_charges_for_shipping_the_last_healthy_qb(slots):
    """thin0 must be judged on healthy bodies too: with a dead QB2 on the bench, trading QB1's backup still costs."""
    from ff.model.trades import depth
    mine, _ = _rosters()
    mine = mine + [P(30, "QB2", "QB", 18, tid=1), P(31, "QB3", "QB", 2, ros=0.0, tid=1)]
    assert "QB" not in depth(mine, slots)[1]
    without_backup = [p for p in mine if p.espn_id != 30]
    assert "QB" in depth(without_backup, slots)[1]


def test_drop_already_offered_removes_a_deal_that_is_already_pending():
    """The same ask, sitting in the rival's inbox with a day left on it, is not a thing to do today."""
    from ff.model.trades import drop_already_offered
    by_id = {1: P(1, "Maye", "QB", 18, tid=1), 2: P(2, "Dart", "QB", 12, tid=1), 3: P(3, "Jameson", "WR", 14, tid=2),
             4: P(4, "Odunze", "WR", 13, tid=3)}
    pending = [{"direction": "outgoing", "give": [1, 2], "get": [3]}]
    cands = [{"give": ["Maye"], "get": ["Jameson"]}, {"give": ["Maye"], "get": ["Odunze"]}]
    kept = drop_already_offered(cands, pending, by_id)
    assert [c["get"] for c in kept] == [["Odunze"]]


def test_drop_already_offered_leaves_incoming_offers_alone():
    from ff.model.trades import drop_already_offered
    by_id = {1: P(1, "Maye", "QB", 18, tid=1), 3: P(3, "Jameson", "WR", 14, tid=2)}
    pending = [{"direction": "incoming", "give": [1], "get": [3]}]
    cands = [{"give": ["Maye"], "get": ["Jameson"]}]
    assert drop_already_offered(cands, pending, by_id) == cands


def test_scan_will_not_call_an_overpay_sendable(slots):
    """Lineup math alone happily ships twice the market value for a fraction of a point per week."""
    mine = [P(1, "QB", "QB", 20, tid=1), P(2, "RB1", "RB", 16, tid=1), P(3, "RB2", "RB", 15, tid=1), P(4, "RB3", "RB", 14, tid=1),
            P(5, "WR1", "WR", 14, tid=1), P(6, "WR2", "WR", 12, tid=1), P(21, "WR3", "WR", 10, tid=1),
            P(7, "TE", "TE", 3, tid=1), P(8, "K", "K", 8, tid=1), P(9, "D", "D/ST", 7, tid=1)]
    theirs = [P(11, "QB", "QB", 20, tid=2), P(12, "RB1", "RB", 8, tid=2), P(13, "RB2", "RB", 6, tid=2),
              P(15, "WR1", "WR", 14, tid=2), P(16, "WR2", "WR", 12, tid=2), P(17, "WR3", "WR", 11, tid=2),
              P(18, "TEgood", "TE", 12, tid=2), P(22, "TE2", "TE", 6, tid=2), P(19, "K", "K", 8, tid=2), P(20, "D", "D/ST", 7, tid=2)]
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    meta = {2: {"name": "Rival", "wins": 0, "losses": 2}}
    # The trade the lineup math loves (my spare RB for their good TE) is a 2:1 overpay at market.
    values = {str(i): {"redraft_value": 6000} for i in (2, 3, 4)} | {"18": {"redraft_value": 3000}}
    out = scan(1, {1: mine, 2: theirs}, slots, repl, meta, values)
    overpays = [c for c in out if "TEgood" in c["get"] and c["market_ratio"] is not None and c["market_ratio"] < 0.8]
    assert overpays, "expected the overpay candidate to survive the prefilter so the floor has something to judge"
    for c in overpays:
        assert not c["sendable"]
        assert any("market says I give more" in w for w in c["why"])


def test_scan_still_sends_a_fair_deal(slots):
    mine = [P(1, "QB", "QB", 20, tid=1), P(2, "RB1", "RB", 16, tid=1), P(3, "RB2", "RB", 15, tid=1), P(4, "RB3", "RB", 14, tid=1),
            P(5, "WR1", "WR", 14, tid=1), P(6, "WR2", "WR", 12, tid=1), P(21, "WR3", "WR", 10, tid=1),
            P(7, "TE", "TE", 3, tid=1), P(8, "K", "K", 8, tid=1), P(9, "D", "D/ST", 7, tid=1)]
    theirs = [P(11, "QB", "QB", 20, tid=2), P(12, "RB1", "RB", 8, tid=2), P(13, "RB2", "RB", 6, tid=2),
              P(15, "WR1", "WR", 14, tid=2), P(16, "WR2", "WR", 12, tid=2), P(17, "WR3", "WR", 11, tid=2),
              P(18, "TEgood", "TE", 12, tid=2), P(22, "TE2", "TE", 6, tid=2), P(19, "K", "K", 8, tid=2), P(20, "D", "D/ST", 7, tid=2)]
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    meta = {2: {"name": "Rival", "wins": 0, "losses": 2}}
    values = {str(i): {"redraft_value": 5000} for i in (2, 3, 4, 18)}
    out = scan(1, {1: mine, 2: theirs}, slots, repl, meta, values)
    assert any(c["sendable"] for c in out if "TEgood" in c["get"])


def _out(p, weeks_out, weeks_remaining=12, status="OUT"):
    p.mu_ros_active = p.mu_ros
    p.weeks_out = min(weeks_out, weeks_remaining)
    p.avail_ros = (weeks_remaining - p.weeks_out) / weeks_remaining
    p.mu_ros = round(p.mu_ros_active * p.avail_ros, 2)
    p.sources = {"espn_status": status}
    return p


def test_trade_math_sees_the_injury(slots):
    """Identical per-game value; one is out for the season, one misses a game. The lineup math has to tell them apart."""
    from ff.model.trades import lineup_strength
    healthy, _ = lineup_strength(_rosters()[0], slots)
    one_week = [_out(p, 1) if p.name == "RB1" else p for p in _rosters()[0]]
    season = [_out(p, 12) if p.name == "RB1" else p for p in _rosters()[0]]
    assert healthy > lineup_strength(one_week, slots)[0] > lineup_strength(season, slots)[0]
    assert lineup_strength(one_week, slots)[0] == pytest.approx(healthy - 0.95 * 16 / 12, abs=0.05)


def test_scan_offers_a_hurt_starter_at_his_discounted_market_value(slots):
    """FantasyCalc still prices him healthy. Judged raw, the market floor calls every sell an overpay by me; judged at
    his availability the deal is sendable, and the caveat rides on the row for Claude to rule on."""
    mine, theirs = _rosters()
    mine = [_out(p, 4) if p.name == "RB1" else p for p in mine]          # 16/g, out 4 of 12
    theirs = [P(22, "TE2", "TE", 9, tid=2) if p.name == "TE2" else p for p in theirs]
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    # my healthy RBs are priced out of the ask (the scan keeps one package per rival `get`, and a healthy RB for the TE
    # would win that slot), so the hurt one is the package on the table
    values = {"2": {"redraft_value": 4000}, "3": {"redraft_value": 8000}, "4": {"redraft_value": 8000}, "18": {"redraft_value": 3000}}
    out = scan(1, {1: mine, 2: theirs}, slots, repl, {2: {"name": "Rival", "wins": 0, "losses": 2}}, values)
    sells = [c for c in out if c["give"] == ["RB1"] and c["get"] == ["TEgood"]]
    assert sells, [(c["give"], c["get"]) for c in out]
    c = sells[0]
    assert c["sendable"] and c["market_give"] == 4000 and c["market_give_eff"] == pytest.approx(4000 * 8 / 12, abs=1)
    assert any(w.startswith("market still prices RB1 healthy") for w in c["why"])
    # control: the same package with a healthy RB1 is the overpay the floor exists for
    healthy = scan(1, {1: _rosters()[0], 2: theirs}, slots, repl, {2: {"name": "Rival", "wins": 0, "losses": 2}}, values)
    ctl = [c for c in healthy if c["give"] == ["RB1"] and c["get"] == ["TEgood"]]
    assert not ctl or not ctl[0]["sendable"]


def test_scan_never_offers_a_season_ender(slots):
    mine, theirs = _rosters()
    mine = [_out(p, 12) if p.name == "RB1" else p for p in mine]
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    out = scan(1, {1: mine, 2: theirs}, slots, repl, {2: {"name": "Rival", "wins": 0, "losses": 2}}, values={})
    assert out and all("RB1" not in c["give"] for c in out)


def test_evaluate_discounts_my_hurt_player_too(slots):
    """A rival offering to take my hurt RB off my hands is not a lowball just because the market has not caught up."""
    mine, theirs = _rosters()
    mine = [_out(p, 4) if p.name == "RB1" else p for p in mine]
    by_id = {p.espn_id: p for p in mine + theirs}
    repl = {"QB": 14, "RB": 7, "WR": 8, "TE": 5, "K": 6, "D/ST": 5}
    out = evaluate(1, 2, [by_id[2]], [by_id[18]], {1: mine, 2: theirs}, slots, repl,
                   values={"2": {"redraft_value": 4000}, "18": {"redraft_value": 3000}})
    assert out["market_give"] == 4000 and out["market_give_eff"] < 3000 and out["verdict"] == "accept"
    assert any("market still prices RB1 healthy" in w for w in out["why"])
