# ESPN setup (one time, ~5 minutes)

## 1. League IDs
Open each league at fantasy.espn.com. The URL looks like
`https://fantasy.espn.com/football/league?leagueId=1234567`. Put each `leagueId` into `leagues.toml`
and give it a short name (used for `--league <name>` and section headers in the briefing).

## 2. Cookies (`espn_s2` and `SWID`)
Private leagues need two cookies from a logged-in browser session. They last roughly a year.

**Easiest:** install the "ESPN Private League Setup" Chrome extension by an espn-api maintainer
(source: https://github.com/dtcarls/ESPNExtension), open fantasy.espn.com while logged in, click it, copy both values.

**Manual:** log in at fantasy.espn.com → DevTools (F12) → Application (Chrome) / Storage (Firefox) → Cookies →
`https://fantasy.espn.com` → copy `SWID` (keep the curly braces) and `espn_s2` (long, URL-encoded string).

## 3. `.env`
```
cp .env.example .env
```
Paste values. Then:
```
uv run ff setup-check
```
It prints every team in each league and marks yours. If it says cookies are missing/expired, redo step 2.

## Notes
- `ff doctor` runs daily inside the briefing and alerts loudly if the cookie dies mid-season.
- Never commit `.env`. It is gitignored.
- This project is read-only against ESPN. It never sets lineups, bids, or posts for you.
