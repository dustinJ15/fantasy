"""`packet.build` prices the league's week (ESPN's `current_week`, which rolls Tuesday); every weekly source it pulls
must be for that same week. Sleeper's `/state/nfl` rolls on its own clock, so on Monday and Tuesday the two can differ."""
from ff import demo, packet
from ff.config import LeagueRef


class _XW(demo.FakeCrosswalk):
    def fp_weekly_index(self):
        return {}


def _stub_build(monkeypatch, tmp_path, league_week: int, sleeper_week: int, state=None) -> list[int]:
    """Run the real build over the demo league with every network pull and projlog write stubbed out.
    `state` replaces `sleeper.state` (default: a clock reading `sleeper_week`). Returns the weeks `sleeper.projections`
    was asked for."""
    asked: list[int] = []
    snap = demo.make_snapshot()
    snap["week"] = league_week
    monkeypatch.setattr(packet, "leagues", lambda only=None: [LeagueRef(name="demo", espn_id=1, team_id=1)])
    monkeypatch.setattr(packet, "league_snapshot", lambda ref, force=False: snap)
    monkeypatch.setattr(packet, "Crosswalk", _XW)
    monkeypatch.setattr(packet.sleeper, "injury_table", lambda force=False: {})
    monkeypatch.setattr(packet.sleeper, "players", lambda force=False: {})
    monkeypatch.setattr(packet.sleeper, "trending", lambda *a, **kw: [])
    monkeypatch.setattr(packet.sleeper, "state", state or (lambda force=False: {"week": sleeper_week, "display_week": sleeper_week}))

    def projections(season, week, force=False):
        asked.append(week)
        return {}
    monkeypatch.setattr(packet.sleeper, "projections", projections)
    monkeypatch.setattr(packet.usage_mod, "season_summary", lambda season: (_ for _ in ()).throw(RuntimeError("no nflverse")))
    monkeypatch.setattr(packet.vegas, "implied_totals", lambda week=None, force=False: {})
    monkeypatch.setattr(packet.fantasycalc, "by_espn_id", lambda **kw: {})
    for name in ("load_skips", "load_pushes", "load_outcomes", "load_ir_moves"):
        monkeypatch.setattr(packet, name, lambda: {})
    monkeypatch.setattr(packet, "record_outcomes", lambda pkt, now=None: {})
    monkeypatch.setattr(packet, "save_ir_moves", lambda moves: None)
    monkeypatch.setattr(packet, "PACKET_DIR", tmp_path)
    pkt = packet.build(sims=50)
    assert pkt["leagues"][0]["week"] == league_week
    return asked


def test_sleeper_projections_are_for_the_leagues_week(monkeypatch, tmp_path):
    # Monday: ESPN still says week 5 (it rolls Tuesday) and the clock banks Sunday's points; Sleeper already says 6.
    asked = _stub_build(monkeypatch, tmp_path, league_week=5, sleeper_week=6)
    assert asked == [5], f"Sleeper projections fetched for {asked}, the league is pricing week 5"


def test_sleeper_lagging_the_league_is_the_same_bug(monkeypatch, tmp_path):
    # Tuesday morning the other way round: ESPN has rolled to 6, Sleeper's state still reads 5.
    asked = _stub_build(monkeypatch, tmp_path, league_week=6, sleeper_week=5)
    assert asked == [6], f"Sleeper projections fetched for {asked}, the league is pricing week 6"


def test_build_does_not_consult_sleepers_clock(monkeypatch, tmp_path):
    # Sleeper's clock is not read at all: a dead `/state/nfl` must not cost the week's projections either.
    def boom(force=False):
        raise AssertionError("sleeper.state() is not the week the briefing prices")
    asked = _stub_build(monkeypatch, tmp_path, league_week=7, sleeper_week=7, state=boom)
    assert asked == [7]


def test_sleeper_down_leaves_the_blend_without_it(monkeypatch):
    monkeypatch.setattr(packet.sleeper, "projections", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("503")))
    assert packet._sleeper_projections(2026, 5) == {}
    assert packet._sleeper_projections(2026, 0) == {}
