# ff — fantasy football co-manager

Three ESPN redraft leagues (see `leagues.toml`). **Read-only against ESPN**: never propose or build lineup/waiver/trade
writes or ESPN chat posting. Dustin taps the buttons.

## Boundary rule
Code owns state and math. Claude owns judgment over unstructured text and prose.
Claude returns *parameters and prose*, never *decisions or state*. Every number in the briefing comes from `ff`.

## Morning routine (`/briefing` skill encodes this)
1. `uv run ff doctor` — stop and tell Dustin if cookies are dead.
2. `uv run ff sync && uv run ff packet` → `data/packets/<date>.json`.
3. Read the packet. `shared.injury_watchlist` lists players with ambiguous designations across all my rosters.
   WebSearch each one (beat writers, practice reports). Also skim for narrative shifts on my players and top waiver targets
   (committee → bellcow, QB change, coach comments).
4. Write `overrides.json`: `{"<espn_id>": {"p_zero": 0.15, "mu_mult": 1.1, "note": "..."}}` only where news changes the picture.
5. `uv run ff briefing --overrides overrides.json` → markdown. Add a short "Claude's read" paragraph per league at the top of each section:
   what you'd actually do and why, in plain words. Keep the numbers from the packet.
6. Email it to Dustin via the Gmail connector (subject: `FF briefing — Week N — <date>`).

Tuesday = waivers emphasis (bids due before Wednesday processing). Sunday morning = final lineup + inactives check.

## Commands
`ff setup-check | doctor | sync | roster | lineup | waivers | trades | odds | packet | briefing` (all accept `--league <name>`).

## Layout
`src/ff/sources/*` data pulls (cached in `data/cache/`), `src/ff/model/*` math, `packet.py` builds the DecisionPacket,
`report.py` renders markdown. Tests: `uv run pytest`.

## Data gotchas
- nflreadpy installed from git (PyPI lags). No 2026 snap counts yet.
- FantasyPros via dynastyprocess/data mirror; do not scrape fantasypros.com or keeptradecut.com.
- Player ID joins via `db_playerids.csv` + Sleeper; check `ff doctor` for unmatched names.
