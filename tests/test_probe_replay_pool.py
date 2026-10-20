"""The pure half of `scripts/probe_replay_pool.py` (TODO D12 step 1): the stat rows of a `kona_player_info` entry read
into periods, a past-period pool that holds a rostered-that-week player reads as today's, the projection comparison
counts agreement and the largest gap, and the coverage says how deep the universe pull must go."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("probe_replay_pool", Path(__file__).resolve().parents[1] / "scripts" / "probe_replay_pool.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def _stat(period, source, total, split=1, season=2026):
    return {"scoringPeriodId": period, "statSourceId": source, "statSplitTypeId": split, "seasonId": season, "appliedTotal": total}


def test_period_stats_reads_projection_and_actual_per_period_and_skips_season_totals():
    entry = {"id": 1, "player": {"stats": [_stat(3, 1, 12.4), _stat(3, 0, 9.1), _stat(4, 1, 11.0),
                                           _stat(0, 1, 180.0, split=0), _stat(3, 1, 5.0, season=2025)]}}
    assert probe.period_stats(entry, 2026) == {3: {"proj": 12.4, "actual": 9.1}, 4: {"proj": 11.0}}


def test_pool_verdict_reads_an_overlap_as_todays_pool():
    assert probe.pool_verdict({1, 2, 3}, {3, 9})["verdict"].startswith("today's")
    v = probe.pool_verdict({1, 2}, {3, 9})
    assert v["n_rostered_that_week"] == 0 and v["verdict"].startswith("consistent")


def test_projection_agreement_counts_matches_gaps_and_missing():
    universe = {1: {6: {"proj": 12.4}}, 2: {6: {"proj": 10.0}}, 3: {5: {"proj": 4.0}}}
    out = probe.projection_agreement(universe, {1: 12.4, 2: 7.6, 3: 4.0, 4: 1.0}, week=6)
    assert out == {"n": 2, "n_equal": 1, "max_diff": 2.4, "missing": 2}


def test_coverage_finds_the_depth_and_the_misses_per_size():
    ordered = list(range(100, 1300))
    rostered = {100, 450, 1250}
    out = probe.coverage(ordered, rostered)
    assert out["depth"] == 1151 and out["beyond_pull"] == 0
    assert out["missing_at"] == {300: 2, 600: 1, 1000: 1}
    beyond = probe.coverage(ordered[:200], rostered)
    assert beyond["depth"] is None and beyond["beyond_pull"] == 2


def _entry(pid, status="ACTIVE", owned=50.0, team=1):
    return {"id": pid, "onTeamId": team, "player": {"injuryStatus": status, "ownership": {"percentOwned": owned}}}


def test_payload_drift_reads_a_matching_payload_as_todays_and_counts_the_moves():
    past = {1: _entry(1, team=3), 2: _entry(2, team=0), 3: _entry(3, "OUT", 80.0, 2)}
    now = {1: _entry(1, team=3), 2: _entry(2, team=0), 3: _entry(3, "OUT", 80.0, 2)}
    box_team = {1: 1, 2: 2, 3: 2}   # week w held 1 on team 1, 2 on team 2; the past payload says team 3 and the wire
    out = probe.payload_drift(past, now, box_team)
    assert out["verdict"].startswith("today's")
    assert (out["status_diff"], out["owned_diff"], out["team_diff"]) == (0, 0, 0)
    assert out["moved"] == 2 and out["moved_to_today"] == 2 and out["n_rostered"] == 3


def test_payload_drift_counts_each_field_that_differs():
    past = {1: _entry(1, "QUESTIONABLE", 40.0, 1), 2: _entry(2, owned=10.0, team=1), 3: _entry(3, team=1)}
    now = {1: _entry(1, "ACTIVE", 40.0, 1), 2: _entry(2, owned=12.0, team=1), 3: _entry(3, team=4)}
    out = probe.payload_drift(past, now, {1: 1, 2: 1, 3: 1})
    assert (out["status_diff"], out["owned_diff"], out["team_diff"]) == (1, 1, 1)
    assert out["moved"] == 0 and out["verdict"].startswith("the past period")
