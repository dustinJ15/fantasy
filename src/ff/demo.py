"""A synthetic 8-team league so the whole pipeline runs with no ESPN account, no cookies and no network.

`ff briefing --demo` / `ff packet --demo` / `ff incoming --demo` build a packet from `make_snapshot()` instead of ESPN.
The tests use the same fixture. Every player and team name is made up (seeded, so the output is stable); everything else is real code.
"""
from __future__ import annotations

import json
import random
import time
from datetime import date, datetime
from unittest.mock import patch

from .config import PACKET_DIR
from .packet import PACKET_VERSION, analyze_league, fantasycalc

# Fictional people and fictional franchises. Any resemblance to a real player is a coincidence and a bad omen.
FIRST = ["Marcus", "Dontae", "Kellen", "Jalen", "Trey", "Deshawn", "Cole", "Rashad", "Tyrek", "Amari", "Brody", "Darius", "Zeke",
         "Malik", "Cam", "Isaiah", "Tanner", "Jaxon", "Kwame", "Rico", "Devin", "Elias", "Terrell", "Nico", "Grady", "Omar", "Landon",
         "Xavier", "Quincy", "Beau", "Josiah", "Andre", "Miles", "Reggie", "Tobias", "Wes", "Kai", "Jermaine", "Silas", "Deon"]
LAST = ["Vell", "Ruiz-Hollis", "Okafor", "Brandt", "Castellano", "Whitlock", "Mbeki", "Sorensen", "Delacroix", "Haggerty", "Pruitt",
        "Nakamura", "Osei", "Fairweather", "Lindqvist", "Booker", "Tremblay", "Achebe", "Kowalczyk", "Rutherford", "Saldana", "Igwe",
        "Marchetti", "Holloway", "Bassett", "Duquesne", "Farrow", "Oyelaran", "Stroud", "Vanterpool", "Ketchum", "Abernathy",
        "Solano", "Whitfield", "Grantham", "Ibarra", "Tolliver", "McCrae", "Pennington", "Danforth"]
TEAMS = ["Regression to the Mean", "The Tuesday Regrets", "Waiver Wire Widows", "Bye Week Blues", "Gronk's Ghost",
         "Ctrl+Alt+Delete Kelce", "Sunday Scaries", "Punt Return Policy"]
DST = ["Packers", "Chiefs", "Cowboys", "Bills", "Ravens", "Eagles", "49ers", "Lions", "Steelers", "Broncos", "Texans", "Seahawks",
       "Dolphins", "Bengals", "Chargers", "Vikings", "Rams", "Buccaneers", "Jets", "Falcons", "Bears", "Browns", "Colts", "Saints"]


class FakeCrosswalk:
    """Stands in for ids.Crosswalk: no FantasyPros rows, no Sleeper ids, nothing unmatched."""
    unmatched: list = []

    def fp_row(self, idx, espn_id, name, pos):
        return {"r2p_pts": None, "sd": 2.0, "ecr": 10, "start_sit_grade": "B"}

    def lookup(self, espn_id, name="", pos=""):
        return {"gsis_id": f"g{espn_id}"}

    def sleeper_id(self, espn_id, name="", pos=""):
        return None


def make_snapshot(teams: int = 8, seed: int = 1) -> dict:
    """The same shape `sources.espn.snapshot()` returns, with deterministic fake rosters, schedule and two pending trades."""
    rng = random.Random(seed)
    slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "K": 1, "D/ST": 1}
    names = [f"{fn} {ln}" for fn in FIRST for ln in LAST]
    rng.shuffle(names)
    dsts = DST[:]

    def name_for(pos: str) -> str:
        return f"{dsts.pop(0)} D/ST" if pos == "D/ST" else names.pop()

    now_ms = int(time.time() * 1000)  # the offer must still be open whenever the demo runs
    roster, pid = [], 100
    for tid in range(1, teams + 1):
        plan = [("QB", 2), ("RB", 4), ("WR", 4), ("TE", 2), ("K", 1), ("D/ST", 1)]
        for pos, n in plan:
            for i in range(n):
                base = {"QB": 18, "RB": 12, "WR": 11, "TE": 7, "K": 8, "D/ST": 7}[pos]
                mu = max(base + rng.gauss(0, 4) - 3 * i, 1)
                elig = [pos] + (["RB/WR/TE"] if pos in ("RB", "WR", "TE") else [])
                slot = pos if i < slots.get(pos, 0) else "BE"
                team = rng.choice(["GB", "KC", "DAL"])
                roster.append({"espn_id": pid, "name": name_for(pos), "pos": pos, "team": team,
                               "eligible": elig, "slot": slot, "fantasy_team_id": tid, "injury_status": rng.choice([None, "ACTIVE", "QUESTIONABLE"]),
                               "proj_week": round(mu, 1), "actual_week": 0, "proj_season": round(mu * 16, 1), "percent_owned": 90.0,
                               "pos_rank": i + 1, "bye": False})
                pid += 1
    fas = []
    for _ in range(40):
        pos = rng.choice(["RB", "WR", "TE", "QB", "K", "D/ST"])
        mu = max(rng.gauss(6, 3), 0.5)
        fas.append({"espn_id": pid, "name": name_for(pos), "pos": pos, "team": "GB", "eligible": [pos] + (["RB/WR/TE"] if pos in ("RB", "WR", "TE") else []),
                    "slot": "FA", "fantasy_team_id": None, "injury_status": None, "proj_week": round(mu, 1), "actual_week": 0,
                    "proj_season": round(mu * 16, 1), "percent_owned": 20.0, "pos_rank": 30, "bye": False})
        pid += 1
    ids = list(range(1, teams + 1))
    sched = {t: [] for t in ids}
    for _ in range(14):
        order = ids[:]
        rng.shuffle(order)
        for a, b in zip(order[::2], order[1::2]):
            sched[a].append(b)
            sched[b].append(a)
    team_rows = [{"team_id": t, "name": TEAMS[(t - 1) % len(TEAMS)], "abbrev": f"T{t}", "owners": [], "wins": rng.randint(0, 1), "losses": 0, "ties": 0,
                  "points_for": rng.uniform(80, 130), "points_against": 100, "faab_spent": rng.randint(0, 30), "waiver_rank": t,
                  "streak": "W1", "seed": t, "espn_playoff_pct": 50, "schedule": sched[t], "scores": [], "outcomes": [], "is_me": t == 1} for t in ids]
    team_rows[0]["losses"] = 2
    matchups = [{"home": 1, "away": sched[1][1], "home_proj": None, "away_proj": None}]

    def pick(tid: int, pos: str, i: int) -> int:
        """espn_id of fantasy team `tid`'s i-th best player at `pos`."""
        return [r for r in roster if r["fantasy_team_id"] == tid and r["pos"] == pos][i]["espn_id"]
    return {
        "ref": {"name": "demo", "espn_id": 1}, "week": 2, "my_team_id": 1, "teams": team_rows, "matchups": matchups,
        "settings": {"name": "Demo League", "team_count": teams, "scoring": {"REC": 1.0}, "lineup_slots": slots, "bench_slots": 6, "ir_slots": 1,
                     "reg_season_weeks": 14, "playoff_team_count": 4, "playoff_weeks": [15, 16], "matchup_periods": {i: [i] for i in range(1, 17)},
                     "faab": True, "faab_budget": 100, "trade_deadline_ms": 0, "ppr": 1.0},
        "roster": roster, "free_agents": fas, "faab_bids": [],
        # one incoming 2-for-1 from team 2 (their best RB for my RB2 + WR2), one offer I sent to team 3
        "pending_trades": [
            {"id": "in-1", "proposer_team_id": 2, "rival_team_id": 2, "proposed_ts": now_ms - 3 * 3600_000, "expires_ts": now_ms + 21 * 3600_000,
             "status": "PENDING", "team_actions": {"2": "ACCEPTED"}, "direction": "incoming",
             "give": [pick(1, "RB", 1), pick(1, "WR", 1)], "get": [pick(2, "RB", 0)]},
            {"id": "out-1", "proposer_team_id": 1, "rival_team_id": 3, "proposed_ts": now_ms - 3 * 3600_000, "expires_ts": now_ms + 21 * 3600_000,
             "status": "PENDING", "team_actions": {"1": "ACCEPTED"}, "direction": "outgoing",
             "give": [pick(1, "TE", 1)], "get": [pick(3, "TE", 0)]},
        ],
        "pending_trades_error": None,
    }


def analyze(snap: dict | None = None, overrides: dict | None = None, sims: int = 300) -> dict:
    """analyze_league over the synthetic snapshot with the market lookup stubbed out."""
    snap = snap or make_snapshot()
    with patch.object(fantasycalc, "by_espn_id", lambda **kw: {}):
        return analyze_league(snap, FakeCrosswalk(), {}, {}, {}, {}, overrides, sims)


def build_packet(overrides_path: str | None = None, sims: int = 300, write: bool = True) -> dict:
    """Same shape as packet.build(), one synthetic league, no network. Writes data/packets/demo-<date>.json when `write`."""
    overrides = json.load(open(overrides_path)) if overrides_path else None
    blk = analyze(overrides=overrides, sims=sims)
    packet = {
        "version": PACKET_VERSION, "generated": datetime.now().isoformat(timespec="seconds"), "season": 2026, "demo": True,
        "shared": {"injury_watchlist": [], "exposure": {}, "trending_adds": [], "usage_error": None, "unmatched_ids": [],
                   "pending_trades_error": None, "incoming_trade_count": len(blk["incoming_trades"])},
        "leagues": [blk],
    }
    if write:
        PACKET_DIR.mkdir(parents=True, exist_ok=True)
        out = PACKET_DIR / f"demo-{date.today().isoformat()}.json"
        out.write_text(json.dumps(packet, indent=1, default=str))
        packet["_path"] = str(out)
    return packet
