"""End-to-end over a synthetic league snapshot: analyze_league -> report.render, no network."""
import random

from ff import report
from ff.packet import analyze_league


class FakeXW:
    unmatched = []
    def fp_row(self, idx, espn_id, name, pos):
        return {"r2p_pts": None, "sd": 2.0, "ecr": 10, "start_sit_grade": "B"}
    def lookup(self, espn_id, name="", pos=""):
        return {"gsis_id": f"g{espn_id}"}
    def sleeper_id(self, espn_id, name="", pos=""):
        return None


def make_snapshot(teams=8):
    rng = random.Random(1)
    slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "K": 1, "D/ST": 1}
    roster, pid = [], 100
    for tid in range(1, teams + 1):
        plan = [("QB", 2), ("RB", 4), ("WR", 4), ("TE", 2), ("K", 1), ("D/ST", 1)]
        for pos, n in plan:
            for i in range(n):
                base = {"QB": 18, "RB": 12, "WR": 11, "TE": 7, "K": 8, "D/ST": 7}[pos]
                mu = max(base + rng.gauss(0, 4) - 3 * i, 1)
                elig = [pos] + (["RB/WR/TE"] if pos in ("RB", "WR", "TE") else [])
                slot = pos if i < slots.get(pos, 0) else "BE"
                roster.append({"espn_id": pid, "name": f"{pos}{tid}_{i}", "pos": pos, "team": rng.choice(["GB", "KC", "DAL"]),
                               "eligible": elig, "slot": slot, "fantasy_team_id": tid, "injury_status": rng.choice([None, "ACTIVE", "QUESTIONABLE"]),
                               "proj_week": round(mu, 1), "actual_week": 0, "proj_season": round(mu * 16, 1), "percent_owned": 90.0,
                               "pos_rank": i + 1, "bye": False})
                pid += 1
    fas = []
    for i in range(40):
        pos = rng.choice(["RB", "WR", "TE", "QB", "K", "D/ST"])
        mu = max(rng.gauss(6, 3), 0.5)
        fas.append({"espn_id": pid, "name": f"FA_{pos}_{i}", "pos": pos, "team": "GB", "eligible": [pos] + (["RB/WR/TE"] if pos in ("RB", "WR", "TE") else []),
                    "slot": "FA", "fantasy_team_id": None, "injury_status": None, "proj_week": round(mu, 1), "actual_week": 0,
                    "proj_season": round(mu * 16, 1), "percent_owned": 20.0, "pos_rank": 30, "bye": False})
        pid += 1
    ids = list(range(1, teams + 1))
    sched = {t: [] for t in ids}
    for w in range(14):
        order = ids[:]; rng.shuffle(order)
        for a, b in zip(order[::2], order[1::2]):
            sched[a].append(b); sched[b].append(a)
    team_rows = [{"team_id": t, "name": f"Team {t}", "abbrev": f"T{t}", "owners": [], "wins": rng.randint(0, 1), "losses": 0, "ties": 0,
                  "points_for": rng.uniform(80, 130), "points_against": 100, "faab_spent": rng.randint(0, 30), "waiver_rank": t,
                  "streak": "W1", "seed": t, "espn_playoff_pct": 50, "schedule": sched[t], "scores": [], "outcomes": [], "is_me": t == 1} for t in ids]
    team_rows[0]["losses"] = 2
    matchups = [{"home": 1, "away": sched[1][1], "home_proj": None, "away_proj": None}]
    by_name = {r["name"]: r["espn_id"] for r in roster}
    return {
        "ref": {"name": "synth", "espn_id": 1}, "week": 2, "my_team_id": 1, "teams": team_rows, "matchups": matchups,
        "settings": {"name": "Synthetic League", "team_count": teams, "scoring": {"REC": 1.0}, "lineup_slots": slots, "bench_slots": 6, "ir_slots": 1,
                     "reg_season_weeks": 14, "playoff_team_count": 4, "playoff_weeks": [15, 16], "matchup_periods": {i: [i] for i in range(1, 17)},
                     "faab": True, "faab_budget": 100, "trade_deadline_ms": 0, "ppr": 1.0},
        "roster": roster, "free_agents": fas, "faab_bids": [],
        # one incoming 2-for-1 from team 2 (their best RB for my RB2 + WR2), one offer I sent to team 3
        "pending_trades": [
            {"id": "in-1", "proposer_team_id": 2, "rival_team_id": 2, "proposed_ts": 1789500000000, "expires_ts": 1789672800000,
             "status": "PENDING", "team_actions": {"2": "ACCEPTED"}, "direction": "incoming",
             "give": [by_name["RB1_1"], by_name["WR1_1"]], "get": [by_name["RB2_0"]]},
            {"id": "out-1", "proposer_team_id": 1, "rival_team_id": 3, "proposed_ts": 1789500000000, "expires_ts": 1789672800000,
             "status": "PENDING", "team_actions": {"1": "ACCEPTED"}, "direction": "outgoing",
             "give": [by_name["TE1_1"]], "get": [by_name["TE3_0"]]},
        ],
        "pending_trades_error": None,
    }


def test_end_to_end_synthetic(monkeypatch):
    monkeypatch.setattr("ff.packet.fantasycalc.by_espn_id", lambda **kw: {})
    snap = make_snapshot()
    blk = analyze_league(snap, FakeXW(), {}, {}, {}, {}, overrides=None, sims=300)
    assert blk["my_team_id"] == 1
    assert sum(len(v) for v in blk["lineup_win"]["slots"].values()) == 9
    assert blk["lineup_win"]["p_win"] is not None
    assert abs(sum(o["title_pct"] for o in blk["odds"].values()) - 100) < 2
    assert blk["waivers"] and all(w["bid"] <= blk["faab_remaining"] for w in blk["waivers"])
    packet = {"version": 3, "generated": "2026-09-10T07:00:00", "season": 2026,
              "shared": {"injury_watchlist": [], "exposure": {}, "trending_adds": [], "usage_error": None, "unmatched_ids": []},
              "leagues": [blk]}
    md = report.render(packet)
    assert "Synthetic League" in md and "## Waivers" in md and "## League odds" in md and "Lineup" in md
    # incoming offer: evaluated, first in the checklist, outgoing listed separately
    inc = blk["incoming_trades"]
    assert len(inc) == 1 and inc[0]["verdict"] in ("accept", "decline", "counter") and inc[0]["rival"] == "Team 2"
    assert inc[0]["give"] == ["RB1_1", "WR1_1"] and inc[0]["get"] == ["RB2_0"] and "my_title_delta" in inc[0]
    assert len(blk["outgoing_trades"]) == 1 and blk["outgoing_trades"][0]["rival"] == "Team 3"
    first = report.todos(blk)[0]
    assert first["kind"] == "trade_in" and "Team 2 offers RB2_0 for your RB1_1, WR1_1" in first["text"]
    assert "## Incoming offers" in md and "Your open offers" in md
    short = report.render(packet, reads={"synth": {"reply": "thanks but no", "reply_to": "Team 2"}}, only_incoming=True)
    assert short.startswith("# FF trade offer") and "Reply to Team 2" in short and "## Waivers" not in short
    # overrides flow through
    pid = str(blk["roster"][0]["espn_id"])
    blk2 = analyze_league(snap, FakeXW(), {}, {}, {}, {}, overrides={pid: {"p_zero": 1.0}}, sims=100)
    assert blk2["roster"][-1]["espn_id"] == int(pid) or any(r["espn_id"] == int(pid) and r["p_zero"] == 1.0 for r in blk2["roster"])
