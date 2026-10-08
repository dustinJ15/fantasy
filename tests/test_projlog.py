"""The accuracy harness scores a pre-kickoff forecast against ESPN's actual, never the blend against itself (TODO A2)."""
import csv
import re

import numpy as np
import pytest

from ff import projlog
from ff.model.projections import sigma_shape
from ff.projlog import COLUMNS, scored_rows, write


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(projlog, "LOG_DIR", tmp_path)
    return tmp_path


def _row(p, **kw):
    r = {"espn_id": p["espn_id"], "name": p["name"], "pos": p["pos"], "team": "X", "espn_pts": p.get("espn"), "sleeper_pts": p.get("sleeper"),
         "fp_pts": p.get("fp"), "blend": p["blend"], "p_zero": 0.02, "implied": None, "phase": "pre", "actual": None, "actual_prev": None}
    r.update(kw)
    return r


def _write(log_dir, season, week, date, rows, legacy=False):
    cols = [c for c in COLUMNS if not legacy or c not in ("league", "phase", "actual", "actual_prev")]
    with open(log_dir / f"{season}-w{week:02d}-{date}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def _packet_player(i, name, pos, mu, locked=False, actual=None, mu_pre=None, actual_prev=None, bye=False):
    flags = ["clock:post"] if locked else []
    return {"espn_id": i, "name": name, "pos": pos, "team": "X", "mu": mu, "p_zero": 0.0 if locked else 0.02, "bye": bye, "flags": flags,
            "locked": locked, "actual": actual, "mu_pre": mu_pre,
            "sources": {"espn_pts": mu, "sleeper_pts": mu + 1, "fp_pts": None, "implied_total": 24.0, "actual_prev": actual_prev}}


def test_write_logs_the_pre_clock_projection_and_one_row_per_league(log_dir):
    kittle_played = _packet_player(1, "Kittle", "TE", 19.0, locked=True, actual=19.0, mu_pre=13.3, actual_prev=7.5)
    kittle_pre = _packet_player(1, "Kittle", "TE", 12.9, actual_prev=7.0)   # half-PPR league: same player, other numbers
    bye = _packet_player(2, "ByeGuy", "WR", 0.0, bye=True)
    packet = {"season": 2026, "generated": "2026-10-05T12:00", "leagues": [
        {"name": "L1", "week": 4, "roster": [kittle_played, bye]}, {"name": "L2", "week": 4, "roster": [kittle_pre]}]}
    out = write(packet)
    rows = list(csv.DictReader(open(out)))
    assert out.name == "2026-w04-2026-10-05.csv"
    assert [(r["league"], r["name"]) for r in rows] == [("L1", "Kittle"), ("L1", "ByeGuy"), ("L2", "Kittle")]
    l1 = rows[0]
    assert l1["blend"] == "13.3" and l1["phase"] == "post" and l1["actual"] == "19.0" and l1["actual_prev"] == "7.5"
    assert rows[1]["phase"] == "bye"
    assert rows[2]["blend"] == "12.9" and rows[2]["phase"] == "pre" and rows[2]["actual"] == ""


def test_scores_last_pre_kickoff_row_against_espn_actual_per_league(log_dir):
    wr = {"espn_id": "10", "name": "WR", "pos": "WR", "blend": 14.0, "espn": 13.0}
    k = {"espn_id": "11", "name": "K", "pos": "K", "blend": 8.0, "espn": 8.0}
    dst = {"espn_id": "12", "name": "DST", "pos": "D/ST", "blend": 7.0, "espn": 6.0}
    mnf = {"espn_id": "13", "name": "MNF", "pos": "RB", "blend": 12.0, "espn": 12.0}
    # Thursday: everyone is a forecast. Saturday: the WR's news moved him; he is still pre-kickoff, so Saturday's number counts.
    _write(log_dir, 2026, 3, "2026-09-24", [_row(p, league="L1") for p in (wr, k, dst, mnf)] + [_row(wr, league="L2", blend=12.0)])
    _write(log_dir, 2026, 3, "2026-09-26", [_row(wr, league="L1", blend=10.0), _row(wr, league="L2", blend=9.0)])
    # Monday: Sunday players are post with ESPN's actual (league scoring differs: L2 is half-PPR); the MNF player is still pre.
    monday = [_row(wr, league="L1", phase="post", blend=10.0, actual=20.0), _row(wr, league="L2", phase="post", blend=9.0, actual=17.0),
              _row(k, league="L1", phase="post", blend=8.0, actual=3.0), _row(dst, league="L1", phase="post", blend=7.0, actual=12.0),
              _row(mnf, league="L1", blend=11.0)]
    _write(log_dir, 2026, 3, "2026-09-28", monday)
    # Tuesday, week 4: ESPN's finals for week 3 ride in as actual_prev, which is how the Monday-night game gets scored.
    _write(log_dir, 2026, 4, "2026-09-29", [_row(mnf, league="L1", actual_prev=4.0), _row(wr, league="L1", actual_prev=20.0)])
    recs = scored_rows(projlog._logs(2026), through_week=4)
    blend = {(r["league"], r["espn_id"]): r for r in recs if r["source"] == "blend"}
    assert blend[("L1", "10")]["abs_err"] == 10.0     # Saturday's 10.0 against 20.0, not Monday's banked 20.0 against itself
    assert blend[("L2", "10")]["abs_err"] == 8.0      # the half-PPR league scores its own forecast against its own actual
    assert blend[("L1", "11")]["abs_err"] == 5.0 and blend[("L1", "12")]["abs_err"] == 5.0   # K and D/ST have rows
    assert blend[("L1", "13")]["abs_err"] == 7.0      # the Monday-night player: Monday's 11.0 against Tuesday's actual_prev 4.0
    assert {r["source"] for r in recs} == {"blend", "espn_pts"}   # sleeper/fp blank rows are not scored
    assert projlog.accuracy(2026, 4).filter(projlog.pl.col("pos") == "WR").height == 2


def test_legacy_logs_recover_the_truth_from_the_locked_blend(log_dir):
    kittle = {"espn_id": "3040151", "name": "George Kittle", "pos": "TE", "blend": 13.34, "espn": 13.76}
    ghost = {"espn_id": "99", "name": "Ghost", "pos": "RB", "blend": 9.0, "espn": 9.0}
    _write(log_dir, 2026, 4, "2026-10-04", [_row(kittle), _row(ghost)], legacy=True)
    # Monday, old format: the clock zeroed p_zero and wrote the actual into the blend. Ghost is a stale-clock zero, not a score.
    _write(log_dir, 2026, 4, "2026-10-05", [_row(kittle, blend=19.0, p_zero=0.0), _row(ghost, blend=0.0, p_zero=0.0)], legacy=True)
    recs = scored_rows(projlog._logs(2026), through_week=5)
    by = {(r["espn_id"], r["source"]): r for r in recs}
    assert by[("3040151", "blend")]["abs_err"] == pytest.approx(5.66)
    assert by[("3040151", "espn_pts")]["abs_err"] == pytest.approx(5.24)
    assert ("99", "blend") not in by


def test_nothing_scored_without_a_truth_or_past_through_week(log_dir):
    p = {"espn_id": "1", "name": "A", "pos": "QB", "blend": 20.0, "espn": 20.0}
    _write(log_dir, 2026, 5, "2026-10-08", [_row(p, league="L1")])
    _write(log_dir, 2026, 5, "2026-10-12", [_row(p, league="L1", phase="post", actual=25.0)])
    assert scored_rows(projlog._logs(2026), through_week=5) == []
    assert len(scored_rows(projlog._logs(2026), through_week=6)) == 2
    assert projlog.accuracy(2026, 5).is_empty()


def test_clock_keeps_the_pre_lock_projection():
    from datetime import UTC, datetime

    from ff.model.clock import apply_clock
    from ff.model.projections import PlayerProj
    p = PlayerProj(espn_id=1, name="A", pos="WR", team="SF", eligible=["WR"], fantasy_team_id=1, slot="WR", mu=13.3, sigma=5.0,
                   p_zero=0.02, mu_ros=13.0)
    apply_clock([p], [{"espn_id": 1, "actual_week": 19.0}], {"SF": {"state": "post"}}, now=datetime(2026, 10, 5, 12, tzinfo=UTC))
    assert (p.mu, p.mu_pre, p.actual, p.locked) == (19.0, 13.3, 19.0, True)
    assert projlog.phase_of(p.to_dict()) == "post"


def _monday_of_week_5(log_dir):
    """Week 4 is complete (its finals rode in on week 5's first log); week 5 is in progress, Monday night still pre."""
    a = {"espn_id": "1", "name": "A", "pos": "QB", "blend": 20.0, "espn": 20.0}
    b = {"espn_id": "2", "name": "B", "pos": "RB", "blend": 12.0, "espn": 12.0}
    _write(log_dir, 2026, 4, "2026-10-01", [_row(a, league="L1"), _row(b, league="L1")])
    _write(log_dir, 2026, 4, "2026-10-05", [_row(a, league="L1", phase="post", actual=25.0), _row(b, league="L1")])
    _write(log_dir, 2026, 5, "2026-10-06", [_row(a, league="L1", blend=18.0, actual_prev=25.0), _row(b, league="L1", actual_prev=6.0)])
    _write(log_dir, 2026, 5, "2026-10-12", [_row(a, league="L1", phase="post", blend=18.0, actual=10.0), _row(b, league="L1")])


def test_accuracy_scores_up_to_the_newest_logged_week_not_sleepers_clock(log_dir, monkeypatch):
    """TODO C8: `ff accuracy` took the current week from Sleeper's clock, which runs ahead of or behind the league's."""
    from typer.testing import CliRunner

    from ff.cli import app
    from ff.sources import sleeper
    _monday_of_week_5(log_dir)
    monkeypatch.setenv("SEASON", "2026")

    def no_network(force=False):
        raise AssertionError("ff accuracy must not read Sleeper's clock")
    monkeypatch.setattr(sleeper, "state", no_network)
    # The newest log is week 5, in progress: only week 4 is scored (A: 20 vs 25, B: 12 vs 6), n=1 per position.
    assert projlog.accuracy(2026).filter(projlog.pl.col("source") == "blend")["n"].to_list() == [1, 1]
    r = CliRunner().invoke(app, ["accuracy"])
    assert r.exit_code == 0, r.output
    assert "week 5" in r.output and "QB" in r.output and "RB" in r.output
    # `--week` overrides the log: 6 pulls in the half-played week 5 (the QB scored, the Monday-night RB not), 4 scores nothing.
    assert projlog.accuracy(2026, 6).filter(projlog.pl.col("source") == "blend")["n"].to_list() == [2, 1]
    assert projlog.accuracy(2026, 4).is_empty()
    out = CliRunner().invoke(app, ["accuracy", "--week", "6"]).output
    assert "week 6 (--week)" in out and re.search(r"QB\s+│\s+blend\s+│\s+2\s+│", out), out
    assert "no completed weeks" in CliRunner().invoke(app, ["accuracy", "--week", "4"]).output


def test_accuracy_with_no_logs_at_all(log_dir):
    assert projlog.current_week(2026) is None
    assert projlog.accuracy(2026).is_empty()


# --- D2: BASE_SIGMA / CV_FLOOR fitted from the blend residuals (`ff accuracy --fit`) ---

def _synthetic_residuals(base, cv, n, seed=0):
    rng = np.random.default_rng(seed)
    mu = rng.uniform(2.0, 25.0, n)
    err = rng.normal(0.0, sigma_shape(mu, base, cv))
    return mu, err


def test_fitter_recovers_a_known_sigma_from_synthetic_residuals():
    mu, err = _synthetic_residuals(base=6.0, cv=0.40, n=4000)
    f = projlog.fit_sigma_params(mu, err)
    assert abs(f["base"] - 6.0) <= 0.6 and abs(f["cv"] - 0.40) <= 0.04
    assert f["n"] == 4000 and 0 < f["floor_rows"] < 4000   # both regimes were in the sample
    assert projlog.fit_sigma_params(mu, err) == f   # deterministic: a grid, not an optimiser


def test_fitter_reports_an_unbinding_floor_as_unidentified():
    rng = np.random.default_rng(1)
    mu = rng.uniform(20.0, 30.0, 2000)   # every forecast is far above any floor on the grid
    err = rng.normal(0.0, 0.5 * mu)
    f = projlog.fit_sigma_params(mu, err)
    assert f["base"] is None and f["floor_rows"] == 0
    assert abs(f["cv"] - 0.5) <= 0.03


def test_fit_sample_drops_the_sat_out_zero_and_keeps_the_healthy_goose_egg():
    recs = [{"source": "blend", "pos": "WR", "mu": 12.0, "actual": 0.0, "p_zero": 0.3, "err": 12.0},   # Questionable, sat: the delta
            {"source": "blend", "pos": "WR", "mu": 9.0, "actual": 0.0, "p_zero": 0.02, "err": 9.0},    # healthy, zero catches: Gaussian
            {"source": "blend", "pos": "WR", "mu": 0.0, "actual": 4.0, "p_zero": 0.02, "err": -4.0},   # no forecast
            {"source": "espn_pts", "pos": "WR", "mu": 11.0, "actual": 5.0, "p_zero": 0.02, "err": 6.0}]  # not the blend
    sample = projlog.fit_sample(recs)
    assert list(sample["WR"][0]) == [9.0] and list(sample["WR"][1]) == [9.0]


def test_fitter_refuses_a_position_under_the_sample_threshold(log_dir):
    base, cv = 6.0, 0.40
    mu_rb, err_rb = _synthetic_residuals(base, cv, projlog.FIT_MIN_N, seed=2)
    mu_wr, err_wr = _synthetic_residuals(base, cv, projlog.FIT_MIN_N - 1, seed=3)
    pre, finals = [], []
    for pos, mus, errs in (("RB", mu_rb, err_rb), ("WR", mu_wr, err_wr)):
        for i, (m, e) in enumerate(zip(mus, errs)):
            p = {"espn_id": f"{pos}{i}", "name": f"{pos}{i}", "pos": pos, "blend": round(float(m), 2)}
            pre.append(_row(p, league="L1"))
            finals.append(_row(p, league="L1", week=4, actual_prev=round(float(m - e), 2)))
    _write(log_dir, 2026, 3, "2026-09-26", pre)
    _write(log_dir, 2026, 4, "2026-09-29", finals)
    rows = {r["pos"]: r for r in projlog.sigma_fit(2026, through_week=4)}
    rb, wr = rows["RB"], rows["WR"]
    assert rb["n"] == projlog.FIT_MIN_N and rb["fitted"] is True
    assert abs(rb["base_fit"] - base) <= 2.0 and abs(rb["cv_fit"] - cv) <= 0.1   # 150 rows is the floor, not a tight fit
    assert wr["n"] == projlog.FIT_MIN_N - 1 and wr["fitted"] is False and wr["cv_fit"] is not None   # shown, not adopted
    assert (wr["base_prior"], wr["cv_prior"]) == (6.5, 0.50)   # the prior rides on the row
    assert rows["QB"]["n"] == 0 and rows["QB"]["fitted"] is False and rows["QB"]["base_fit"] is None
    assert np.isfinite(rb["rmse"])
