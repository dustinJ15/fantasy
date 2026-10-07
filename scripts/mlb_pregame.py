"""Plan today's MLB pregame alerts: one one-shot Claude routine per first pitch.

Step 0 of the morning briefing (.claude/skills/briefing/SKILL.md) runs this in the `fantasy` cloud env, where
the repo is checked out and bash has network. It reads MLB's public schedule, keeps the games that matter
(postseason, or regular-season games of a team in a race), groups games that share a first pitch, and prints
one spec per group: `name`, `run_once_at` (LEAD_MIN before first pitch) and the `prompt` for the one-shot.
Claude creates each with `create_trigger` (run_once_at, create_new_session_on_fire, push notification); the
one-shot fires once and disables itself, so there is no state file, no token and no GitHub cron in the path.
The prompt is .claude/skills/mlb-pregame/SKILL.md (minus its front matter) plus the game lines: a session a
routine spawns has no repo checkout, so the prompt has to carry everything.

    python3 scripts/mlb_pregame.py            # JSON: {"date", "triggers": [...]} or {"season_over": true}
    python3 scripts/mlb_pregame.py --text     # the same, readable

No third-party imports: the scheduler session runs this before (and without) `uv sync`.
"""
import json
import sys
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

MT = ZoneInfo("America/Denver")
LEAD_MIN = 25              # the one-shot fires this many minutes before first pitch; research takes ~2
MIN_NOTICE_MIN = 10        # a game closer than this when the planner runs is not worth an alert
LOOKAHEAD_DAYS = 7         # no qualifying game this far out after the regular season = season over

POSTSEASON_TYPES = {"F", "D", "L", "W"}         # Wild Card, Division Series, LCS, World Series
# Regular season: only games involving teams still in a race. Edit as races settle.
REGULAR_SEASON_LAST_DAY = "2026-09-27"
WATCH_TEAMS = {117: "HOU", 140: "TEX", 114: "CLE", 145: "CWS", 111: "BOS",
               112: "CHC", 135: "SD", 143: "PHI", 109: "ARI"}
SKIP_STATES = {"Final", "Game Over", "Completed Early", "Postponed", "Cancelled", "Suspended"}
SERIES_NAMES = {"F": "Wild Card", "D": "Division Series", "L": "LCS", "W": "World Series", "R": ""}

SCHEDULE_URL = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate={start}&endDate={end}"
                "&gameType=R,F,D,L,W&hydrate=probablePitcher,team,seriesStatus")

SKILL_PATH = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "mlb-pregame" / "SKILL.md"


def alert_instructions(path: Path = SKILL_PATH) -> str:
    """The skill file's body (front matter stripped): the standalone prompt of every one-shot."""
    text = path.read_text()
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return "MLB pregame alert for Dustin.\n\n" + text.strip()


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def fetch_games(start: date, end: date):
    url = SCHEDULE_URL.format(start=start, end=end)
    return [g for d in get_json(url).get("dates", []) for g in d["games"]]


def first_pitch(g) -> datetime:
    return datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))


def matters(g) -> bool:
    """A postseason game, or a regular-season game of a team in a race, that has not started or been called."""
    if g["status"]["detailedState"] in SKIP_STATES:
        return False
    gtype = g["gameType"]
    if gtype in POSTSEASON_TYPES:
        return True
    if gtype != "R" or g["officialDate"] > REGULAR_SEASON_LAST_DAY:
        return False
    ids = {g["teams"]["away"]["team"]["id"], g["teams"]["home"]["team"]["id"]}
    return bool(ids & set(WATCH_TEAMS))


def describe(g) -> str:
    a, h = g["teams"]["away"], g["teams"]["home"]
    fp = first_pitch(g)
    pp = lambda side: side.get("probablePitcher", {}).get("fullName", "TBD")
    ppid = lambda side: side.get("probablePitcher", {}).get("id", "")
    line = (f"- gamePk {g['gamePk']} | type {g['gameType']} | {a['team']['name']} @ {h['team']['name']} | "
            f"first pitch {fp:%Y-%m-%d %H:%M} UTC = {fp.astimezone(MT):%-I:%M%p} MT | "
            f"probables: {pp(a)} (id {ppid(a)}) vs {pp(h)} (id {ppid(h)})")
    if g["gameType"] != "R":
        line += f" | {g.get('seriesDescription') or SERIES_NAMES[g['gameType']]} game {g.get('seriesGameNumber', '')}"
    return line


def short(side) -> str:
    t = side["team"]
    return t.get("abbreviation") or t.get("teamName") or t["name"]


def plan(games, now: datetime, instructions: str | None = None):
    """One trigger spec per distinct first pitch among today's games that matter.

    `run_once_at` is LEAD_MIN before first pitch. A group whose fire time has passed still gets an alert
    (two minutes from now) when first pitch is at least MIN_NOTICE_MIN away; closer than that it is dropped.
    """
    instructions = alert_instructions() if instructions is None else instructions
    today = now.astimezone(MT).date()
    groups: dict[datetime, list] = {}
    for g in games:
        if matters(g) and first_pitch(g).astimezone(MT).date() == today:
            groups.setdefault(first_pitch(g), []).append(g)
    specs = []
    for fp, gs in sorted(groups.items()):
        fire = fp - timedelta(minutes=LEAD_MIN)
        if fire < now + timedelta(minutes=1):
            if fp < now + timedelta(minutes=MIN_NOTICE_MIN):
                continue
            fire = now + timedelta(minutes=2)
        gs.sort(key=lambda g: g["gamePk"])
        matchups = ", ".join(f"{short(g['teams']['away'])} @ {short(g['teams']['home'])}" for g in gs)
        specs.append({
            "name": f"MLB pregame: {matchups} {fp.astimezone(MT):%-I:%M%p} MT {fp.astimezone(MT):%b %-d}",
            "run_once_at": fire.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "prompt": instructions + "\n\nGames starting soon:\n" + "\n".join(describe(g) for g in gs),
        })
    return specs


def season_over(now: datetime) -> bool:
    """After the regular season, a week with no postseason game on the schedule means the season is done."""
    start = now.astimezone(MT).date()
    if str(start) <= REGULAR_SEASON_LAST_DAY:
        return False
    return not any(g["gameType"] in POSTSEASON_TYPES and g["status"]["detailedState"] not in SKIP_STATES
                   for g in fetch_games(start, start + timedelta(days=LOOKAHEAD_DAYS)))


def main():
    now = datetime.now(UTC)
    start = now.astimezone(MT).date()
    # MT today plus the next UTC day: a 7 PM MT first pitch is already tomorrow in UTC.
    games = fetch_games(start, start + timedelta(days=1))
    specs = plan(games, now)
    out = {"date": str(start), "triggers": specs}
    if not specs and season_over(now):
        out["season_over"] = True
    if "--text" in sys.argv:
        if out.get("season_over"):
            print("Season over: no postseason game in the next week.")
        elif not specs:
            print(f"No qualifying games on {start}.")
        for s in specs:
            print(f"\n== {s['name']}\nrun_once_at: {s['run_once_at']}\n{s['prompt']}")
    else:
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
