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
   The `note` is shown next to the player in the email.
5. `uv run ff briefing --overrides overrides.json` → markdown + packet path. Then write `reads.json`
   (`{"L1": {"read": "...", "paste": "...", "paste_to": "..."}}`: 1-2 plain sentences per league, what you'd actually do and why)
   and `uv run ff render-email --packet <path> --reads reads.json --out briefing.html --md briefing.md`. Never hand-edit the HTML;
   `src/ff/email_html.py` owns the layout.
6. Email it to Dustin via the Gmail connector (subject: `FF briefing — Week N — <date>`).

Tuesday = waivers emphasis (bids due before Wednesday processing). Sunday morning = final lineup + inactives check.

## Commands
`ff setup-check | doctor | sync | roster | lineup | waivers | trades | odds | packet | briefing | render-email` (all accept `--league <name>`).

## Layout
`src/ff/sources/*` data pulls (cached in `data/cache/`), `src/ff/model/*` math, `packet.py` builds the DecisionPacket,
`report.py` renders markdown (plain-text body), `email_html.py` renders the HTML email from the packet. Tests: `uv run pytest`.

## Data gotchas
- nflreadpy installed from git (PyPI lags). No 2026 snap counts yet.
- FantasyPros via dynastyprocess/data mirror; do not scrape fantasypros.com or keeptradecut.com.
- Player ID joins via `db_playerids.csv` + Sleeper; check `ff doctor` for unmatched names.

## Operations (for a fresh session responding to a morning email)
- Routine "FF daily briefing": trigger `trig_012oA6amKwYBZFg51w1hEqgb`, cron `0 12 * * *` UTC (6 AM Denver during DST),
  cloud env `fantasy` (`env_01Fh955ffyDEwuNxskeXjN3q`, network Full, env vars ESPN_S2/SWID/SEASON/HEALTHCHECK_URL), model `claude-opus-5` (changed from Sonnet 5 on 2026-09-14 via `RemoteTrigger update`).
  Page: https://claude.ai/code/routines/trig_012oA6amKwYBZFg51w1hEqgb
- Debug a run: `RemoteTrigger list_runs` (trigger_id above) → `get_run_log` on the newest session. Re-run: `RemoteTrigger run`.
- Reproduce locally: `uv run ff doctor && uv run ff sync && uv run ff briefing --short --sims 500`. Local `.env` has the same cookies.
- Code changes take effect on the next cloud run only after `git push` to main (the VM clones fresh each time).
- Do not add ESPN writes. Do not commit briefing.md/html, overrides.json, reads.json, data/cache, data/packets.

## Known failure modes
| symptom | cause | fix |
|---|---|---|
| "FF briefing FAILED" email or `ESPNAccessDenied` / `AUTH_MISSING_CREDENTIALS` | ESPN cookies expired (~yearly, silent) | Dustin re-copies `espn_s2` + `SWID` (scripts/setup_cookies.md) into local `.env` AND the cloud env vars |
| No email and healthchecks.io alert | routine never ran / VM failed | `RemoteTrigger get` to check enabled + next_run_at; `run` manually; check run log |
| `uv sync` network timeout in cloud | flaky PyPI download | cloud_setup.sh retries with UV_HTTP_TIMEOUT=300; re-run if it still fails |
| "usage metrics unavailable: Read timed out" | nflverse GitHub release download slow | NFLREADPY_TIMEOUT=120 is set in cloud_setup.sh; harmless, usage columns just blank |
| Lineup shows a slot as EMPTY | no healthy eligible player | expected; the checklist tells Dustin to pick one up |
| Monday email suggests moving players who played Sunday | `model/clock.py` locks players by kickoff/points; check `lines` (vegas scoreboard cache) has kickoffs and `actual_week` is populated | `ff sync --force`; look at `week_state` in the packet |
| Sleeper projections missing for many players | crosswalk join | `Crosswalk.sleeper_id()`; check `shared.unmatched_ids` in the packet |
| Agent sent >1 email or investigated git/Gmail history | skill scope drift | SKILL.md step 10 forbids it; tighten wording if it recurs |
| Cloud Bash killed a long command | 120 s default timeout | run `ff` steps with timeout 600000, never `&` |
