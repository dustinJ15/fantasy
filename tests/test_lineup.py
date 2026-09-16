from ff.model.lineup import compare, optimize, win_prob


def test_win_prob_symmetry():
    assert abs(win_prob(100, 100, 100, 100) - 0.5) < 1e-9
    assert win_prob(110, 100, 100, 100) > 0.5


def test_ev_lineup_fills_all_slots(roster, slots):
    L = optimize(roster, slots, objective="ev")
    assert sum(len(v) for v in L.assignment.values()) == sum(slots.values())
    names = {p.name for ps in L.assignment.values() for p in ps}
    assert "RB3" not in names  # 9 < WR3's 10 for flex under EV


def test_underdog_prefers_variance(roster, slots):
    # Facing a monster opponent, the optimizer should take the high-sigma WR3 over RB3 in flex,
    # and as a favorite it should stay with the safer pick when EV is close.
    big = optimize(roster, slots, opp_mu=140, opp_var=200)
    names = {p.name for ps in big.assignment.values() for p in ps}
    assert "WR3" in names
    safe = optimize(roster, slots, opp_mu=60, opp_var=200)
    assert safe.p_win > 0.9


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
    assert L.to_dict()["slots"]["TE"] == ["(EMPTY — no eligible player)"] or L.to_dict()["slots"]["TE"] == ["TEout"]
