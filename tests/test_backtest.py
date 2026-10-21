"""The backtest harness (TODO D8): a synthetic season whose actuals come from the model's own distribution has to read
as calibrated, one whose actuals are three times as wide has to read as over-confident, the optimizer's lineup has to
out-score the one a lazy manager set, a trade is scored week by week against the replay, and the pull keeps the box
score's shape (and skips a two-week matchup). The scanner replay (TODO D12, `docs/plans/scanner-replay.md`): on the
model's own draw the scan's packages read edge and the realized mean tracks the promised one; with the actuals
shuffled within a position they read none; and a week-w package never prices from a week-w or later actual. The claim
rows (`claim_hits`) are held to the same three properties, and the managers' actual adds are priced as claim rows."""
from __future__ import annotations

import copy
import random
from collections import defaultdict
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from ff import backtest as bt
from ff.config import LeagueRef, LeagueSettings
from ff.model.lineup import optimize
from ff.model.projections import NFL_GAMES, _sigma

SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "K": 1, "D/ST": 1}
PLAN = (("QB", 2, 18), ("RB", 4, 12), ("WR", 4, 11), ("TE", 2, 7), ("K", 1, 8), ("D/ST", 1, 7))
# The synthetic wire: this many free agents per position in the universe, projected a few points under the rostered
# depth so a claim is sometimes, not always, an upgrade.
WIRE_PER_POS = 24
# The scan tests' league: team t has a surplus at one position and a hole at another (`fit` points on his first two
# bodies there, the pairs rotating through this list), so real fit trades exist for the scan to find. Without them a
# roster drawn flat offers the scan only packages where both sides gain by the pricing's own noise, and the grade of
# those is the winner's curse, not a test of the harness (the plan's "What step 3 found").
FIT_PAIRS = (("RB", "WR"), ("WR", "RB"), ("TE", "QB"), ("QB", "TE"), ("WR", "TE"), ("RB", "QB"))


def _team(rng: random.Random, pid: int, fit: float = 0.0, pair: tuple[str, str] = ("", "")) -> tuple[list[dict], int]:
    """One team's roster for the season: a season level (`mu`) per player by position with a bench, his first two at
    `pair[0]` up `fit` points and at `pair[1]` down. The roster persists across weeks (a week-w package has later
    weeks of its own players to grade, and the wire at week w is the wire, not every other week's rosters)."""
    tpl = []
    for pos, n, base in PLAN:
        for i in range(n):
            shift = (fit if pos == pair[0] else -fit if pos == pair[1] else 0.0) if i < 2 else 0.0
            mu = round(max(base + shift + rng.gauss(0, 4) - 3 * i, 0.5), 1)
            elig = [pos] + (["RB/WR/TE"] if pos in ("RB", "WR", "TE") else [])
            tpl.append({"espn_id": pid, "name": f"P{pid}", "pos": pos, "team": "X", "eligible": elig, "mu": mu})
            pid += 1
    return tpl, pid


def _roster(rng: random.Random, draw, tpl: list[dict], lazy: bool, week: int) -> list[dict]:
    """One team-week: each player's projection drawn around his season level, his actual from `draw(pos, proj)`, the
    lineup set as the highest-points lineup (a careful manager); `lazy` swaps his best RB starter for a bench RB."""
    rows = []
    for t in tpl:
        proj = round(max(t["mu"] + rng.gauss(0, 1.5), 0.5), 1)
        rows.append({"espn_id": t["espn_id"], "name": t["name"], "pos": t["pos"], "team": t["team"], "eligible": list(t["eligible"]),
                     "slot": "BE", "proj": proj, "actual": round(draw(t["pos"], proj), 2), "bye": False})
    ev = optimize([bt.row_proj(r, week) for r in rows], SLOTS, objective="ev")
    seat = {p.espn_id: s for s, ps in ev.assignment.items() for p in ps}
    for r in rows:
        r["slot"] = seat.get(r["espn_id"], "BE")
    if lazy:
        best = max((r for r in rows if r["pos"] == "RB" and r["slot"] != "BE"), key=lambda r: r["proj"])
        sub = max((r for r in rows if r["pos"] == "RB" and r["slot"] == "BE"), key=lambda r: r["proj"])
        best["slot"], sub["slot"] = "BE", best["slot"]
    return rows


def synthetic_replay(weeks: int = 60, teams: int = 12, sigma_mult: float = 1.0, lazy_every: int = 0, seed: int = 3, fit: float = 0.0) -> dict:
    """A replay whose actuals are drawn from the model's mixture (`p_zero` 0.02, the house sigma times
    `sigma_mult`); `lazy_every` benches every n-th team's best RB; `fit` gives each team a surplus and a hole
    (`FIT_PAIRS`) so the scan has real trades to find."""
    rng, nrng = random.Random(seed), np.random.default_rng(seed)

    def draw(pos, mu):
        if nrng.random() < 0.02:
            return 0.0
        return float(nrng.normal(mu, _sigma(pos, mu, None) * sigma_mult))

    out, pid, tpls = [], 1000, {}
    for t in range(1, teams + 1):
        tpls[t], pid = _team(rng, pid, fit, FIT_PAIRS[(t - 1) % len(FIT_PAIRS)])
    for w in range(1, weeks + 1):
        matchups = []
        order = list(range(1, teams + 1))
        rng.shuffle(order)
        for h, a in zip(order[::2], order[1::2]):
            hr = _roster(rng, draw, tpls[h], bool(lazy_every and h % lazy_every == 0), w)
            ar = _roster(rng, draw, tpls[a], bool(lazy_every and a % lazy_every == 0), w)
            score = lambda rows: round(sum(r["actual"] for r in rows if r["slot"] in SLOTS), 2)
            matchups.append({"home": h, "away": a, "home_score": score(hr), "away_score": score(ar), "playoff": False,
                             "home_roster": hr, "away_roster": ar})
        out.append({"week": w, "first_kickoff": f"2025-{9 + (w - 1) // 4:02d}-{1 + 7 * ((w - 1) % 4):02d}", "matchups": matchups})
    players = _universe(out, weeks, rng, draw, pid, {t["espn_id"]: t["mu"] for tpl in tpls.values() for t in tpl})
    return {"version": bt.REPLAY_VERSION, "season": 2025, "league": "syn", "pulled": "2026-10-20",
            "settings": {"name": "Synthetic", "team_count": teams, "lineup_slots": SLOTS, "ppr": 1.0, "reg_season_weeks": weeks, "playoff_weeks": [],
                         "playoff_team_count": max(teams // 2, 1), "bench_slots": sum(n for _, n, _ in PLAN) - sum(SLOTS.values()), "position_limits": {}},
            "skipped_weeks": [], "weeks": out, "universe_size": len(players), "universe_missing": 0, "players": players}


def _universe(out: list[dict], weeks: int, rng: random.Random, draw, pid: int, level: dict[int, float]) -> dict[int, dict]:
    """The synthetic universe (the replay file's `players`): every rostered player, his box-score `proj` and `actual`
    on the weeks he was rostered and a draw of the same shape on any other week, plus a wire of `WIRE_PER_POS` per
    position; everyone with a preseason total (`proj_season`, his season level over `NFL_GAMES`, the prior `blend`
    fades) and a projection and an actual in every week."""
    players: dict[int, dict] = {}

    def add(r: dict, mu: float, known: dict[int, dict]):
        wk = {}
        for w in range(1, weeks + 1):
            p = known.get(w) or {"proj": round(max(mu + rng.gauss(0, 1.5), 0.5), 1)}
            wk[w] = {"proj": p["proj"], "actual": p.get("actual", round(draw(r["pos"], p["proj"]), 2))}
        players[r["espn_id"]] = {"espn_id": r["espn_id"], "name": r["name"], "pos": r["pos"], "team": r["team"],
                                 "eligible": list(r["eligible"]), "proj_season": round(mu * NFL_GAMES, 1), "bye_weeks": [], "weeks": wk}

    known: dict[int, dict[int, dict]] = {}
    for wk in out:
        for m in wk["matchups"]:
            for r in m["home_roster"] + m["away_roster"]:
                known.setdefault(r["espn_id"], {})[wk["week"]] = {"proj": r["proj"], "actual": r["actual"]}
                known[r["espn_id"]]["row"] = r
    for pid_, wks in known.items():
        r = wks.pop("row")
        add(r, level[pid_], wks)
    for pos, _, base in PLAN:
        for i in range(WIRE_PER_POS):
            mu = round(max(base - 4 + rng.gauss(0, 3) - i / 6, 0.5), 1)
            elig = [pos] + (["RB/WR/TE"] if pos in ("RB", "WR", "TE") else [])
            add({"espn_id": pid, "name": f"W{pid}", "pos": pos, "team": "X", "eligible": elig}, mu, {})
            pid += 1
    return players


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


def _up(pid, name, pos, stats, total=100.0, schedule=None):
    """A universe player as espn-api's Player carries him: `stats` keyed by period (0 the season row)."""
    st = {0: {"projected_points": total, "points": 0.0}, **stats} if stats is not None else {}
    return _P(playerId=pid, name=name, position=pos, proTeam="SF", eligibleSlots=[pos, "RB/WR/TE", "BE", "IR"] if pos != "QB" else ["QB", "BE"],
              projected_total_points=total if stats is not None else 0, stats=st, schedule=schedule or {})


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
    sched = {str(w): {} for w in range(1, 19) if w != 9}
    uni = [_up(10, "A", "RB", {1: {"projected_points": 12.3, "points": 15.0}, 2: {"projected_points": 13.0, "points": 2.0}, 3: {"projected_points": 10.0}}, 180.5, sched),
           _up(12, "C", "WR", {1: {"projected_points": 9.0, "points": 4.5}, 2: {"projected_points": 11.0, "points": 20.0}}, 150.0),
           _up(11, "B", "QB", None),                                                     # rostered, no stats block: missing
           _up(99, "Wire", "WR", {1: {"projected_points": 4.0, "points": 0.0}, 2: {"projected_points": 5.0, "points": 9.0}}, 60.0)]
    pulled = []
    with patch.object(bt.espn, "settings", lambda ref, lg: settings), \
         patch.object(bt.espn, "player_universe", lambda lg, w: pulled.append(w) or uni):
        rep = bt.pull_replay(LeagueRef(name="L1", espn_id=7), league, 2025, today=__import__("datetime").date(2026, 10, 20))
    assert pulled == [4]                                                                  # one pull, at the current period
    assert rep["version"] == bt.REPLAY_VERSION and (rep["season"], rep["league"], rep["pulled"]) == (2025, "L1", "2026-10-20")
    assert (rep["universe_size"], rep["universe_missing"]) == (4, 1) and sorted(rep["players"]) == [10, 12, 99]   # D (13) is out with his bye matchup
    assert rep["players"][10] == {"espn_id": 10, "name": "A", "pos": "RB", "team": "SF", "eligible": ["RB", "RB/WR/TE"], "proj_season": 180.5,
                                  "bye_weeks": [9], "weeks": {1: {"proj": 12.3, "actual": 15.0}, 2: {"proj": 13.0, "actual": 2.0}, 3: {"proj": 10.0}}}
    assert rep["players"][99]["weeks"][2] == {"proj": 5.0, "actual": 9.0} and rep["players"][12]["bye_weeks"] == []
    assert rep["settings"]["lineup_slots"] == {"QB": 1, "RB": 1, "WR": 1} and rep["settings"]["ppr"] == 0.5
    assert (rep["settings"]["playoff_team_count"], rep["settings"]["bench_slots"], rep["settings"]["position_limits"]) == (2, 5, {})   # the scanner replay's inputs
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
        back = bt.load_replay(path)
        assert path == tmp_path / "2025-syn.json" and back == rep
        pid = next(iter(back["players"]))
        assert isinstance(pid, int) and all(isinstance(w, int) for w in back["players"][pid]["weeks"])   # JSON strings the keys; the load undoes it
    (tmp_path / "old.json").write_text('{"version": 1, "weeks": []}')
    with pytest.raises(SystemExit, match="version 1, this code reads 2 .*player universe"):
        bt.load_replay(tmp_path / "old.json")


def test_the_synthetic_universe_holds_every_rostered_player_and_a_wire_with_every_week():
    rep = synthetic_replay(weeks=3, teams=4)
    rostered = {r["espn_id"] for wk in rep["weeks"] for m in wk["matchups"] for r in m["home_roster"] + m["away_roster"]}
    assert rostered <= set(rep["players"]) and rep["universe_missing"] == 0 and rep["universe_size"] == len(rep["players"])
    wire = [p for pid, p in rep["players"].items() if pid not in rostered]
    assert len(wire) == WIRE_PER_POS * len(PLAN) and {p["pos"] for p in wire} == {pos for pos, _, _ in PLAN}
    for p in rep["players"].values():
        assert sorted(p["weeks"]) == [1, 2, 3] and p["proj_season"] > 0
        assert all({"proj", "actual"} <= set(v) for v in p["weeks"].values())
    r = rep["weeks"][1]["matchups"][0]["home_roster"][0]                                 # the box score and the universe agree on his week
    assert rep["players"][r["espn_id"]]["weeks"][2] == {"proj": r["proj"], "actual": r["actual"]}


def test_a_player_without_a_stats_block_is_left_out_of_the_universe_and_counted():
    uni, size, missing = bt.universe([_up(1, "A", "RB", {1: {"projected_points": 3.0}}), _up(2, "B", "RB", None)], {1, 2, 3})
    assert (size, missing, sorted(uni)) == (2, 2, [1])                                    # B has no stats, 3 is beyond the pull
    assert uni[1]["weeks"] == {1: {"proj": 3.0}} and uni[1]["proj_season"] == 100.0
    assert bt.universe([], set()) == ({}, 0, 0)


def test_a_season_espn_serves_without_lineups_fails_with_the_finding_not_a_key_error():
    """2025 came back with scores and no roster on any week (2026-10-20); espn-api raises KeyError from inside its box
    score, and the pull names the season instead of a traceback. Any other KeyError is still a bug and still raises."""
    def no_rosters(w, player_team_cache=None):
        raise KeyError("rosterForCurrentScoringPeriod")
    settings = LeagueSettings(name="L", team_count=4, scoring={}, lineup_slots={"QB": 1}, bench_slots=5, ir_slots=1, reg_season_weeks=2,
                              playoff_team_count=2, playoff_weeks=[3], matchup_periods={1: [1], 2: [2]}, faab=False, faab_budget=0,
                              trade_deadline_ms=0, ppr=0.5)
    with patch.object(bt.espn, "settings", lambda ref, lg: settings):
        with pytest.raises(SystemExit, match=r"L1: ESPN serves no lineups for 2025 \(week 1 came back without a roster\)"):
            bt.pull_replay(LeagueRef(name="L1", espn_id=7), _P(current_week=17, box_scores=no_rosters), 2025)
        with pytest.raises(KeyError, match="somethingElse"):
            bt.pull_replay(LeagueRef(name="L1", espn_id=7), _P(current_week=17, box_scores=lambda w, player_team_cache=None: (_ for _ in ()).throw(KeyError("somethingElse"))), 2025)


# ---------- the scanner replay ----------

def shuffled(rep: dict, seed: int = 5) -> dict:
    """The same replay with every week's actuals shuffled across the players of a position: the projections then
    say nothing about who scores. The box scores and the recorded scores follow the universe."""
    rep = copy.deepcopy(rep)
    rng = random.Random(seed)
    by_pos = defaultdict(list)
    for p in rep["players"].values():
        by_pos[p["pos"]].append(p)
    for w in range(1, len(rep["weeks"]) + 1):
        for ps in by_pos.values():
            vals = [p["weeks"][w]["actual"] for p in ps]
            rng.shuffle(vals)
            for p, v in zip(ps, vals):
                p["weeks"][w]["actual"] = v
    _box_scores_from_universe(rep)
    return rep


def poisoned(rep: dict, week: int, sentinel: float = 999.0) -> dict:
    """The same replay with every actual from `week` on replaced by `sentinel`, in the universe and the box scores."""
    rep = copy.deepcopy(rep)
    for p in rep["players"].values():
        for w, v in p["weeks"].items():
            if w >= week:
                v["actual"] = sentinel
    _box_scores_from_universe(rep)
    return rep


def _box_scores_from_universe(rep: dict) -> None:
    for wk in rep["weeks"]:
        for m in wk["matchups"]:
            for side in ("home", "away"):
                for r in m[f"{side}_roster"]:
                    r["actual"] = rep["players"][r["espn_id"]]["weeks"][wk["week"]]["actual"]
                m[f"{side}_score"] = round(sum(r["actual"] for r in m[f"{side}_roster"] if r["slot"] in SLOTS), 2)


def _pooled_scan(bins: list[dict], lo: float) -> tuple[int, float, float, float]:
    """(n, hit, promised, realized) over the promised bins at or above `lo`."""
    sel = [b for b in bins if b["lo"] >= lo and b["n"]]
    n = sum(b["n"] for b in sel)
    return (n, sum(b["hit"] * b["n"] for b in sel) / n, sum(b["pred_mean"] * b["n"] for b in sel) / n,
            sum(b["realized_mean"] * b["n"] for b in sel) / n)


SCAN_REPLAY = dict(weeks=7, teams=6, seed=3, fit=5.0)


@pytest.fixture(scope="module")
def scanned():
    """The scanner replay of the model's own draw, once for the edge tests (six teams over seven weeks with a fit
    trade on every roster is a few hundred packages and a minute)."""
    return bt.scan_hits(synthetic_replay(**SCAN_REPLAY), sims=200)


def test_scan_hits_on_the_models_own_draw_reads_edge_and_the_realized_mean_tracks_the_promise(scanned):
    res = scanned
    assert res["weeks"] == [1, 2, 3, 4, 5, 6] and res["through"] == 7 and res["sims"] == 200 and res["chart"] == bt.CHART_OFF
    assert res["team_weeks"] > 12 and res["candidates"] >= 80
    every = res["all"]["every"]
    assert every["n"] == res["candidates"] and every["unscored"] == 0
    assert sum(b["n"] for b in every["bins"]) == every["n"] and [b["lo"] for b in every["bins"]] == [lo for lo, _ in bt.SCAN_BINS]
    n, hit, pred, realized = _pooled_scan(every["bins"], 1.0)   # the rows the card would send (SEND_MIN_PPW is 1)
    assert n >= 60 and hit > 0.6                                  # well above a coin flip
    assert abs(realized - pred) < 1.0                            # and the promise is the right size, within this n's noise
    assert every["realized_raw_mean"] > every["realized_mean"]    # the raw delta counts bench points; the lineup one is the forecast
    top = res["top3"]["every"]
    assert 0 < top["n"] <= res["team_weeks"] * bt.TOP_PER_TEAM_WEEK and top["hit"] > 0.6
    assert res["all"]["touches_zero"]["n"] == 0 and res["all"]["clean"] == every   # no designation in the synthetic season


def test_scan_hits_on_shuffled_actuals_reads_no_edge(scanned):
    """A harness that finds edge where the projections carry none is leaking an actual into the pricing."""
    res = bt.scan_hits(shuffled(synthetic_replay(**SCAN_REPLAY)), sims=200)
    every = res["all"]["every"]
    assert every["n"] >= 100                                       # the pricing still proposes (its season to date is noise now)
    assert 0.35 < every["hit"] < 0.65
    # Under half a point realized anywhere: no edge. The mean sits under zero rather than at it because a 2-for-1 leaves
    # fewer bodies to draw a lineup from when every actual is an exchangeable draw, and consolidations are what the scan
    # proposes; that is the shape of the shuffled world, not a leak.
    assert every["realized_mean"] < 0.5
    for b in every["bins"]:
        if b["n"] >= 20:
            assert b["realized_mean"] < 1.0
    assert every["pred_mean"] > 0.75                               # the promise is still the scan's floor or more; the grade is what moved


def test_a_week_w_package_never_reads_a_week_w_or_later_actual():
    rep = synthetic_replay(**SCAN_REPLAY)
    clean = bt.scan_week(rep, 3, 8, sims=100)
    assert len(clean) >= 5
    bad = bt.scan_week(poisoned(rep, 3), 3, 8, sims=100)
    key = lambda c: (c["team"], c["rival_team_id"], tuple(c["give_ids"]), tuple(c["get_ids"]), c["my_delta_ppw"], c["their_delta_ppw"], c["p_accept"])
    assert [key(c) for c in clean] == [key(c) for c in bad]
    earlier = bt.scan_week(poisoned(rep, 2), 3, 8, sims=100)   # the week-2 actuals are the season to date and the record: they count
    assert [c["my_delta_ppw"] for c in earlier] != [c["my_delta_ppw"] for c in clean] or [key(c)[:4] for c in earlier] != [key(c)[:4] for c in clean]


def _uni(pid, pos, weeks, total=85.0, byes=()):
    return {"espn_id": pid, "name": f"U{pid}", "pos": pos, "team": "X", "eligible": [pos, "RB/WR/TE"], "proj_season": total,
            "bye_weeks": list(byes), "weeks": weeks}


def test_replay_proj_prices_the_season_to_date_from_the_universe_and_a_zero_week_as_out_this_week():
    uni = {7: _uni(7, "RB", {1: {"proj": 10.0, "actual": 20.0}, 2: {"proj": 11.0, "actual": 0.0}, 3: {"proj": 12.0, "actual": 30.0}, 4: {"proj": 9.0}})}
    row = {"espn_id": 7, "name": "U7", "pos": "RB", "team": "X", "eligible": ["RB", "RB/WR/TE"], "slot": "RB", "proj": 12.0, "actual": 30.0, "bye": False}
    assert bt.season_to_date(uni[7], 3) == (20.0, 2) and bt.season_to_date(uni[7], 1) == (0.0, 0) and bt.season_to_date(None, 3) == (0.0, 0)
    p = bt.replay_proj(row, uni, 3, 5, team_id=4)
    assert (p.mu, p.fantasy_team_id, p.slot, p.weeks_out, p.p_zero) == (12.0, 4, "RB", 0.0, 0.02)
    assert p.sources["games_played"] == 2 and p.sources["ytd_pg"] == 10.0            # the week-3 actual (30) is not in it
    level = 4 / 6 * 5.0 + 2 / 6 * 10.0                                               # the prior (85/17 a game) fading over PRIOR_FADE_GAMES
    assert p.mu_ros_active == pytest.approx(0.5 * level + 0.5 * 12.0, abs=0.02)      # shrunk to this week's number, as live
    zero = bt.replay_proj({**row, "proj": 0.0}, uni, 3, 5)
    assert zero.p_zero == 1.0 and zero.weeks_out == 1.0 and zero.return_week == 4 and "replay:zero" in zero.flags and "llm:weeks_out" not in zero.flags
    assert zero.mu_ros_active == pytest.approx(level, abs=0.02) and zero.mu_ros == pytest.approx(level * 4 / 5, abs=0.02)
    bye = bt.replay_proj({**row, "proj": 0.0, "bye": True}, uni, 3, 5)
    assert bye.bye and bye.p_zero == 1.0 and bye.weeks_out == 0.0 and 3 in bye.bye_weeks
    alone = bt.replay_proj(row, {}, 3, 5)                                             # beyond the universe pull: this week's number alone
    assert alone.mu == 12.0 and alone.mu_ros == 12.0 and alone.sources["games_played"] == 0 and alone.bye_weeks == []
    wire = bt.pool_row(_uni(8, "WR", {3: {"proj": 6.5}}, byes=[4]), 3)
    assert wire == {"espn_id": 8, "name": "U8", "pos": "WR", "team": "X", "eligible": ["WR", "RB/WR/TE"], "slot": "", "proj": 6.5, "bye": False}
    assert bt.pool_row(_uni(8, "WR", {3: {"proj": 6.5}}, byes=[4]), 4)["bye"] is True and bt.pool_row(_uni(9, "TE", {}), 2)["proj"] == 0.0


def _two_team_replay() -> dict:
    """Two teams, one RB slot, three weeks: A (10) and B (5) on team 1, C (12) on team 2, with the actuals set by hand."""
    def row(pid, proj, slot, actual):
        return {"espn_id": pid, "name": f"U{pid}", "pos": "RB", "team": "X", "eligible": ["RB"], "slot": slot, "proj": proj, "actual": actual, "bye": False}
    weeks = []
    for w, (a, b, c) in enumerate(((10.0, 2.0, 15.0), (8.0, 9.0, 1.0), (12.0, 3.0, 20.0)), 1):
        weeks.append({"week": w, "first_kickoff": f"2025-09-{w:02d}",
                      "matchups": [{"home": 1, "away": 2, "home_score": a, "away_score": c, "playoff": False,
                                    "home_roster": [row(1, 10.0, "RB", a), row(2, 5.0, "BE", b)],
                                    "away_roster": [row(3, 12.0, "RB", c)] + ([row(5, 3.0, "BE", 1.0)] if w == 1 else [])}]})   # U5: cut after week 1, beyond the universe
    weeks[1]["matchups"][0]["home_roster"][1]["proj"] = 11.0   # week 2: B projects over A, so the seat goes to B
    uni = {1: _uni(1, "RB", {1: {"proj": 10.0, "actual": 10.0}, 2: {"proj": 10.0, "actual": 8.0}, 3: {"proj": 10.0, "actual": 12.0}}),
           2: _uni(2, "RB", {1: {"proj": 5.0, "actual": 2.0}, 2: {"proj": 11.0, "actual": 9.0}, 3: {"proj": 5.0, "actual": 3.0}}),
           3: _uni(3, "RB", {1: {"proj": 12.0, "actual": 15.0}, 2: {"proj": 12.0, "actual": 1.0}, 3: {"proj": 12.0, "actual": 20.0}}),
           4: _uni(4, "RB", {1: {"proj": 4.0, "actual": 4.0}, 2: {"proj": 4.0, "actual": 4.0}, 3: {"proj": 4.0}}, byes=[3])}
    return {"version": bt.REPLAY_VERSION, "season": 2025, "league": "two", "pulled": "2026-10-20",
            "settings": {"name": "Two", "team_count": 2, "lineup_slots": {"RB": 1}, "ppr": 1.0, "reg_season_weeks": 3, "playoff_weeks": [],
                         "playoff_team_count": 1, "bench_slots": 1, "position_limits": {}},
            "skipped_weeks": [], "weeks": weeks, "universe_size": 4, "universe_missing": 1, "players": uni}


def test_standings_and_the_schedule_stop_at_the_week_and_the_record_feeds_the_sim():
    rep = _two_team_replay()
    assert bt.standings_at(rep, 1) == {1: (0, 0, 0.0), 2: (0, 0, 0.0)}
    assert bt.standings_at(rep, 3) == {1: (1, 1, 18.0), 2: (1, 1, 16.0)}           # weeks 1 and 2 only
    assert bt.schedule_after(rep, 1, 3) == [[(1, 2)], [(1, 2)]] and bt.schedule_after(rep, 3, 3) == []
    rosters = {1: [bt.replay_proj(r, rep["players"], 2, 2, 1) for r in rep["weeks"][1]["matchups"][0]["home_roster"]],
               2: [bt.replay_proj(r, rep["players"], 2, 2, 2) for r in rep["weeks"][1]["matchups"][0]["away_roster"]]}
    odds = bt.playoff_odds(rep, 2, rosters, sims=200)
    assert set(odds) == {1, 2} and odds[1] + odds[2] == pytest.approx(100.0, abs=0.1)
    assert bt.playoff_odds({**rep, "settings": {**rep["settings"], "playoff_team_count": None}}, 2, rosters) is None
    proj, actual = bt.by_week(rep)
    assert actual[2] == {1: 2.0, 2: 9.0, 3: 3.0} and proj[2][2] == 11.0 and actual[4] == {1: 4.0, 2: 4.0, 3: 0.0}   # the bye week is a zero, not missing
    assert 3 not in actual.get(5, {})


def test_score_packages_seats_each_later_week_on_its_projection_and_scores_it_on_its_actual():
    rep = _two_team_replay()
    c = {"week": 1, "team": 1, "rank": 1, "rival_team_id": 2, "give": ["U2"], "get": ["U3"], "give_ids": [2], "get_ids": [3], "drops": [],
         "my_delta_ppw": 2.0, "wire_ids": [4]}
    out = bt.score_packages(rep, [c])[0]
    # raw: week 2: C 1 - B 9 = -8; week 3: C 20 - B 3 = +17 -> +4.5
    # lineup: before = {A, B, wire D}, after = {A, C, D}. Week 2: before seats B (proj 11) -> 9; after seats C (12) -> 1: -8.
    #         Week 3: before seats A (10) -> 12; after seats C (12) -> 20: +8. Mean 0.0.
    assert (out["weeks"], out["missing"], out["realized_ppw"], out["realized_lineup_ppw"], out["hit"]) == (2, 0, 4.5, 0.0, False)
    gone = bt.score_packages(rep, [{**c, "get_ids": [5], "get": ["U5"]}])[0]
    assert (gone["weeks"], gone["missing"], gone["realized_lineup_ppw"], gone["hit"]) == (0, 2, None, None)   # no actual after week 1: missing, not zero
    drop = bt.score_packages(rep, [{**c, "give_ids": [], "give": [], "drops": ["U1"]}])[0]      # a cap drop leaves with the trade
    # before as above; after = {B, C, D}. Week 2: C (12) -> 1 vs 9: -8. Week 3: C -> 20 vs A 12: +8. Mean 0.0; raw = C alone: 10.5
    assert (drop["realized_ppw"], drop["realized_lineup_ppw"]) == (10.5, 0.0)
    assert bt.score_packages(rep, [{**c, "week": 3}])[0]["weeks"] == 0                         # the last week has nothing after it


def test_scan_table_bins_on_the_promise_and_counts_the_unscored():
    rows = [{"my_delta_ppw": 0.8, "realized_lineup_ppw": 1.0, "realized_ppw": 3.0, "hit": True},
            {"my_delta_ppw": 1.5, "realized_lineup_ppw": -2.0, "realized_ppw": -1.0, "hit": False},
            {"my_delta_ppw": 2.0, "realized_lineup_ppw": 4.0, "realized_ppw": 6.0, "hit": True},
            {"my_delta_ppw": 4.0, "realized_lineup_ppw": 5.0, "realized_ppw": 5.0, "hit": True},
            {"my_delta_ppw": 9.0, "realized_lineup_ppw": None, "realized_ppw": None, "hit": None}]
    t = bt.scan_table(rows)
    assert (t["n"], t["unscored"], t["hit"], t["pred_mean"], t["realized_mean"], t["realized_raw_mean"]) == (4, 1, 0.75, 2.08, 2.0, 3.25)
    assert [(b["lo"], b["hi"], b["n"], b["hit"], b["realized_mean"]) for b in t["bins"]] == [(0.0, 1.0, 1, 1.0, 1.0), (1.0, 2.0, 1, 0.0, -2.0), (2.0, 4.0, 1, 1.0, 4.0), (4.0, None, 1, 1.0, 5.0)]
    empty = bt.scan_table([])
    assert empty["n"] == 0 and empty["hit"] is None and all(b["n"] == 0 for b in empty["bins"])


def test_scan_hits_on_a_replay_with_one_week_or_only_playoff_weeks_scores_nothing():
    rep = synthetic_replay(weeks=1, teams=4)
    res = bt.scan_hits(rep)
    assert res["weeks"] == [] and res["candidates"] == 0 and res["through"] is None and res["all"]["every"]["n"] == 0
    rep = synthetic_replay(weeks=2, teams=4)
    rep["settings"]["reg_season_weeks"] = 1                                       # week 2 is a playoff week: nothing regular to grade
    assert bt.scan_hits(rep)["candidates"] == 0


# ---------- the claim rows (D12 step 4) ----------

@pytest.fixture(scope="module")
def claimed():
    """The claim replay of the model's own draw, once: the same six teams over seven weeks as `scanned`."""
    return bt.claim_hits(synthetic_replay(**SCAN_REPLAY))


def test_claim_hits_on_the_models_own_draw_reads_edge_and_the_realized_mean_tracks_the_promise(claimed):
    res = claimed
    assert res["weeks"] == [1, 2, 3, 4, 5, 6] and res["through"] == 7 and res["trending"] == bt.TRENDING_OFF
    assert res["team_weeks"] == 36 and res["rows"] >= 500
    every = res["all"]["every"]
    assert every["n"] == res["rows"] and every["unscored"] == 0
    assert sum(b["n"] for b in every["bins"]) == every["n"] and [b["lo"] for b in every["bins"]] == [lo for lo, _ in bt.CLAIM_BINS]
    worthy = res["claim_worthy"]["every"]                        # the rows `priority_cost` prices live
    assert worthy["n"] >= 300 and worthy["hit"] > 0.7            # well above a coin flip
    assert abs(worthy["realized_mean"] - worthy["pred_mean"]) < 1.0   # and the promise is the right size
    assert all(b["n"] == 0 for b in worthy["bins"] if b["hi"] is not None and b["hi"] <= bt.CLAIM_WORTHY_PPW)
    top = res["top1"]["every"]                                   # the card's first claim per team-week
    assert top["n"] == res["team_weeks"] and top["hit"] > 0.8 and top["realized_mean"] > worthy["realized_mean"]
    wk = worthy["week"]                                           # the START NOW rows on their one-week promise
    assert wk["n"] >= 100 and wk["hit"] > 0.6 and abs(wk["realized_mean"] - wk["pred_mean"]) < 1.5
    assert res["all"]["touches_zero"]["n"] == 0 and res["all"]["clean"] == every   # no designation in the synthetic season
    assert res["adds"]["n"] == 0 and res["adds"]["unpriced"] == 0                  # the synthetic rosters persist: nobody adds


def test_claim_hits_on_shuffled_actuals_reads_no_edge():
    """A harness that finds edge where the projections carry none is leaking an actual into the pricing. The displaced
    starter's draw is shared by every row at his slot that week, so the mean wanders a point either side of zero
    across shuffle seeds; the test holds it to no edge against a promise of three or more."""
    rep = shuffled(synthetic_replay(**SCAN_REPLAY))
    rows = []
    for w in range(1, 7):
        rows += bt.claim_week(rep, w, 7)
    bt.score_claims(rep, rows, 7)
    t = bt.claim_table([c for c in rows if c["claim_worthy"]])
    assert t["n"] >= 300 and 0.4 < t["hit"] < 0.6
    assert t["pred_mean"] > 3.0 and t["realized_mean"] < 1.0
    assert t["week"]["n"] >= 100 and t["week"]["pred_mean"] > 3.0 and t["week"]["realized_mean"] < 1.0
    # Within a position every actual is an exchangeable draw, so the claimed body over the starter he displaces is zero
    # in expectation whoever is picked; across positions (a RB over the TE in the flex) it is not, which is the shape
    # of the shuffled world, not a leak.
    same = [c for c in rows if c["starter_id"] is not None and rep["players"][c["starter_id"]]["pos"] == c["pos"]]
    s = bt.claim_table(same)
    assert s["n"] >= 1000 and 0.4 < s["hit"] < 0.6 and abs(s["realized_mean"]) < 1.0


def test_a_week_w_claim_row_never_reads_a_week_w_or_later_actual():
    rep = synthetic_replay(**SCAN_REPLAY)
    clean = bt.claim_week(rep, 3, 8)
    assert len(clean) >= 50
    bad = bt.claim_week(poisoned(rep, 3), 3, 8)
    key = lambda c: (c["team"], c["espn_id"], c["rank"], c["delta_over_starter"], c["slot"], c["starter_id"], c["delta_week"], c["week_slot"], c["week_starter_id"])
    assert [key(c) for c in clean] == [key(c) for c in bad]
    earlier = bt.claim_week(poisoned(rep, 2), 3, 8)   # the week-2 actuals are the season to date: they count
    assert [key(c) for c in earlier] != [key(c) for c in clean]


def test_score_claims_reads_the_weeks_after_against_the_fixed_starter_and_the_week_itself_for_start_now():
    rep = _two_team_replay()
    row = {"week": 1, "team": 1, "espn_id": 3, "starter_id": 2, "delta_over_starter": 2.0, "start_now": True, "week_starter_id": 1, "delta_week": 2.0}
    out = bt.score_claims(rep, [dict(row)])[0]
    # weeks 2 and 3: C - B = 1 - 9, 20 - 3 -> +4.5; week 1: C 15 - A 10 = +5
    assert (out["weeks"], out["missing"], out["realized_over_starter"], out["hit"], out["realized_week"], out["hit_week"]) == (2, 0, 4.5, True, 5.0, True)
    cut = bt.score_claims(rep, [{**row, "starter_id": 5}])[0]                 # U5 has no actual after week 1: missing, not zero
    assert (cut["weeks"], cut["missing"], cut["realized_over_starter"], cut["hit"]) == (0, 2, None, None)
    seat = bt.score_claims(rep, [{**row, "week_starter_id": None}])[0]        # an empty seat scores zero: his whole week counts
    assert seat["realized_week"] == 15.0
    later = bt.score_claims(rep, [{**row, "start_now": False, "delta_over_starter": -2.0}])[0]
    assert (later["realized_week"], later["hit_week"], later["hit"]) == (None, None, False)   # +4.5 against a promise under zero
    assert bt.score_claims(rep, [{**row, "week": 3}])[0]["weeks"] == 0        # the last week has nothing after it


def test_adds_week_prices_the_managers_add_as_a_claim_row_and_counts_one_beyond_the_universe():
    rep = _two_team_replay()
    assert bt.adds_week(rep, 1, 4) == ([], 0)                                 # nobody added anyone
    home2 = rep["weeks"][1]["matchups"][0]["home_roster"]
    home2.append({"espn_id": 4, "name": "U4", "pos": "RB", "team": "X", "eligible": ["RB"], "slot": "BE", "proj": 4.0, "actual": 4.0, "bye": False})
    home2.append({"espn_id": 9, "name": "U9", "pos": "RB", "team": "X", "eligible": ["RB"], "slot": "BE", "proj": 4.0, "actual": 4.0, "bye": False})
    adds, unpriced = bt.adds_week(rep, 1, 4)
    assert unpriced == 1 and [(a["team"], a["espn_id"], a["rank"], a["slot"], a["starter_id"]) for a in adds] == [(1, 4, None, "RB", 1)]
    a = adds[0]
    assert a["delta_over_starter"] < 0 and not a["claim_worthy"] and not a["start_now"] and a["week_starter_id"] is None
    bt.score_claims(rep, adds, 4)
    # week 2: U4 4 - A 8; week 3: U4 on bye (zero) - A 12 -> -8.0, the sign the promise had
    assert (a["weeks"], a["realized_over_starter"], a["hit"]) == (2, -8.0, True)
    assert bt.adds_week(rep, 3, 4) == ([], 0)                                 # the last week has no next one


def test_claim_table_bins_on_the_promise_and_reads_the_start_now_rows_apart():
    rows = [{"delta_over_starter": -1.0, "realized_over_starter": -2.0, "hit": True, "delta_week": 2.0, "realized_week": 3.0, "hit_week": True},
            {"delta_over_starter": 0.5, "realized_over_starter": 1.0, "hit": True, "delta_week": 0.0, "realized_week": None, "hit_week": None},
            {"delta_over_starter": 1.5, "realized_over_starter": -2.0, "hit": False, "delta_week": 4.0, "realized_week": -1.0, "hit_week": False},
            {"delta_over_starter": 2.0, "realized_over_starter": 4.0, "hit": True, "delta_week": 0.0, "realized_week": None, "hit_week": None},
            {"delta_over_starter": 4.0, "realized_over_starter": 5.0, "hit": True, "delta_week": 0.0, "realized_week": None, "hit_week": None},
            {"delta_over_starter": 9.0, "realized_over_starter": None, "hit": None, "delta_week": 0.0, "realized_week": None, "hit_week": None}]
    t = bt.claim_table(rows)
    assert (t["n"], t["unscored"], t["hit"], t["pred_mean"], t["realized_mean"]) == (5, 1, 0.8, 1.4, 1.2)
    assert [(b["lo"], b["hi"], b["n"], b["hit"], b["realized_mean"]) for b in t["bins"]] == [
        (None, 0.0, 1, 1.0, -2.0), (0.0, 1.0, 1, 1.0, 1.0), (1.0, 2.0, 1, 0.0, -2.0), (2.0, 4.0, 1, 1.0, 4.0), (4.0, None, 1, 1.0, 5.0)]
    assert t["week"] == {"n": 2, "hit": 0.5, "pred_mean": 3.0, "realized_mean": 1.0}
    empty = bt.claim_table([])
    assert empty["n"] == 0 and empty["hit"] is None and empty["week"]["n"] == 0 and all(b["n"] == 0 for b in empty["bins"])


def test_claim_hits_on_a_replay_with_one_week_scores_nothing():
    res = bt.claim_hits(synthetic_replay(weeks=1, teams=4))
    assert res["weeks"] == [] and res["rows"] == 0 and res["through"] is None and res["all"]["every"]["n"] == 0 and res["adds"]["n"] == 0
