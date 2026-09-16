"""Game clock: locked players stay put, banked points feed the matchup, phase is reported."""
from datetime import UTC, datetime

from ff.model.clock import apply_clock, game_phase, week_state
from ff.model.lineup import optimize
from tests.conftest import P

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)  # Monday morning
LINES = {"SUN": {"kickoff": "2026-09-13T17:00Z", "state": "post"}, "MON": {"kickoff": "2026-09-15T00:15Z", "state": "pre"},
         "LIVE": {"kickoff": "2026-09-14T11:00Z", "state": "in"}}


def test_game_phase():
    assert game_phase(LINES["SUN"], 0.0, NOW) == "post"
    assert game_phase(LINES["MON"], 0.0, NOW) == "pre"
    assert game_phase(LINES["LIVE"], 3.0, NOW) == "in"
    assert game_phase(None, 12.0, NOW) == "post"      # no line but points on the board
    assert game_phase({"kickoff": "2026-09-14T08:00Z"}, 0.0, NOW) == "post"  # stale 'pre' state, >3.5h ago


def test_locked_players_pinned_and_bench_locked_excluded(slots):
    def mk(i, name, pos, mu, team, slot):
        p = P(i, name, pos, mu, team=team); p.slot = slot; return p
    roster = [mk(1, "QB1", "QB", 20, "SUN", "QB"), mk(2, "RB1", "RB", 16, "SUN", "RB"), mk(3, "RB2", "RB", 5, "SUN", "RB"),
              mk(4, "RB3", "RB", 14, "SUN", "BE"), mk(5, "WR1", "WR", 15, "MON", "WR"), mk(6, "WR2", "WR", 11, "SUN", "WR"),
              mk(7, "WR3", "WR", 12, "MON", "BE"), mk(8, "TE1", "TE", 8, "SUN", "TE"), mk(9, "K1", "K", 8, "MON", "K"),
              mk(10, "D1", "D/ST", 7, "SUN", "D/ST"), mk(11, "RB4", "RB", 10, "MON", "RB/WR/TE")]
    rows = [{"espn_id": p.espn_id, "actual_week": {2: 22.0, 3: 1.5, 4: 25.0, 6: 9.0}.get(p.espn_id, 0.0)} for p in roster]
    apply_clock(roster, rows, LINES, NOW)
    by = {p.name: p for p in roster}
    assert by["RB1"].locked and by["RB1"].mu == 22.0 and by["RB1"].var == 0
    assert not by["WR1"].locked
    L = optimize(roster, slots, objective="ev")
    names = {s: [p.name for p in ps] for s, ps in L.assignment.items()}
    assert names["RB"] == ["RB1", "RB2"]           # RB2 scored 1.5 but is locked; RB3 (25 on the bench) can't come in
    assert "RB3" not in sum(names.values(), [])
    # WR3 (unplayed bench, 12) can still replace RB4 (unplayed, 10) in the flex
    assert names["RB/WR/TE"] == ["WR3"]
    # Sunday players are banked at their actual points (QB1/TE1/D1 scored 0); Monday players keep projections
    assert abs(L.mu - (0 + 22 + 1.5 + 15 * 0.98 + 9 + 0 + 8 * 0.98 + 0 + 12 * 0.98)) < 1e-6


def test_week_state_phases():
    a = P(1, "A", "QB", 20); a.slot = "QB"; a.locked = True; a.actual = 21.0
    b = P(2, "B", "RB", 10); b.slot = "RB"
    o = P(3, "O", "QB", 20, tid=2); o.slot = "QB"; o.locked = True; o.actual = 15.0
    ns = {"BE", "IR", "", "FA"}
    ws = week_state([a, b], [o], ns)
    assert ws["phase"] == "in_progress" and ws["my_points"] == 21.0 and ws["my_left"] == ["B"]
    b.locked = True; b.actual = 4.0
    assert week_state([a, b], [o], ns)["phase"] == "final"
    a.locked = b.locked = o.locked = False
    assert week_state([a, b], [o], ns)["phase"] == "pre"


def test_locked_free_agent_has_no_week_value():
    fa = P(50, "FA", "WR", 14, team="SUN")
    apply_clock([fa], [{"espn_id": 50, "actual_week": 30.0}], LINES, NOW, free_agents=True)
    assert fa.locked and fa.mu == 0 and fa.mu_ros == 14
