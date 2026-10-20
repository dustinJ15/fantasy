from ff.model.lineup import EMPTY_SLOT, compare, optimize, win_prob


def test_win_prob_symmetry():
    assert abs(win_prob(100, 100, 100, 100) - 0.5) < 1e-9
    assert win_prob(110, 100, 100, 100) > 0.5


def test_ev_lineup_fills_all_slots(roster, slots):
    L = optimize(roster, slots, objective="ev")
    assert sum(len(v) for v in L.assignment.values()) == sum(slots.values())
    names = {p.name for ps in L.assignment.values() for p in ps}
    assert "RB3" not in names  # 9 < WR3's 10 for flex under EV


def _flex_toss_up(wr3_mu: float, wr3_sd: float = 9):
    """RB3 (9.0 ± 4) against a high-variance WR3 for the flex: the P(win) search flips to the WR against a strong
    opponent, and how much P(win) that buys depends on how far behind on points the WR is."""
    from tests.conftest import P
    return [
        P(1, "QB1", "QB", 20, 6), P(2, "RB1", "RB", 16, 6), P(3, "RB2", "RB", 12, 5), P(4, "RB3", "RB", 9.0, 4),
        P(5, "WR1", "WR", 15, 6), P(6, "WR2", "WR", 11, 5), P(7, "WR3", "WR", wr3_mu, wr3_sd),
        P(8, "TE1", "TE", 8, 4), P(9, "K1", "K", 8, 3), P(10, "DST1", "D/ST", 7, 4),
    ]


def test_underdog_prefers_variance(slots):
    """Facing a monster opponent, the optimizer takes the high-sigma WR3 over RB3 in the flex even though RB3 projects
    for more points; as a favorite it stays with the safer, higher-points RB3.

    The WR must have the *lower* EV: the old fixture gave him 10 to RB3's 9, so the EV lineup already held him and the
    test passed with variance ignored. A search that scores on points alone (or zero variance) now fails both halves."""
    from ff.model.lineup import MIN_WIN_GAIN
    roster = _flex_toss_up(8.5, wr3_sd=15)
    ev = optimize(roster, slots, objective="ev")
    ev_names = {p.name for ps in ev.assignment.values() for p in ps}
    assert "RB3" in ev_names and "WR3" not in ev_names  # 9.0 > 8.5: the points lineup sits the WR

    big = optimize(roster, slots, opp_mu=140, opp_var=200)
    names = {p.name for ps in big.assignment.values() for p in ps}
    assert "WR3" in names and "RB3" not in names
    assert big.mu < ev.mu  # the swap costs points
    assert big.var > ev.var  # and buys variance
    assert big.win_gain is not None and big.win_gain >= MIN_WIN_GAIN  # ~3.2pp: variance, not the floor, decides
    assert big.p_win > win_prob(ev.mu, ev.var, 140, 200)
    assert {d["name"] for d in compare(ev, big)} == {"RB3", "WR3"}

    safe = optimize(roster, slots, opp_mu=60, opp_var=200)
    safe_names = {p.name for ps in safe.assignment.values() for p in ps}
    assert "RB3" in safe_names and "WR3" not in safe_names
    assert safe.p_win > 0.9 and safe.win_gain == 0.0 and compare(ev, safe) == []


def test_compare_lists_differences(roster, slots):
    a = optimize(roster, slots, objective="ev")
    b = optimize(roster, slots, opp_mu=140, opp_var=200)
    diff = compare(a, b)
    assert isinstance(diff, list)


def test_empty_slot_does_not_break_lineup(roster, slots):
    from tests.conftest import P
    r = [p for p in roster if p.pos != "TE"] + [P(8, "TEout", "TE", 0.0, 0.0, p0=1.0)]
    L = optimize(r, slots, opp_mu=110, opp_var=300)
    assert L.mu > 90 and L.p_win is not None
    assert L.to_dict()["slots"]["TE"] == [EMPTY_SLOT]


def test_small_p_win_gain_keeps_the_ev_lineup(slots):
    """Variance is a guess, so a 0.3pp P(win) gain is not worth benching the higher-points player."""
    roster = _flex_toss_up(8.7)
    ev = optimize(roster, slots, objective="ev")
    assert "RB3" in {p.name for ps in ev.assignment.values() for p in ps}
    win = optimize(roster, slots, opp_mu=157, opp_var=200)
    gain = win.p_win - win_prob(ev.mu, ev.var, 157, 200)
    assert gain < 0.005  # the unconstrained search would still flip the flex here (~0.3pp)
    assert compare(ev, win) == []
    assert win.mu == ev.mu
    assert win.win_gain == 0.0
    assert win.to_dict()["win_gain"] == 0.0


def test_gain_below_the_floor_is_not_enough_either(slots):
    roster = _flex_toss_up(8.7)
    ev = optimize(roster, slots, objective="ev")
    win = optimize(roster, slots, opp_mu=125, opp_var=200)  # ~1.2pp, under MIN_WIN_GAIN
    assert compare(ev, win) == [] and win.win_gain == 0.0


def test_gain_above_the_floor_deviates_and_states_it(slots):
    from ff.model.lineup import MIN_WIN_GAIN
    roster = _flex_toss_up(8.8, wr3_sd=12)
    ev = optimize(roster, slots, objective="ev")
    win = optimize(roster, slots, opp_mu=125, opp_var=200)  # ~2.8pp
    diff = compare(ev, win)
    assert {d["name"] for d in diff} == {"RB3", "WR3"}
    assert win.win_gain is not None and win.win_gain >= MIN_WIN_GAIN
    assert abs(win.win_gain - (win.p_win - win_prob(ev.mu, ev.var, 125, 200))) < 1e-9
    assert win.to_dict()["win_gain"] == round(win.win_gain, 3)


# ---------- B15: a player who scores zero this week never starts ----------

def test_a_bye_or_a_certain_sit_never_starts_and_the_slot_reads_empty(roster, slots):
    """Oct 20: `avail` kept `mu > 0` bodies, so a kicker on IR (mu 8.4, ev 0) started at K, and the per-slot fallback
    seated a bye QB rather than leave the slot open. The lineup then read "Lawrence: QB -> bench, Herbert: bench -> QB"
    for two zeros and the header's P(win) counted both empty slots as filled."""
    from tests.conftest import P
    r = [p for p in roster if p.pos not in ("QB", "K")]
    bye1, bye2 = P(1, "Lawrence", "QB", 20, 6), P(11, "Herbert", "QB", 18, 6)
    bye1.bye = bye2.bye = True
    ir_k = P(9, "Grupe", "K", 8.4, 3, p0=1.0)        # ev 0, mu > 0: the IR kicker
    r += [bye1, bye2, ir_k]
    L = optimize(r, slots, opp_mu=110, opp_var=300)
    d = L.to_dict()
    assert d["slots"]["QB"] == [EMPTY_SLOT] and d["slots"]["K"] == [EMPTY_SLOT]
    assert {"Lawrence", "Herbert", "Grupe"} <= set(d["bench"])
    assert sum(len(v) for v in L.assignment.values()) == sum(slots.values()) - 2
    assert L.mu == sum(p.ev for ps in L.assignment.values() for p in ps)
    ev = optimize(r, slots, objective="ev")
    assert ev.to_dict()["slots"]["QB"] == [EMPTY_SLOT] and ev.to_dict()["slots"]["K"] == [EMPTY_SLOT]


def test_a_near_certain_sit_is_a_zero_too(roster, slots):
    """p_zero 0.99 leaves ev at a hundredth of mu: not a reason to start him over an empty slot the card fills."""
    from tests.conftest import P
    r = [p for p in roster if p.pos != "K"] + [P(9, "Doubtful K", "K", 8.0, 3, p0=0.99)]
    assert optimize(r, slots, objective="ev").to_dict()["slots"]["K"] == [EMPTY_SLOT]


def test_one_empty_seat_in_a_two_seat_slot_prints_one_marker(roster, slots):
    """RB holds two; with one RB left healthy the slot reads the healthy one and one EMPTY marker, not a full slot."""
    from tests.conftest import P
    r = [p for p in roster if p.pos != "RB"] + [P(2, "RB1", "RB", 16, 6)]
    for i, n in ((3, "RB2"), (4, "RB3")):
        q = P(i, n, "RB", 12, 5)
        q.bye = True
        r.append(q)
    d = optimize(r, slots, objective="ev").to_dict()
    assert d["slots"]["RB"] == ["RB1", EMPTY_SLOT] and d["slots"]["RB/WR/TE"] != [EMPTY_SLOT]


# ---------- B18: a swap between two healthy starters under MIN_SWAP_GAIN is noise ----------

def _two_qbs(cur_mu: float, bench_mu: float, roster):
    """The Oct 20 Denver card: Caleb Williams (Thu, 18.7) in the QB slot today, Kyler Murray (Sun, 19.5) on the
    bench. `roster` from conftest sits everyone in slot "" (no current lineup), so this seats the rest where the
    optimizer would put them anyway and the QB slot is the only question."""
    from tests.conftest import P
    r = [p for p in roster if p.pos != "QB"]
    cur = P(1, "Caleb Williams", "QB", cur_mu, 6)
    cur.slot = "QB"
    other = P(11, "Kyler Murray", "QB", bench_mu, 6)
    other.slot = "BE"
    return r + [cur, other]


def test_a_sub_point_swap_between_healthy_starters_keeps_the_current_one(roster, slots):
    from ff.model.lineup import MIN_SWAP_GAIN
    assert 0 < MIN_SWAP_GAIN <= 1.5
    r = _two_qbs(18.7, 19.5, roster)
    L = optimize(r, slots, objective="ev", hold=True)
    assert L.to_dict()["slots"]["QB"] == ["Caleb Williams"]
    assert L.held == [{"name": "Caleb Williams", "slot": "QB", "for": "Kyler Murray", "gain": 0.8}]
    assert L.to_dict()["held"] == L.held
    assert abs(L.mu - (optimize(r, slots, objective="ev").mu - 0.8 * (1 - 0.02))) < 1e-6  # the forgone EV is the hold
    # the same roster against an opponent: the P(win) search returns the held lineup too
    W = optimize(r, slots, opp_mu=110, opp_var=300, hold=True)
    assert W.to_dict()["slots"]["QB"] == ["Caleb Williams"] and W.held == L.held


def test_a_swap_worth_the_floor_or_more_still_happens(roster, slots):
    r = _two_qbs(18.7, 21.0, roster)
    L = optimize(r, slots, objective="ev", hold=True)
    assert L.to_dict()["slots"]["QB"] == ["Kyler Murray"] and L.held == []


def test_without_the_flag_the_search_is_exact(roster, slots):
    """Rest-of-season pricing (trades, the injury rule, the wire) wants the best lineup, not the fewest clicks."""
    r = _two_qbs(18.7, 19.5, roster)
    L = optimize(r, slots, objective="ev")
    assert L.to_dict()["slots"]["QB"] == ["Kyler Murray"] and L.held == []


def test_a_bye_an_out_or_an_empty_seat_is_never_held(roster, slots):
    from tests.conftest import P
    r = _two_qbs(18.7, 19.0, roster)
    cur = next(p for p in r if p.name == "Caleb Williams")
    cur.bye = True
    assert optimize(r, slots, objective="ev", hold=True).to_dict()["slots"]["QB"] == ["Kyler Murray"]
    cur.bye, cur.p_zero = False, 1.0
    assert optimize(r, slots, objective="ev", hold=True).to_dict()["slots"]["QB"] == ["Kyler Murray"]
    # the current K is out and the bench K is 0.3 better than nobody at all: an empty seat is not a hold
    r2 = [p for p in roster if p.pos != "K"] + [P(9, "K out", "K", 8, 3, p0=1.0), P(12, "K bench", "K", 0.3, 3)]
    r2[-2].slot, r2[-1].slot = "K", "BE"
    assert optimize(r2, slots, objective="ev", hold=True).to_dict()["slots"]["K"] == ["K bench"]


def test_a_hold_at_one_slot_does_not_hold_a_real_upgrade_at_another(roster, slots):
    """Two swaps on one card: the sub-point QB swap is held, the three-point flex upgrade is not."""
    from tests.conftest import P
    r = _two_qbs(18.7, 19.5, roster)
    for p in r:
        if p.slot == "":
            p.slot = "BE"
    rb3 = next(p for p in r if p.name == "RB3")
    rb3.slot = "RB/WR/TE"  # 9.0 in the flex today; WR2 (11) takes the flex once a 12-point bench WR takes his WR seat
    r.append(P(13, "WR4", "WR", 12, 5))
    r[-1].slot = "BE"
    L = optimize(r, slots, objective="ev", hold=True)
    d = L.to_dict()
    assert d["slots"]["QB"] == ["Caleb Williams"]
    assert "RB3" in d["bench"] and {"WR4", "WR2"} <= {n for ns in d["slots"].values() for n in ns}
    assert [h["name"] for h in L.held] == ["Caleb Williams"]
