---
name: mlb-pregame
description: Write Dustin's pregame push alert for an MLB game that matters (fired by a one-shot routine that the "MLB pregame scheduler" routine created that morning).
---

# MLB pregame alert

Dustin is in Denver (Mountain Time). The prompt that fired this session lists the game(s): gamePk, away @ home,
first pitch (UTC and MT), game type (R = regular season, F = Wild Card, D = Division Series, L = LCS, W = World
Series) and the listed probable pitchers. Your final reply becomes a push notification. If no game details were
given, reply with one line `No game info received.` and stop.

## Data sources
Bash has network here, so `curl -s` works; WebFetch is the fallback (add a cache-buster like `&cb=<UTC HHMMSS>` to
every WebFetch URL or you may get a stale copy).
1. Game status, confirmed starters and series score: `https://statsapi.mlb.com/api/v1/schedule?sportId=1&gamePk=<gamePk>&hydrate=probablePitcher,seriesStatus`
2. Standings and clinch flags (regular season only): `https://statsapi.mlb.com/api/v1/standings?leagueId=103,104`
3. Starter W-L and ERA: `https://statsapi.mlb.com/api/v1/people/<id>?hydrate=stats(group=[pitching],type=[season])`
4. Series context for the postseason: `https://statsapi.mlb.com/api/v1/schedule/postseason/series?season=2026`
5. The live tracker's current state (races and series as Dustin's page shows them): ArtifactData (load via
   ToolSearch), action `get`, collection `tracker`, doc_id `state`, url https://claude.ai/artifact/AtSNeP32QKQmk2rW6WRXyh.
   Read only; never write to it.

Use WebSearch only for news context (injuries, late scratches), at most two calls. Work out the stakes from confirmed
data, including results of games earlier today: in the regular season, what a win or loss does to a division race,
Wild Card spot or seed; in the postseason, the series score and what this game means (e.g. "Game 3, winner advances
to face the Rays"). If the game is postponed or already under way, say so in one line instead of the alert.

## Reply
Reply with ONLY the alert below. Never leave a bracketed placeholder; if something cannot be confirmed, say so in a
few words. Under about 100 words. Do not edit any page, do not commit, and do not create or change any scheduled task.

```
First pitch [time] MT: [Away] @ [Home] [(and the other games in the message)]
- Why it matters: [one line]
- Starters: [Away pitcher (W-L, ERA) vs. Home pitcher (W-L, ERA)]
- Watch: [TV network if known]
- Live tracker: https://claude.ai/artifact/AtSNeP32QKQmk2rW6WRXyh
```
