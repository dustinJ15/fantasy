# ff — fantasy football co-manager

Three ESPN redraft leagues (`leagues.toml`, untracked; copy from `leagues.example.toml`). **Read-only against ESPN**: never propose or build lineup/waiver/trade
writes or ESPN chat posting. Dustin taps the buttons.

## Boundary rule
Code owns state and math. Claude owns judgment over unstructured text and prose.
Claude returns *parameters and prose*, never *decisions or state*. Every number in the briefing comes from `ff`.

## Morning routine (`/briefing` skill encodes this)
1. `uv run ff doctor` — stop and tell Dustin if cookies are dead.
2. `uv run ff sync && uv run ff packet` → `data/packets/<date>.json`.
3. Read the packet. `shared.injury_watchlist` lists players with ambiguous designations across all my rosters;
   `shared.injured` lists the ones out a week or more (or on IR) whose return timeline needs a number.
   WebSearch each one (beat writers, practice reports). Also skim for narrative shifts on my players and top waiver targets
   (committee → bellcow, QB change, coach comments).
4. Write `overrides.json`: `{"<espn_id>": {"p_zero": 0.15, "mu_mult": 1.1, "weeks_out": 4, "ros_mult": 0.9, "note": "..."}}` only where
   news changes the picture. `p_zero`/`mu_mult` are this week; `weeks_out` (games, or `"season"`) and `ros_mult` are the rest of the
   season and decide the hold / IR / drop / trade row for a hurt player. The `note` is shown next to the player in the email.
5. `uv run ff briefing --overrides overrides.json` → markdown + packet path. Then write `reads.json`
   (`{"L1": {"read": "...", "items": {"<row id>": {"verdict": "do|skip|amend", "note": "..."}}, "paste": "...", "paste_to": "...",
   "reply": "...", "reply_to": "..."}}`): rule on rows in `items` (the ids print in backticks at the end of each briefing.md
   checklist line) rather than arguing with the card in prose, every `trade` row needs a verdict, and `read` carries only
   what the research adds; `reply` only when `incoming_trades` has an offer.
   Then `uv run ff render-email --packet <path> --reads reads.json --out briefing.html --md briefing.md`. Never hand-edit the HTML;
   `src/ff/email_html.py` owns the layout.
6. Email it to Dustin via the Gmail connector (subject: `FF briefing — Week N — <date>`).

Tuesday = waivers emphasis (bids due before Wednesday processing). Sunday morning = final lineup + inactives check.

## Commands
`ff setup-check | doctor | sync | roster | lineup | waivers | trades | incoming | odds | packet | briefing | render-email` (all accept `--league <name>`).
`ff incoming` = offers other managers sent me, with an accept/decline/counter verdict (`--json --new-since 40m` is the poller path).

## Layout
`src/ff/sources/*` data pulls (cached in `data/cache/`), `src/ff/model/*` math (`injuries.py` is the hold / IR / drop / trade
rule; `mu_ros` is availability-weighted, `mu_ros_active` is per game played; `season.py` prices a roster week by week with
byes, return dates and the wire as the fallback body; `acceptance.py` is the would-he-say-yes scorecard behind every trade
row, `trades.py` the scan and the hard rules), `packet.py` builds the DecisionPacket,
`report.py` renders markdown (plain-text body) and owns the checklist itself (`todos` builds the rows and their ids,
`apply_reads` folds Claude's per-row verdicts in, `read_lint` catches a typo'd id or an unruled trade),
`email_html.py` renders the HTML email from the packet. Tests: `uv run pytest`.
`demo.py` is the synthetic league (fictional, seeded names); `scripts/screenshots.sh` regenerates `examples/` including the README images.
The Gmail doorbell is Apps Script, so pytest cannot see it: `node scripts/gmail_trade_doorbell.test.js` runs it against a stubbed
Apps Script runtime (retries, escalation, no-double-fire). Run it after editing the `.gs`, before pasting into the editor.

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
  Backstop: `.github/workflows/trade-poll.yml` runs `ff incoming --new-since 6h` in season, dedupes by offer id via
  `actions/cache`, and fires the same routine. The cron asks for hourly but GitHub delivers roughly every 3h on a quiet
  repo, so the window is deliberately wider than the cadence; overlap is free because ids are deduped.
  GitHub needs secrets `ESPN_S2`, `SWID`, `FF_ROUTINE_FIRE_TOKEN` and variables `FF_TRADE_ROUTINE_ID`, `SEASON`, `LEAGUES_TOML`.
- MLB pregame alerts (baseball, same env): step 0 of the briefing skill runs `python3 scripts/mlb_pregame.py`, which reads
  MLB's schedule and prints one one-shot spec (name, `run_once_at` = first pitch minus `LEAD_MIN`, prompt) per first pitch
  among today's games that matter (postseason, or `WATCH_TEAMS` through `REGULAR_SEASON_LAST_DAY`); the briefing session
  creates each with `create_trigger` (fresh session, push notification) and the one-shot's reply is the push. The prompt
  is `.claude/skills/mlb-pregame/SKILL.md` inlined: a session a routine spawns has no repo checkout and no trigger tools,
  which is why this rides the briefing routine (created in the UI with the repo and the Claude Code Remote connector)
  instead of a routine of its own, and why there is no token, state file or GitHub cron (the old workflow ran hours late
  and never had a fire token). `python3 scripts/mlb_pregame.py --text` shows today's plan.
- Debug a run: `RemoteTrigger list_runs` (trigger_id in ops.local.md) → `get_run_log` on the newest session. Re-run: `RemoteTrigger run`.
- Reproduce locally: `uv run ff doctor && uv run ff sync && uv run ff briefing --short --sims 500`. Local `.env` has the same cookies.
  No credentials at all: `uv run ff briefing --demo` (synthetic league from `src/ff/demo.py`).
- Code changes take effect on the next cloud run only after `git push` to main (the VM clones fresh each time).
- Projection logs: the routine pushes `data/projlog/` to the `projlog` branch, never main. To run `ff accuracy` locally:
  `git fetch origin projlog && git checkout origin/projlog -- data/projlog`. The log (`src/ff/projlog.py`) keeps the
  pre-clock projection (`mu_pre`) and ESPN's actual in league scoring (`actual` once his game is `post`, `actual_prev`
  in the next week's first log for Monday night); the scorer takes each player's last pre-kickoff row per league, so K
  and D/ST are scored and half-PPR is scored as half-PPR. No nflverse, no crosswalk; it runs offline.
- Skipped trade rows are remembered: `ff render-email --reads` writes each `skip` on a `trade:` row to
  `data/projlog/skipped_trades.json` (`src/ff/rulings.py`), the packet drops that package for 14 days, and the file rides
  the `projlog` branch (cloud_setup.sh restores it). A `do`/`amend` is not remembered.
- Offer outcomes: every offer of mine in `outgoing_trades` is opened in `data/projlog/offer_outcomes.json` the morning it
  shows and closed the morning it is gone (`src/ff/rulings.py` `record_outcomes`, run by `ff packet`): accepted when the
  players I asked for are on my roster, expired when its expiry passed, declined otherwise. The scan reads it per rival
  (`history`): a no in the last 7 days is a factor on every package to him, and after two answers his rate is a prior.
  Rides the `projlog` branch. `ff trades --explain` prints the scorecard behind each row (p(accept), its factors, what he
  is left with, the fallback package for when he says no).
- Pushed trades: the one package the scan marks `must_try` (sendable and ≥ +2.0 ppw for me) or that Claude rules `push` on
  (with a note) is recorded in `data/projlog/pushed_trades.json` by `ff render-email` and comes back at the top of the card
  every morning ("asked N mornings running") until it shows up in my pending offers (sent), Claude rules `skip` on it, or
  the scan stops producing it. One push per league at a time; the packet only reads the memory.
- IR slot moves: `ff packet` notes who sits in each league's IR slot in `data/projlog/ir_moves.json` (`src/ff/rulings.py`
  `note_ir_roster`, before the injury rule runs, so the morning he comes off IR already counts) and stamps `left` when a
  player comes off the slot and `stashed` + `added` (the names that joined the roster that run) when one goes on. A player
  who left the slot in the last `IR_REENTRY_DAYS` (10) is not stashed again unless he is out `IR_REENTRY_WEEKS` (3) or more;
  the hold row says the tag is bouncing. The activate row names the drop as "added when he was stashed <date>" when it is
  the body that stash brought in. Rides the `projlog` branch.
- Checklist ledger: `report._Spots` hands out roster spots (open bench spot first, then the cheapest drop not already
  named), so an activation and a pickup never spend the same drop. It also counts bodies per position against ESPN's
  caps (`settings.position_limits`): a trade row that brings in a WR at the cap says which WR to drop in the trade
  screen, and skips that when a pickup above it already dropped one. Waiver rows say `claim` (still on waivers, with the
  priority) or `add` (free agent) from `waiver_status` in the snapshot.
- Questionable sit-risk is day-aware (`QUESTIONABLE_BY_WEEKDAY`: 15% Mon–Wed, 20% Thu, 30% from Fri); a `p_zero` override wins.
  An IR stash is activated only when ESPN's designation leaves the IR-eligible set, never from the guessed return week.
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
| Card says "activate" on a stash still listed Out, or names one drop on two rows | old checklist logic (fixed 2026-09-23) | activation keys off `ir_eligible`; drops come from `report._Spots` |
| Card says activate, then "move to IR" three days later, then activate again (Daniels, Sep 30 to Oct 7: a four-day McGowan rental) | ESPN's tag bounced Questionable → Out → Questionable and the stash rule had no memory of the activation | fixed 2026-10-07: `ir_moves.json` remembers the exit; a short Out inside `IR_REENTRY_DAYS` holds instead. If it still churns, check the projlog branch restored the file and that `weeks_out` in overrides.json is not inflating a one-week Out |
| Same trade package returns the morning after a `skip` | `data/projlog/skipped_trades.json` missing (projlog branch not restored) | check cloud_setup.sh fetched `origin/projlog`; the key is `<league>|<get names>` |
| Email card says do it and Claude's read says don't | a row was argued with in prose instead of ruled on | `items` in reads.json: `skip` strikes the row, `amend` corrects it; `ff render-email` warns about unruled trade rows |
| Cloud Bash killed a long command | 120 s default timeout | run `ff` steps with timeout 600000, never `&` |
| Email says hold a player who is done for the year, or trade/drop one who is back Sunday | `weeks_out` still at its designation default (IR = 4, Out = 1) | the player is in `shared.injured`; write `weeks_out` (or `"season"`) in overrides.json and re-run step 5 |
| Card says drop a hurt starter (or hold a backup who is plainly dead weight) | `mu_ros_active` is off: ESPN docked his season total for the injury, or his healthy level is not what ESPN thinks | `shared.injured` shows `mu_ros_active`; write `ros_mult` in overrides.json; the drop rule fires when he is below replacement on return |
| Card says move a player to IR and the app refuses | league's IR eligibility is stricter than `IR_ELIGIBLE` in `model/injuries.py` | `scripts/probe_injuries.py` shows what ESPN says; narrow the constant |
| Briefing says "could not read pending trades" | ESPN changed `mPendingTransactions` or cookies half-dead | check `pending_trades_error` in the packet; `ff incoming --force` locally |
| trade-poll workflow red | cookies dead in GitHub secrets, or fire token revoked | update repo secrets; `gh workflow run trade-poll.yml -f window=48h` to test |
| "Summary of failures for Google Apps Script" naming one or two runs | transient Google backend fault | ignore; the doorbell retries in-run and re-runs the next minute. Apps Script only reports it after 5 consecutive failed runs |
| Email "FF trade doorbell — cannot reach the trade routine" | 3 fires in a row rejected: token rotated (401/403) or routine id wrong (404) | fix the Script Property; `fireTestOffer` in the Apps Script editor re-checks the path |
| Trade offer email never arrives but the offer is in ESPN | doorbell silent (Apps Script trigger gone, Script Properties cleared, token rotated) and poller missed it or routine disabled | Apps Script Executions log; confirm Script Properties `FF_TRADE_ROUTINE_ID` + `FF_ROUTINE_FIRE_TOKEN` are still set and the 1-minute trigger exists; `RemoteTrigger get` on the trade routine; it still appears in the next morning briefing |
| Trade screen says "Too many players with default position WR (maximum 6)" on a trade the card proposed | the league caps rostered players per position (`position_limits` in the settings, from ESPN's `positionLimits`); the scan used to ignore it | fixed 2026-09-24: the trade row now names the drop ESPN wants in the trade screen (`drops` on the candidate, cheapest body at that position, IR stash never). If ESPN does not actually demand the drop the card names, the IR occupant should stop counting: see `over_cap` in `model/trades.py` |
| Rival laughs at a 2-for-1 the card called "neutral for them" (his backup QB, the market's QB3, for a QB nobody wants plus a mid RB) | lineup math prices a rival's bench at zero, and the market ratio summed the package so the throw-in rode in on the other piece's value | fixed 2026-10-06: `throw_ins` in `model/trades.py` drops a package with a piece he would neither start nor price (`THROW_IN_FRAC`); the row also warns when I ask for a player he starts today, and when a 2-for-1 forces a cut on his full roster. Same rule discounts throw-ins in offers I receive |
| Card proposes two mid pieces for a top-10 player, or asks a one-QB team for its QB and the paste says "you're set at QB" | the scan sums market value linearly, rewards me getting the best player (`consol`), never depth-checks the rival, and counts his IR bodies as cover | `docs/plans/trade-acceptance.md` (evidence: 17 of 19 skips on the projlog branch were that shape). Since 2026-10-07 `model/trades.py` taxes the side sending more bodies (`CONSOLIDATION_TAX`, `fairness`), refuses a star ask that does not send a top-24 piece back with the premium (`is_star`, `STAR_PREMIUM`), asks for a QB only from a roster with two startable ones (`startable_qbs`), depth-checks the rival, prices both rosters week by week with the wire as the fallback (`model/season.py`), ranks by `p_accept` × my gain (`model/acceptance.py`; the row says "coin flip" or "he'd likely take it" and what he is left with at the slot), shows two rows and no "reach". If a row still looks like a lowball, `ff trades` prints `p(accept)` with the factors; tune the factor in `acceptance.score`, not the row |
| Hold, trade and drop rows value every player more each week (an injured player's hold row most of all), playoff and title odds drift up, a 14-a-game WR reads 19 a game in October | `mu_ros_active` divided ESPN's full-season total by the weeks left, so the inflation was `17 / weeks_remaining` | fixed 2026-10-08 (TODO A1): the per-game base is season-to-date points per game with `proj_season / 17` as a prior that fades out by game six (`season_pg` in `model/projections.py`), shrunk toward the matchup-neutral weekly blend; `espn_pg` (the rival's view) is the same arithmetic on ESPN's numbers. If a healthy starter's ROS/g is still far from his weekly projection, check `games_played` and `ytd_pg` in his `sources` |
| `ff accuracy` shows a blend MAE under 1, or no K / D/ST rows, or a week missing | logs before 2026-10-08 scored Monday's banked points against themselves (fixed, TODO A2); a week with no Monday log and no log the Tuesday after has no truth (the routine skipped both days) | the harness scores a forecast only when a `post` row or the next week's `actual_prev` exists for it; `ff accuracy` with the projlog branch restored lists what it could score; nothing to fix for a skipped week, the row is simply absent |
| No MLB pregame push before a game | the briefing run failed before step 0, or skipped it; or the one-shot was never created (`list_triggers` with recurring false shows `MLB pregame: ...` rows) | the briefing run log; `python3 scripts/mlb_pregame.py --text` locally shows what it should have scheduled; create the missing one-shot by hand from that output |
| ESPN proposal email has no `ff-alerted` label an hour later | doorbell never ran or the fire returned non-2xx | same as above; remove the label (if any) to make the script retry |
