from ff.model.trades import scan
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
