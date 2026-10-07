---
name: mlb-pregame
description: The pregame push alert for an MLB game that matters. scripts/mlb_pregame.py inlines this file into the prompt of each one-shot routine the morning briefing schedules; the fired session has no repo checkout, so nothing here may point at a file.
---

Dustin is in Denver (Mountain Time). The game details are at the end of this message: gamePk, away @ home, first pitch
(UTC and MT), game type (R = regular season, F = Wild Card, D = Division Series, L = LCS, W = World Series) and the
listed probable pitchers. Do not wait for or look for any other message. Your final reply becomes a push notification.
Finish within about 5 minutes.

Data sources (bash has network here, so `curl -s` works; WebFetch is the fallback, with a cache-buster like
`&cb=<UTC HHMMSS>` on every WebFetch URL or you may get a stale copy):
1. Game status, confirmed starters and series score: https://statsapi.mlb.com/api/v1/schedule?sportId=1&gamePk=<gamePk>&hydrate=probablePitcher,seriesStatus
2. Standings and clinch flags (regular season only): https://statsapi.mlb.com/api/v1/standings?leagueId=103,104
3. Starter W-L and ERA: https://statsapi.mlb.com/api/v1/people/<id>?hydrate=stats(group=[pitching],type=[season])
4. Series context for the postseason: https://statsapi.mlb.com/api/v1/schedule/postseason/series?season=2026
5. The live tracker's current state (races and series as Dustin's page shows them): ArtifactData (load via ToolSearch),
   action "get", collection "tracker", doc_id "state", url https://claude.ai/artifact/AtSNeP32QKQmk2rW6WRXyh.
   Read only; never write to it. If the tool is not available, skip it.

Use WebSearch only for news context (injuries, late scratches), at most two calls. Work out the stakes from confirmed
data, including results of games earlier today: in the regular season, what a win or loss does to a division race,
Wild Card spot or seed; in the postseason, the series score and what this game means (e.g. "Game 3, winner advances
to face the Rays"). If the game is postponed or already under way, say so in one line instead of the alert.

Reply with ONLY the alert below. Never leave a bracketed placeholder; if something cannot be confirmed, say so in a
few words. Under about 100 words. Do not edit any page, do not commit, and do not create or change any scheduled task.
First pitch [time] MT: [Away] @ [Home] [(and the other games in the message)]
- Why it matters: [one line]
- Starters: [Away pitcher (W-L, ERA) vs. Home pitcher (W-L, ERA)]
- Watch: [TV network if known]
- Live tracker: https://claude.ai/artifact/AtSNeP32QKQmk2rW6WRXyh
