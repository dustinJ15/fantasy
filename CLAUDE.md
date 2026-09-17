# ff — fantasy football co-manager

Three ESPN redraft leagues (`leagues.toml`, untracked; copy from `leagues.example.toml`). **Read-only against ESPN**: never propose or build lineup/waiver/trade
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
   (`{"L1": {"read": "...", "paste": "...", "paste_to": "...", "reply": "...", "reply_to": "..."}}`: 1-2 plain sentences per league,
   what you'd actually do and why; `reply` only when `incoming_trades` has an offer)
   and `uv run ff render-email --packet <path> --reads reads.json --out briefing.html --md briefing.md`. Never hand-edit the HTML;
   `src/ff/email_html.py` owns the layout.
6. Email it to Dustin via the Gmail connector (subject: `FF briefing — Week N — <date>`).

Tuesday = waivers emphasis (bids due before Wednesday processing). Sunday morning = final lineup + inactives check.

## Commands
`ff setup-check | doctor | sync | roster | lineup | waivers | trades | incoming | odds | packet | briefing | render-email` (all accept `--league <name>`).
`ff incoming` = offers other managers sent me, with an accept/decline/counter verdict (`--json --new-since 40m` is the poller path).

## Layout
`src/ff/sources/*` data pulls (cached in `data/cache/`), `src/ff/model/*` math, `packet.py` builds the DecisionPacket,
`report.py` renders markdown (plain-text body), `email_html.py` renders the HTML email from the packet. Tests: `uv run pytest`.
`demo.py` is the synthetic league (fictional, seeded names); `scripts/screenshots.sh` regenerates `examples/` including the README images.

## Data gotchas
- nflreadpy installed from git (PyPI lags). No 2026 snap counts yet.
- FantasyPros via dynastyprocess/data mirror; do not scrape fantasypros.com or keeptradecut.com.
- Player ID joins via `db_playerids.csv` + Sleeper; check `ff doctor` for unmatched names.

## Operations (for a fresh session responding to a morning email)
Trigger ids, env id, routine URLs and the recipient address live in `ops.local.md` (untracked) and in memory; nothing personal is tracked.
- Routine "FF daily briefing": cron `0 12 * * *` UTC (6 AM Denver during DST), cloud env `fantasy` (network Full, env vars
  ESPN_S2/SWID/SEASON/HEALTHCHECK_URL/BRIEFING_TO/LEAGUES_TOML), model `claude-opus-5`. `scripts/cloud_setup.sh` writes `.env` and
  `leagues.toml` from those env vars. The briefing is emailed to `$BRIEFING_TO`.
- Incoming trade offers: every pending offer shows in the morning briefing (`incoming_trades` per league, first checklist item).
  Primary alert path: a Google Apps Script doorbell (`scripts/gmail_trade_doorbell.gs`, setup in `scripts/gmail_trade_doorbell.md`)
  runs every minute in Dustin's Gmail, finds ESPN's "Trade Proposal" email, fires the "FF trade offer" routine's API trigger
  (`/trade-offer` skill, emails `FF trade offer — <league> — <date>`) and labels the email `ff-alerted`. The trigger id and fire
  token live only in the script's Script Properties (nothing in the repo).
  Backstop: `.github/workflows/trade-poll.yml` runs `ff incoming --new-since 75m` hourly in season, dedupes by offer id via
  `actions/cache`, and fires the same routine. GitHub needs secrets `ESPN_S2`, `SWID`, `FF_ROUTINE_FIRE_TOKEN` and variables
  `FF_TRADE_ROUTINE_ID`, `SEASON`, `LEAGUES_TOML`.
- Debug a run: `RemoteTrigger list_runs` (trigger_id in ops.local.md) → `get_run_log` on the newest session. Re-run: `RemoteTrigger run`.
- Reproduce locally: `uv run ff doctor && uv run ff sync && uv run ff briefing --short --sims 500`. Local `.env` has the same cookies.
  No credentials at all: `uv run ff briefing --demo` (synthetic league from `src/ff/demo.py`).
- Code changes take effect on the next cloud run only after `git push` to main (the VM clones fresh each time).
- Projection logs: the routine pushes `data/projlog/` to the `projlog` branch, never main. To run `ff accuracy` locally:
  `git fetch origin projlog && git checkout origin/projlog -- data/projlog`.
- Do not add ESPN writes. Do not commit briefing.md/html, overrides.json, reads.json, data/cache, data/packets, leagues.toml, ops.local.md.

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
| Briefing says "could not read pending trades" | ESPN changed `mPendingTransactions` or cookies half-dead | check `pending_trades_error` in the packet; `ff incoming --force` locally |
| trade-poll workflow red | cookies dead in GitHub secrets, or fire token revoked | update repo secrets; `gh workflow run trade-poll.yml -f window=48h` to test |
| Trade offer email never arrives but the offer is in ESPN | doorbell silent (Apps Script trigger gone, Script Properties cleared, token rotated) and poller missed it or routine disabled | Apps Script Executions log; confirm Script Properties `FF_TRADE_ROUTINE_ID` + `FF_ROUTINE_FIRE_TOKEN` are still set and the 1-minute trigger exists; `RemoteTrigger get` on the trade routine; it still appears in the next morning briefing |
| ESPN proposal email has no `ff-alerted` label an hour later | doorbell never ran or the fire returned non-2xx | same as above; remove the label (if any) to make the script retry |
