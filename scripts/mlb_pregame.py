"""Fire Dustin's pre-approved "MLB pregame alert" Claude task shortly before key MLB games.

Runs from GitHub Actions every ~15 min. Reads MLB's public schedule API, picks games
starting in the next WINDOW_MIN minutes that matter, groups games with the same first
pitch, and fires the Claude task once per group with the game details appended.
State (already-alerted gamePks) lives in data/pregame_state.json so a game alerts once.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta, timezone

TRIGGER_ID = "trig_016ve9hkgW9Pr4Qh47dJh2tY"   # "MLB pregame alert (fired by GitHub)"
STATE_PATH = "data/pregame_state.json"
LEAD_MIN, WINDOW_MIN = 5, 40                    # alert if first pitch is 5-40 min away
MT = timezone(timedelta(hours=-6))              # MDT; revisit after Nov 1 (season is over by then)

POSTSEASON_TYPES = {"F", "D", "L", "W"}         # Wild Card, Division Series, LCS, World Series
# Regular season: only games involving teams still in a race. Edit as races settle.
REGULAR_SEASON_LAST_DAY = "2026-09-27"
WATCH_TEAMS = {117: "HOU", 140: "TEX", 114: "CLE", 145: "CWS", 111: "BOS",
               112: "CHC", 135: "SD", 143: "PHI", 109: "ARI"}
SKIP_STATES = {"Final", "Game Over", "Completed Early", "Postponed", "Cancelled", "Suspended"}


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


# Same fire path as the trade-offer poller (.github/workflows/trade-poll.yml) and the Gmail
# doorbell (scripts/gmail_trade_doorbell.gs): POST to the routine's /fire endpoint with the
# routine's API fire token as a Bearer token; `text` is appended to the task's prompt.
# Fire tokens are per routine ("Token is not authorized for this routine" otherwise), so this
# is the pregame routine's own token, not the trade-offer one.
FIRE_URL = "https://api.anthropic.com/v1/claude_code/routines/{}/fire"
TOKEN_ENV = "MLB_ROUTINE_FIRE_TOKEN"
RETRY_ATTEMPTS, RETRY_BASE_S = 3, 2


def fire_trigger(trigger_id, text):
    """Fire the Claude scheduled task with `text` appended as an extra message.

    Transport errors and 5xx are retried with backoff; a 4xx (rotated token, wrong trigger
    id) is a real answer and raises at once. The token comes from the MLB_ROUTINE_FIRE_TOKEN
    environment variable (a GitHub Actions secret); it is never written anywhere.
    """
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise SystemExit(f"{TOKEN_ENV} is not set; cannot fire {trigger_id}")
    req = urllib.request.Request(
        FIRE_URL.format(trigger_id),
        data=json.dumps({"text": text}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "experimental-cc-routine-2026-04-01",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    last = None
    for attempt in range(RETRY_ATTEMPTS):
        if attempt:
            time.sleep(RETRY_BASE_S * 2 ** (attempt - 1))
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                print(f"fired {trigger_id}: HTTP {r.status}")
                return
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"
            if e.code < 500:
                break  # 401/403/404 will not fix themselves.
        except (urllib.error.URLError, OSError) as e:
            last = f"request failed: {e}"
    raise SystemExit(f"could not fire {trigger_id}: {last}")


def main():
    now = datetime.now(UTC)
    dry = "--dry-run" in sys.argv
    state = json.load(open(STATE_PATH)) if os.path.exists(STATE_PATH) else {"alerted": []}
    alerted = set(state["alerted"])

    # MT "today" plus the next UTC day covers late West Coast starts after 00:00 UTC.
    start = now.astimezone(MT).date()
    url = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1"
           f"&startDate={start}&endDate={start + timedelta(days=1)}"
           "&gameType=R,F,D,L,W&hydrate=probablePitcher,team")
    games = [g for d in get_json(url).get("dates", []) for g in d["games"]]

    groups = {}
    for g in games:
        pk, gtype = g["gamePk"], g["gameType"]
        first_pitch = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))
        mins_away = (first_pitch - now).total_seconds() / 60
        if pk in alerted or not (LEAD_MIN <= mins_away <= WINDOW_MIN):
            continue
        if g["status"]["detailedState"] in SKIP_STATES:
            continue
        away, home = g["teams"]["away"], g["teams"]["home"]
        if gtype == "R":
            if g["officialDate"] > REGULAR_SEASON_LAST_DAY:
                continue
            if away["team"]["id"] not in WATCH_TEAMS and home["team"]["id"] not in WATCH_TEAMS:
                continue
        elif gtype not in POSTSEASON_TYPES:
            continue
        groups.setdefault(g["gameDate"], []).append(g)

    for _game_date, gs in sorted(groups.items()):
        lines = ["Games starting soon:"]
        for g in gs:
            a, h = g["teams"]["away"], g["teams"]["home"]
            fp = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))
            pp = lambda side: side.get("probablePitcher", {}).get("fullName", "TBD")
            ppid = lambda side: side.get("probablePitcher", {}).get("id", "")
            lines.append(
                f"- gamePk {g['gamePk']} | type {g['gameType']} | "
                f"{a['team']['name']} @ {h['team']['name']} | first pitch "
                f"{fp:%Y-%m-%d %H:%M} UTC = {fp.astimezone(MT):%-I:%M%p} MT | "
                f"probables: {pp(a)} (id {ppid(a)}) vs {pp(h)} (id {ppid(h)})"
                + (f" | {g.get('seriesDescription', '')} game {g.get('seriesGameNumber', '')}"
                   if g["gameType"] != "R" else ""))
        text = "\n".join(lines)
        print(text)
        if not dry:
            fire_trigger(TRIGGER_ID, text)
            alerted.update(g["gamePk"] for g in gs)

    if not dry:
        state["alerted"] = sorted(alerted)[-500:]
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        json.dump(state, open(STATE_PATH, "w"), indent=1)
    if not groups:
        print("No qualifying games in the window.")


if __name__ == "__main__":
    main()
