"""The backtest harness (TODO D8): a synthetic season whose actuals come from the model's own distribution has to read
as calibrated, one whose actuals are three times as wide has to read as over-confident, the optimizer's lineup has to
out-score the one a lazy manager set, a trade is scored week by week against the replay, and the pull keeps the box
score's shape (and skips a two-week matchup)."""
from __future__ import annotations

import random
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from ff import backtest as bt
from ff.config import LeagueRef, LeagueSettings
from ff.model.lineup import optimize
from ff.model.projections import _sigma

SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "K": 1, "D/ST": 1}
PLAN = (("QB", 2, 18), ("RB", 4, 12), ("WR", 4, 11), ("TE", 2, 7), ("K", 1, 8), ("D/ST", 1, 7))


def _roster(rng: random.Random, draw, pid: int, lazy: bool, week: int) -> tuple[list[dict], int]:
    """One team-week: projections by position with a bench, actuals from `draw(pos, mu)`, the lineup set as the
    highest-points lineup (a careful manager); `lazy` swaps his best RB starter for a bench RB."""
    rows = []
    for pos, n, base in PLAN:
        for i in range(n):
            mu = round(max(base + rng.gauss(0, 4) - 3 * i, 0.5), 1)
            elig = [pos] + (["RB/WR/TE"] if pos in ("RB", "WR", "TE") else [])
            rows.append({"espn_id": pid, "name": f"P{pid}", "pos": pos, "team": "X", "eligible": elig, "slot": "BE",
                         "proj": mu, "actual": round(draw(pos, mu), 2), "bye": False})
            pid += 1
    ev = optimize([bt.row_proj(r, week) for r in rows], SLOTS, objective="ev")
    seat = {p.espn_id: s for s, ps in ev.assignment.items() for p in ps}
    for r in rows:
        r["slot"] = seat.get(r["espn_id"], "BE")
    if lazy:
        best = max((r for r in rows if r["pos"] == "RB" and r["slot"] != "BE"), key=lambda r: r["proj"])
        sub = max((r for r in rows if r["pos"] == "RB" and r["slot"] == "BE"), key=lambda r: r["proj"])
        best["slot"], sub["slot"] = "BE", best["slot"]
    return rows, pid


def synthetic_replay(weeks: int = 60, teams: int = 12, sigma_mult: float = 1.0, lazy_every: int = 0, seed: int = 3) -> dict:
    """A replay whose actuals are drawn from the model's mixture (`p_zero` 0.02, the house sigma times
    `sigma_mult`); `lazy_every` benches every n-th team's best RB."""
    rng, nrng = random.Random(seed), np.random.default_rng(seed)

    def draw(pos, mu):
        if nrng.random() < 0.02:
            return 0.0
        return float(nrng.normal(mu, _sigma(pos, mu, None) * sigma_mult))

    out, pid = [], 1000
    for w in range(1, weeks + 1):
        matchups = []
        order = list(range(1, teams + 1))
        rng.shuffle(order)
        for h, a in zip(order[::2], order[1::2]):
            hr, pid = _roster(rng, draw, pid, bool(lazy_every and h % lazy_every == 0), w)
            ar, pid = _roster(rng, draw, pid, bool(lazy_every and a % lazy_every == 0), w)
            score = lambda rows: round(sum(r["actual"] for r in rows if r["slot"] in SLOTS), 2)
            matchups.append({"home": h, "away": a, "home_score": score(hr), "away_score": score(ar), "playoff": False,
                             "home_roster": hr, "away_roster": ar})
        out.append({"week": w, "first_kickoff": f"2025-{9 + (w - 1) // 4:02d}-{1 + 7 * ((w - 1) % 4):02d}", "matchups": matchups})
    return {"version": bt.REPLAY_VERSION, "season": 2025, "league": "syn", "pulled": "2026-10-20",
            "settings": {"name": "Synthetic", "team_count": teams, "lineup_slots": SLOTS, "ppr": 1.0, "reg_season_weeks": weeks, "playoff_weeks": []},
            "skipped_weeks": [], "weeks": out}


def _pooled(bins: list[dict], lo: float) -> tuple[float, float]:
    """(predicted, won) over the bins at or above `lo`."""
    sel = [b for b in bins if b["lo"] >= lo and b["n"]]
    n = sum(b["n"] for b in sel)
    return sum(b["p_mean"] * b["n"] for b in sel) / n, sum(b["won"] * b["n"] for b in sel) / n


@pytest.fixture(scope="module")
def calibrated():
    """The model's own draw, scored once for the two calibration tests (the search runs 720 lineups)."""
    return bt.lineup_calibration(synthetic_replay())


def test_actuals_from_the_models_own_distribution_read_as_calibrated(calibrated):
    res = calibrated
    c = res["calibration"]
    assert c["n"] == 360 and res["score_mismatch"] == 0
    assert c["brier"] < 0.22          # the number has skill: lineups differ, and the draw is the model's
    assert c["ece"] < 0.08            # and it is honest within sampling noise at this n
    pred, won = _pooled(c["bins"], 0.6)
    assert abs(pred - won) < 0.08
    assert sum(b["n"] for b in c["bins"]) == c["n"]
    assert all(b["lo"] < b["hi"] for b in c["bins"]) and len(c["bins"]) == bt.BINS


def test_actuals_three_times_as_wide_read_as_over_confident(calibrated):
    """Sigma too small is the failure this table exists to show: the favourites win less than the model says."""
    good = calibrated["calibration"]
    wide = bt.lineup_calibration(synthetic_replay(sigma_mult=3.0))["calibration"]
    assert wide["ece"] > good["ece"] and wide["brier"] > good["brier"]
    pred, won = _pooled(wide["bins"], 0.7)
    assert pred - won > 0.1              # the favourites' bins: promised over 0.7, delivered well under


def test_the_optimizer_out_scores_a_lazy_manager_and_matches_a_careful_one():
    careful = bt.lineup_calibration(synthetic_replay(weeks=20, teams=8))["optimizer"]
    assert careful["team_weeks"] == 160
    assert careful["ev_over_set"] == 0.0 and careful["pts"]["ev"] == careful["pts"]["set"]   # he set the highest-points lineup
    lazy = bt.lineup_calibration(synthetic_replay(weeks=20, teams=8, lazy_every=2))["optimizer"]
    assert lazy["ev_over_set"] > 1.0 and lazy["win_rate"]["ev"] > lazy["win_rate"]["set"]
    assert lazy["pts"]["win"] >= lazy["pts"]["set"]
    d = lazy["differs"]
    assert d["n"] >= 0 and d["min_n"] == bt.DIFFERS_MIN_N
    if d["n"]:
        assert d["gain_realized"] == pytest.approx(d["win_rate"]["win"] - d["win_rate"]["ev"], abs=0.002)


def test_a_score_that_does_not_match_its_starters_is_counted_not_fixed():
    rep = synthetic_replay(weeks=2, teams=4)
    rep["weeks"][0]["matchups"][0]["home_score"] += 5.0
    assert bt.lineup_calibration(rep)["score_mismatch"] == 1


def test_an_empty_replay_scores_nothing():
    rep = synthetic_replay(weeks=1, teams=4)
    rep["weeks"] = []
    res = bt.lineup_calibration(rep)
    assert res["calibration"] is None and res["optimizer"] is None and res["weeks"] == []


def test_row_proj_is_the_house_prior_on_espns_number():
    p = bt.row_proj({"espn_id": 1, "name": "A", "pos": "WR", "team": "SF", "eligible": ["WR", "RB/WR/TE"], "slot": "WR", "proj": 12.0, "actual": 3.0, "bye": False}, 5)
    assert (p.mu, p.sigma, p.p_zero) == (12.0, round(_sigma("WR", 12.0, None), 2), 0.02)
    out = bt.row_proj({"espn_id": 2, "name": "B", "pos": "RB", "team": "SF", "eligible": ["RB"], "slot": "BE", "proj": 0.0, "actual": 0.0, "bye": False}, 5)
    assert out.p_zero == 1.0 and out.var == 0.0      # ESPN's zero on a game week: a certain zero, not 0 ± sigma
    bye = bt.row_proj({"espn_id": 3, "name": "C", "pos": "QB", "team": "SF", "eligible": ["QB"], "slot": "QB", "proj": 18.0, "actual": 0.0, "bye": True}, 5)
    assert bye.p_zero == 1.0 and bye.mu == 0.0 and bye.bye


# ---------- trades ----------

def _mini_replay() -> dict:
    def row(pid, name, pos, slot, actual):
        return {"espn_id": pid, "name": name, "pos": pos, "team": "X", "eligible": [pos], "slot": slot, "proj": 10.0, "actual": actual, "bye": False}
    weeks = []
    for w, kick, hub, rod, tut in ((6, "2026-10-15", 18.0, 4.0, 6.0), (7, "2026-10-22", 9.0, 7.0, None), (8, "2026-10-29", 12.0, 2.0, 1.0)):
        home = [row(1, "Chuba Hubbard", "RB", "RB", hub), row(9, "QB A", "QB", "QB", 20.0)]
        away = [row(2, "Chris Rodriguez Jr.", "RB", "RB", rod)] + ([row(3, "Bhayshul Tuten", "RB", "BE", tut)] if tut is not None else [])
        weeks.append({"week": w, "first_kickoff": kick, "matchups": [{"home": 1, "away": 2, "home_score": 0, "away_score": 0, "playoff": False,
                                                                       "home_roster": home, "away_roster": away}]})
    return {"version": 1, "season": 2026, "league": "L1", "pulled": "2026-11-01", "settings": {"lineup_slots": {"QB": 1, "RB": 1}},
            "skipped_weeks": [], "weeks": weeks}


def test_a_trade_is_scored_from_the_first_week_after_it_closed_and_a_missing_week_is_not_a_zero():
    rep = _mini_replay()
    assert bt.week_after(rep, "2026-10-14") == 6 and bt.week_after(rep, "2026-10-15") == 7 and bt.week_after(rep, "2026-11-05") is None
    assert bt.week_after(rep, None) is None
    o = {"status": "accepted", "league": "L1", "rival": "R", "give": ["Chris Rodriguez Jr.", "Bhayshul Tuten"], "get": ["Chuba Hubbard"],
         "closed": "2026-10-14", "predicted_ppw": 2.5}
    r = bt.trade_hits({"L1|x": o}, {"L1": rep})[0]
    # week 6: 18 - (4 + 6) = 8; week 7: Tuten unrostered, missing; week 8: 12 - (2 + 1) = 9
    assert (r["from_week"], r["weeks"], r["missing"], r["realized_ppw"], r["predicted_ppw"], r["hit"]) == (6, 2, 1, 8.5, 2.5, True)
    bad = bt.score_trade({**o, "predicted_ppw": -1.0}, bt.weekly_actuals(rep), 6, 9)
    assert bad["hit"] is False
    assert bt.score_trade({**o, "predicted_ppw": None}, bt.weekly_actuals(rep), 6, 9)["hit"] is None


def test_an_offer_without_a_replay_or_not_accepted_is_listed_or_skipped():
    rep = _mini_replay()
    outs = {"L2|y": {"status": "accepted", "league": "L2", "give": ["A"], "get": ["B"], "closed": "2026-10-14"},
            "L1|z": {"status": "declined", "league": "L1", "give": ["A"], "get": ["B"], "closed": "2026-10-14"}}
    rows = bt.trade_hits(outs, {"L1": rep})
    assert len(rows) == 1 and rows[0]["league"] == "L2" and rows[0]["weeks"] == 0 and rows[0]["realized_ppw"] is None


# ---------- the pull ----------

class _P(SimpleNamespace):
    pass


def _bp(pid, name, pos, slot, proj, actual, bye=False, kick=None):
    return _P(playerId=pid, name=name, position=pos, proTeam="SF", eligibleSlots=[pos, "RB/WR/TE", "BE", "IR"] if pos != "QB" else ["QB", "BE"],
              slot_position=slot, projected_points=proj, points=actual, on_bye_week=bye,
              **({"game_date": kick} if kick else {}))


def _box(home, away, hs, as_, hl, al, playoff=False):
    return _P(home_team=_P(team_id=home) if home else None, away_team=_P(team_id=away) if away else None,
              home_score=hs, away_score=as_, home_lineup=hl, away_lineup=al, is_playoff=playoff)


def test_pull_keeps_the_box_scores_shape_and_skips_two_week_matchups_and_byes():
    kick = {1: datetime(2025, 9, 4, 18), 2: datetime(2025, 9, 11, 18)}
    boxes = {
        1: [_box(1, 2, 101.5, 98.0, [_bp(10, "A", "RB", "RB", 12.3, 15.0, kick=kick[1]), _bp(11, "B", "QB", "BE", 0.0, 0.0, bye=True)],
                 [_bp(12, "C", "WR", "WR", 9.0, 4.5, kick=datetime(2025, 9, 7, 13))]),
            _box(3, None, 0, 0, [_bp(13, "D", "RB", "RB", 5.0, 5.0)], [])],                  # a bye in the fantasy schedule
        2: [_box(2, 1, 88.0, 90.0, [_bp(12, "C", "WR", "WR", 11.0, 20.0, kick=kick[2])], [_bp(10, "A", "RB", "RB", 13.0, 2.0)])],
        3: [_box(1, 2, 0, 0, [_bp(10, "A", "RB", "RB", 10.0, 0.0)], [_bp(12, "C", "WR", "WR", 10.0, 0.0)])],   # not played yet
    }
    league = _P(current_week=4, box_scores=lambda w, player_team_cache=None: boxes.get(w, []))
    settings = LeagueSettings(name="L", team_count=4, scoring={}, lineup_slots={"QB": 1, "RB": 1, "WR": 1}, bench_slots=5, ir_slots=1,
                              reg_season_weeks=2, playoff_team_count=2, playoff_weeks=[3], matchup_periods={1: [1], 2: [2], 3: [3, 4]},
                              faab=False, faab_budget=0, trade_deadline_ms=0, ppr=0.5)
    with patch.object(bt.espn, "settings", lambda ref, lg: settings):
        rep = bt.pull_replay(LeagueRef(name="L1", espn_id=7), league, 2025, today=__import__("datetime").date(2026, 10, 20))
    assert rep["version"] == bt.REPLAY_VERSION and (rep["season"], rep["league"], rep["pulled"]) == (2025, "L1", "2026-10-20")
    assert rep["settings"]["lineup_slots"] == {"QB": 1, "RB": 1, "WR": 1} and rep["settings"]["ppr"] == 0.5
    assert [w["week"] for w in rep["weeks"]] == [1, 2] and rep["skipped_weeks"] == [3, 4]
    w1 = rep["weeks"][0]
    assert w1["first_kickoff"] == "2025-09-04" and len(w1["matchups"]) == 1          # the bye matchup is gone, the earliest game dates it
    m = w1["matchups"][0]
    assert (m["home"], m["away"], m["home_score"], m["away_score"]) == (1, 2, 101.5, 98.0)
    assert m["home_roster"][0] == {"espn_id": 10, "name": "A", "pos": "RB", "team": "SF", "eligible": ["RB", "RB/WR/TE"], "slot": "RB",
                                   "proj": 12.3, "actual": 15.0, "bye": False}
    assert m["home_roster"][1]["bye"] is True and m["home_roster"][1]["eligible"] == ["QB"]
    assert bt.weekly_actuals(rep)["A"] == {1: 15.0, 2: 2.0}


def test_save_and_load_round_trip_and_version_check(tmp_path):
    rep = synthetic_replay(weeks=1, teams=4)
    with patch.object(bt, "REPLAY_DIR", tmp_path):
        path = bt.save_replay(rep)
        assert path == tmp_path / "2025-syn.json" and bt.load_replay(path) == rep
    (tmp_path / "old.json").write_text('{"version": 0}')
    with pytest.raises(SystemExit):
        bt.load_replay(tmp_path / "old.json")
