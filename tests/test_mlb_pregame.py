"""The pregame planner: which games get a one-shot, when it fires, and what it says."""
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location("mlb_pregame", Path(__file__).resolve().parents[1] / "scripts" / "mlb_pregame.py")
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)


def game(pk, when, gtype="D", away=("Tampa Bay Rays", "TB", 139), home=("New York Yankees", "NYY", 147),
         state="Scheduled", official=None, probables=True):
    def side(name, abbr, tid):
        s = {"team": {"id": tid, "name": name, "abbreviation": abbr}}
        if probables:
            s["probablePitcher"] = {"id": 1000 + tid, "fullName": f"{abbr} Ace"}
        return s
    return {"gamePk": pk, "gameType": gtype, "gameDate": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "officialDate": official or when.strftime("%Y-%m-%d"), "status": {"detailedState": state},
            "teams": {"away": side(*away), "home": side(*home)}, "seriesDescription": "AL Division Series",
            "seriesGameNumber": 3}


NOW = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)  # 9:00 AM MDT


def test_one_shot_fires_lead_minutes_before_first_pitch():
    fp = NOW + timedelta(hours=9)  # 6:00 PM MT = 00:00 UTC next day
    (s,) = mp.plan([game(1, fp)], NOW)
    assert s["run_once_at"] == "2026-10-07T23:35:00Z"
    assert s["name"] == "MLB pregame: TB @ NYY 6:00PM MT Oct 7"
    assert "gamePk 1 | type D | Tampa Bay Rays @ New York Yankees" in s["prompt"]
    assert "6:00PM MT" in s["prompt"] and "AL Division Series game 3" in s["prompt"]
    assert "TB Ace (id 1139) vs NYY Ace (id 1147)" in s["prompt"]
    assert s["prompt"].startswith("MLB pregame alert for Dustin.\n\nDustin is in Denver")   # skill body, no front matter
    assert "name: mlb-pregame" not in s["prompt"] and "/home/user" not in s["prompt"]
    assert s["prompt"].rstrip().endswith("game 3")


def test_instructions_can_be_supplied():
    (s,) = mp.plan([game(1, NOW + timedelta(hours=4))], NOW, instructions="Say hi.")
    assert s["prompt"].startswith("Say hi.\n\nGames starting soon:\n- gamePk 1")


def test_same_first_pitch_is_one_trigger():
    fp = NOW + timedelta(hours=4)
    specs = mp.plan([game(2, fp, away=("Chicago Cubs", "CHC", 112), home=("San Diego Padres", "SD", 135)), game(1, fp)], NOW)
    assert len(specs) == 1
    assert specs[0]["name"].startswith("MLB pregame: TB @ NYY, CHC @ SD ")
    assert specs[0]["prompt"].count("- gamePk") == 2


def test_late_planner_still_alerts_a_game_ten_minutes_out_and_drops_a_closer_one():
    soon = mp.plan([game(1, NOW + timedelta(minutes=15))], NOW)
    assert soon and soon[0]["run_once_at"] == "2026-10-07T15:02:00Z"
    assert mp.plan([game(1, NOW + timedelta(minutes=5))], NOW) == []


def test_filters():
    fp = NOW + timedelta(hours=4)
    assert mp.plan([game(1, fp, state="Postponed")], NOW) == []
    assert mp.plan([game(1, fp + timedelta(days=1))], NOW) == []           # tomorrow's game is tomorrow's plan
    reg = game(1, fp, gtype="R", official="2026-09-20", away=("Miami Marlins", "MIA", 146), home=("Pittsburgh Pirates", "PIT", 134))
    assert mp.plan([reg], NOW) == []                                         # nobody in a race
    reg["teams"]["home"]["team"]["id"] = 117                                 # Houston
    assert len(mp.plan([reg], NOW)) == 1
    reg["officialDate"] = "2026-09-28"                                       # past the regular season's last day
    assert mp.plan([reg], NOW) == []


def test_probables_tbd():
    (s,) = mp.plan([game(1, NOW + timedelta(hours=4), probables=False)], NOW)
    assert "probables: TBD (id ) vs TBD (id )" in s["prompt"]
