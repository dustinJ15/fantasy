# ff — fantasy football co-manager

Three ESPN redraft leagues (`leagues.toml`, untracked; copy from `leagues.example.toml`). **Read-only against ESPN**: never propose or build
lineup/waiver/trade writes or ESPN chat posting. Dustin taps the buttons. `docs/README.md` indexes every other document (who it is for, when to read
it); read one only when the task names it.

## Boundary rule
Code owns state and math. Claude owns judgment over unstructured text and prose.
Claude returns *parameters and prose*, never *decisions or state*. Every number in the briefing comes from `ff`.

## Morning routine (`/briefing` skill encodes this)
1. `uv run ff doctor` — stop and tell Dustin if cookies are dead.
2. `uv run ff sync && uv run ff packet` → `data/packets/<date>.json`.
3. Read the packet. `shared.injury_watchlist` lists players with ambiguous designations across all my rosters; `shared.injured` lists the ones out a
   week or more (or on IR) whose return timeline needs a number. WebSearch each one (beat writers, practice reports). Also skim for narrative shifts
   on my players and top waiver targets (committee → bellcow, QB change, coach comments).
4. Write `overrides.json`: `{"<espn_id>": {"p_zero": 0.15, "mu_mult": 1.1, "weeks_out": 4, "ros_mult": 0.9, "note": "..."}}` only where news changes
   the picture. `p_zero`/`mu_mult` are this week; `weeks_out` (games, or `"season"`) and `ros_mult` are the rest of the season and decide the hold /
   IR / drop / trade row for a hurt player. The `note` is shown next to the player in the email.
5. `uv run ff briefing --overrides overrides.json` → markdown + packet path. Then write `reads.json` (`{"L1": {"read": "...", "items": {"<row id>":
   {"verdict": "do|skip|amend", "note": "..."}}, "paste": "...", "paste_to": "...", "reply": "...", "reply_to": "..."}}`): rule on rows in `items`
   (the ids print in backticks at the end of each briefing.md checklist line) rather than arguing with the card in prose, every `trade` row needs a
   verdict, and `read` carries only what the research adds; `reply` only when `incoming_trades` has an offer. Then `uv run ff render-email --packet
   <path> --reads reads.json --out briefing.html --md briefing.md`. Never hand-edit the HTML; `src/ff/email_html.py` owns the layout.
6. Email it to Dustin via the Gmail connector (subject: `FF briefing — Week N — <date>`).
Tuesday = waivers emphasis (bids due before Wednesday processing). Sunday morning = final lineup + inactives check.

## Commands
`ff setup-check | doctor | sync | roster | lineup | waivers | trades | incoming | odds | packet | briefing | render-email` (all accept `--league <name>`);
`ff incoming` = offers other managers sent me, with an accept/decline/counter verdict (`--json --new-since 40m` is the poller path).

## Layout
`src/ff/sources/*` data pulls (cached in `data/cache/`); `src/ff/model/*` math. `injuries.py` is the hold / IR / drop / trade rule (`mu_ros` is
availability-weighted, `mu_ros_active` per game played; `drop_cost` ranks a cut by `mu_ros` + market + handcuff value − a bye or sit-risk week).
`season.py` prices a roster week by week with byes, return dates and the wire as the fallback body, each week weighted by `week_weight` (1 in the
regular season; in the playoff weeks my playoff odds × `TITLE_RUN_MULT`; `injuries.week_weights` is the same number, `playoff_weight` in the league
block is what the card prints). `acceptance.py` is the would-he-say-yes scorecard behind every trade row, `trades.py` the scan and the hard rules.
`deadlines.py` is the league's clocks (next waiver run from ESPN's `processDate` else `WAIVER_RUN_HOUR_ET`, a drop's clear time, when an accepted
offer executes, next kickoff) as each league's `deadlines` block; claim and offer rows print them ("lands Wed 1:00 AM"). `lineup.py` is the P(win)
optimizer (`MIN_WIN_GAIN` keeps the highest-points lineup under 1.5pp; `MIN_SWAP_GAIN` keeps a healthy starter under a 1-point swap, `held` on the why line); `projections.py` the blend (`season_pg`, `wind_mult`,
`QUESTIONABLE_BY_WEEKDAY`); `clock.py` locks players from kickoff; `waivers.py` `priority_cost` prices the priority a claim spends in a rolling
league. `packet.py` builds the DecisionPacket (`apply_accepted_trades` moves an accepted trade's players before anything is priced; `title_deltas`
re-sims on the baseline's seed). `ledger.py` is the roster-spot ledger behind the checklist: `Spots` hands out spots and drops (an open spot, the spot an IR
row frees, a Drop-verdict player at cost 0, then the cheapest drop), counts bodies against `settings.position_limits`; `drop_order` / `drop_note` rank and word a cut.
`report.py` renders markdown and owns the checklist; one `_*_items` builder per row kind over the shared ledger, `todos` is the order (roster moves
first, the lineup row after them), the push selection and the ids, `apply_reads` folds Claude's per-row verdicts in, `read_lint` catches a typo'd id
or an unruled trade. A row is two tiers: `text` is the click in one sentence, held under `MAX_ROW_WORDS` by `tests/test_card.py` (the lineup row is
exempt); `detail` is the reasons, clocks and numbers behind it (the email's grey line, `report.detail_line`). New wording goes in `detail` unless it
changes the click. Game context on a row is a packet field put into words by one `report` helper both renderers call (`game_note` reads `odds_line`;
`usage_note`, `due_note`, `accept_note`, `processes_note` likewise). `email_html.py` renders the HTML email from the packet. `rulings.py` is the
memory on the `projlog` branch (skipped and pushed trades, offer outcomes, IR moves); `projlog.py` the projection log (`ff accuracy`). `demo.py` is
the synthetic league. Tests: `uv run pytest`; the Apps Script doorbell: `node scripts/gmail_trade_doorbell.test.js` (run it after editing the `.gs`).

## Data gotchas and rules
- nflreadpy installed from git (PyPI lags); no 2026 snap counts yet. FantasyPros via the dynastyprocess/data mirror; do not scrape
  fantasypros.com or keeptradecut.com. Player ID joins via `db_playerids.csv` + Sleeper; check `ff doctor` for unmatched names.
- Questionable sit-risk is day-aware (`QUESTIONABLE_BY_WEEKDAY`: 15% Mon–Wed, 20% Thu, 30% from Fri); a `p_zero` override wins. An IR stash
  is activated only when ESPN's designation leaves the IR-eligible set, never from the guessed return week.
- Do not add ESPN writes. Do not commit briefing.md/html, overrides.json, reads.json, data/cache, data/packets, leagues.toml, ops.local.md.

## Operations (the whole of it: `docs/operations.md`; trigger ids, env id, routine URLs and the recipient address: `ops.local.md`, untracked)
- Debug a run: `RemoteTrigger list_runs` (trigger_id in ops.local.md) → `get_run_log` on the newest session. Re-run: `RemoteTrigger run`.
- Reproduce locally: `uv run ff doctor && uv run ff sync && uv run ff briefing --short --sims 500`. No credentials: `uv run ff briefing --demo`.
- Code reaches the cloud routine only after `git push` to main (the VM clones fresh each time); rulings and memories ride the `projlog` branch.

## Known failure modes (open, or checks to run; the fixed ones are in `docs/failures.md`)
| symptom | cause | fix |
|---|---|---|
| "FF briefing FAILED" email or `ESPNAccessDenied` / `AUTH_MISSING_CREDENTIALS` | ESPN cookies expired (~yearly, silent) | Dustin re-copies `espn_s2` + `SWID` (scripts/setup_cookies.md) into local `.env` AND the cloud env vars |
| No email and healthchecks.io alert | routine never ran / VM failed | `RemoteTrigger get` to check enabled + next_run_at; `run` manually; check run log |
| `uv sync` network timeout in cloud | flaky PyPI download | cloud_setup.sh retries with UV_HTTP_TIMEOUT=300; re-run if it still fails |
| "usage metrics unavailable: Read timed out" | nflverse GitHub release download slow | NFLREADPY_TIMEOUT=120 is set in cloud_setup.sh; harmless, usage columns just blank |
| Lineup shows a slot as EMPTY | nobody I hold for it can play (bye, IR, `p_zero` at `NEVER_STARTS_AT`); the optimizer never seats a zero | expected; the lineup row names the slot, who I hold there and why, and the add or claim that fills it; the header prints the P(win) once he is in (`lineup_after`). If the line says "pick one up" with a body on the wire, check `week_slot` on him in the packet's `waivers` |
| Monday email suggests moving players who played Sunday | `model/clock.py` locks players by kickoff/points; check `lines` (vegas scoreboard cache) has kickoffs and `actual_week` is populated | `ff sync --force`; look at `week_state` in the packet |
| Sleeper projections missing for many players | crosswalk join | `Crosswalk.sleeper_id()`; check `shared.unmatched_ids` in the packet |
| Agent sent >1 email or investigated git/Gmail history | skill scope drift | SKILL.md step 10 forbids it; tighten wording if it recurs |
| Same trade package returns the morning after a `skip` | `data/projlog/skipped_trades.json` missing (projlog branch not restored) | check cloud_setup.sh fetched `origin/projlog`; the key is `<league>|<get names>` |
| Email card says do it and Claude's read says don't (the morning checklist, or the trade-offer alert's verdict badge with a read underneath disagreeing) | a row was argued with in prose instead of ruled on | `items` in reads.json: `skip` strikes the row, `amend` corrects it; `ff render-email` warns about unruled trade rows. The `--only-incoming` alert folds a ruling on the `offer:` row the same way (`ff incoming --json` prints the id as `row_id`) |
| Cloud Bash killed a long command | 120 s default timeout | run `ff` steps with timeout 600000, never `&` |
| Email says hold a player who is done for the year, or trade/drop one who is back Sunday | `weeks_out` still at its designation default (IR = 4, Out = 1) | the player is in `shared.injured`; write `weeks_out` (or `"season"`) in overrides.json and re-run step 5 |
| Card says drop a hurt starter (or hold a backup who is plainly dead weight) | `mu_ros_active` is off: ESPN docked his season total for the injury, or his healthy level is not what ESPN thinks | `shared.injured` shows `mu_ros_active`; write `ros_mult` in overrides.json; the drop rule fires when he is below replacement on return |
| Card says move a player to IR and the app refuses | league's IR eligibility is stricter than `IR_ELIGIBLE` in `model/injuries.py` | `scripts/probe_injuries.py` shows what ESPN says; narrow the constant |
| Briefing says "could not read pending trades" | ESPN changed `mPendingTransactions` or cookies half-dead | check `pending_trades_error` in the packet; `ff incoming --force` locally |
| trade-poll workflow red | cookies dead in GitHub secrets, or fire token revoked | update repo secrets; `gh workflow run trade-poll.yml -f window=48h` to test |
| Email "FF trade doorbell — cannot reach the trade routine" | 3 fires in a row rejected: token rotated (401/403) or routine id wrong (404) | fix the Script Property; `fireTestOffer` in the Apps Script editor re-checks the path |
| Trade offer email never arrives but the offer is in ESPN | doorbell silent (Apps Script trigger gone, Script Properties cleared, token rotated) and poller missed it or routine disabled | Apps Script Executions log; confirm Script Properties `FF_TRADE_ROUTINE_ID` + `FF_ROUTINE_FIRE_TOKEN` are still set and the 1-minute trigger exists; `RemoteTrigger get` on the trade routine; it still appears in the next morning briefing |
| No MLB pregame push before a game | the briefing run failed before step 0, or skipped it; or the one-shot was never created (`list_triggers` with recurring false shows `MLB pregame: ...` rows) | the briefing run log; `python3 scripts/mlb_pregame.py --text` locally shows what it should have scheduled; create the missing one-shot by hand from that output |
| ESPN proposal email has no `ff-alerted` label an hour later | doorbell never ran or the fire returned non-2xx | same as above; `resetDoorbellState` in the Apps Script editor makes it fire again for a message already on record |
| Claim row says "pass: you'd give up priority #N for +0.3/wk" on a player I obviously want (a one-week fill-in, or the wire is stacked) | `_priority_note` in `report.py` compares `claim_gain` (the ROS upgrade, or a one-week fill-in's points spread over the weeks left) with `model/waivers.py` `priority_cost`: holding #N vs holding last over today's claim-worthy wire (`delta_over_starter >= CLAIM_WORTHY_PPW`), `RIVAL_CLAIM_P` (0.35) per team ahead, discounted `(weeks-1)/(2*weeks)` | the two numbers are on the row; `skip`/`amend` it in reads.json when the research says otherwise (a short-week fill-in with a bye crunch, a wire the card overrates). A league that resets priority weekly must read `waiver_order: reset` in the packet settings; if it says `rolling` and ESPN says "Waiver Order Reset: Yes", the `waiverOrderReset` mapping in `sources/espn.py` `waiver_order` is backwards |
