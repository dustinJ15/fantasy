# Operations

For a fresh session responding to a morning email, or anyone debugging the cloud routines, the trade alerts and the
memories on the `projlog` branch. Moved whole from CLAUDE.md on 2026-10-20 (Docs-1); CLAUDE.md keeps the four lines
every session needs. Trigger ids, the env id, routine URLs and the recipient address live in `ops.local.md`
(untracked) and in memory; nothing personal is tracked.

- Routine "FF daily briefing": cron `CRON_TZ=America/Denver 59 5 * * *` (5:59 AM Denver year-round; it was `0 12 * * *` UTC
  until 2026-10-08, which drifts an hour at each DST change), cloud env `fantasy` (network Full, env vars
  ESPN_S2/SWID/SEASON/HEALTHCHECK_URL/BRIEFING_TO/FF_MAIL_RELAY_URL/FF_MAIL_RELAY_TOKEN/LEAGUES_TOML), model `claude-opus-5`.
  `scripts/cloud_setup.sh` writes `.env` and `leagues.toml` from those env vars. The briefing is emailed to `$BRIEFING_TO` by
  `ff email` (`src/ff/mail.py`): an HTTPS POST of the two rendered files to a Google Apps Script web app in Dustin's
  account (`scripts/gmail_send_relay.gs`, deploy steps and the token in `scripts/gmail_send_relay.md`; `FF_MAIL_RELAY_URL`
  is its `/exec` URL, `FF_MAIL_RELAY_TOKEN` the shared secret, also a Script Property there) that sends with `GmailApp`.
  Gmail SMTP (`GMAIL_USER`/`GMAIL_APP_PASSWORD`, the app password from Google account > Security > App passwords) is the
  path only when the relay variables are absent, and never works from the cloud container: its egress is a web proxy
  that carries HTTP and HTTPS only, so port 465 hangs for 60 s and the skill pasted the email into the Gmail connector
  every morning until the relay (C7, 2026-10-21). `ff doctor` prints `mail.status()`, which path the run will take; the
  briefing and trade-offer skills paste the files into the Gmail connector only when `ff email` fails (C5, C6). After
  editing the `.gs`: `node scripts/gmail_send_relay.test.js`, paste it in, and **Deploy > Manage deployments > New
  version** (the `/exec` URL serves the deployed version, not the editor's). A second routine, "FF Sunday lineup check"
  (`CRON_TZ=America/Denver 45 9 * * 0`, same env and prompt with a preface: inactives are out, research only my questionable
  starters, email the final lineups as `FF Sunday check — Week N — <date>`, skip waivers, trades and the MLB step 0), runs
  after the 11:30 ET inactives. The routines UI stores a plain cron in UTC; a timezone needs the **Custom** trigger with the
  `CRON_TZ=` prefix typed in, which the UI accepts and displays in local time.
- Incoming trade offers: every pending offer shows in the morning briefing (`incoming_trades` per league, first checklist item).
  Primary alert path: a Google Apps Script doorbell (`scripts/gmail_trade_doorbell.gs`, setup in `scripts/gmail_trade_doorbell.md`)
  runs every minute in Dustin's Gmail, finds ESPN's "Trade Proposal" emails of the last 2 hours, fires the "FF trade offer"
  routine's API trigger (`/trade-offer` skill, emails `FF trade offer — <league> — <date>`) once per message id it has not
  fired for (`ff_fired_message_ids` in Script Properties, pruned after 3 days) and labels the thread `ff-alerted`. The label
  is a marker only: ESPN's subject is identical every time, so proposals thread together and the id record, not the label,
  decides what is new. The trigger id and fire token live only in the script's Script Properties (nothing in the repo).
  Backstop: `.github/workflows/trade-poll.yml` runs `ff incoming --new-since 6h` in season, dedupes by offer id via
  `actions/cache`, and fires the same routine. The cron asks for hourly but GitHub delivers roughly every 3h on a quiet
  repo, so the window is deliberately wider than the cadence; overlap is free because ids are deduped. Whether a
  scheduled run polls is `scripts/trade_poll_gate.py` (stdlib, Denver time, `tests/test_trade_poll_gate.py`): Sep-Jan,
  every weekday, every hour but 1-5 AM Denver, so an evening offer is seen within the cadence instead of waiting for
  the briefing (the gate skipped Monday and UTC 0-11, every Denver evening, until 2026-10-08). `python3
  scripts/trade_poll_gate.py --now <ISO>` answers "would it have polled then".
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
- Projection logs: the routine pushes `data/projlog/` to the `projlog` branch, never main, through
  `scripts/projlog_push.sh "<message>"` (step 9 of the briefing skill): it fetches the remote tip, builds the commit in a
  temporary index (`data/projlog` additions and edits only, never a deletion), parents it on that tip and pushes a plain
  fast-forward, so the checkout, main and the branch's history are never touched; a rejected push refetches and rebuilds,
  up to three times. `scripts/projlog_push.sh --restore` is the other direction (`git archive` of the tip's
  `data/projlog` into the working tree as untracked files; cloud_setup.sh runs it when the directory is missing), and
  is also how to get the logs locally before `ff accuracy`. The log (`src/ff/projlog.py`) keeps the
  pre-clock projection (`mu_pre`) and ESPN's actual in league scoring (`actual` once his game is `post`, `actual_prev`
  in the next week's first log for Monday night); the scorer takes each player's last pre-kickoff row per league, so K
  and D/ST are scored and half-PPR is scored as half-PPR. No nflverse, no crosswalk; it runs offline.
  `uv run ff accuracy --fit` (`projlog.sigma_fit`) fits `BASE_SIGMA` / `CV_FLOOR` per position to the blend residuals
  in the optimizer's own shape (`max(0.6 × BASE_SIGMA, CV_FLOOR × mu)`, Gaussian NLL on a grid, deterministic) and
  prints them next to the constants in `model/projections.py`; it writes nothing, and a position under
  `projlog.FIT_MIN_N` (150) scored forecasts reads `keep prior`. TODO D2 says when each position gets there.
- Skipped trade rows are remembered: `ff render-email --reads` writes each `skip` on a `trade:` row to
  `data/projlog/skipped_trades.json` (`src/ff/rulings.py`), the packet drops that package for 14 days, and the file rides
  the `projlog` branch (cloud_setup.sh restores it). A `do`/`amend` is not remembered.
- Offer outcomes: every offer of mine in `outgoing_trades` is opened in `data/projlog/offer_outcomes.json` the morning it
  shows and closed the morning it is gone (`src/ff/rulings.py` `record_outcomes`, run by `ff packet`): `accepted` when the
  players I asked for are on my roster and mine are gone, `countered` when he has a counter pending or a different
  package with him went through, `expired` when ESPN's expiry (`expires_ts`, compared to the run's clock) passed,
  `withdrawn` when a piece I offered left my roster with nothing back (ESPN voids the proposal), `declined` otherwise.
  The scan reads it per rival (`history`): a `declined` in the last 7 days is a factor on every package to him, and after
  two answers (accepted / declined / expired) his rate is a prior; a counter or a withdrawal is not an answer.
  Rides the `projlog` branch. `ff trades --explain` prints the scorecard behind each row (p(accept), its factors, what he
  is left with, the fallback package for when he says no).
- Pushed trades: the one package the scan marks `must_try` (sendable and ≥ +2.0 ppw for me) or that Claude rules `push` on
  (with a note) is recorded in `data/projlog/pushed_trades.json` by `ff render-email` and comes back at the top of the card
  every morning ("asked N mornings running") until it shows up in my pending offers (sent), Claude rules `skip` on it, or
  the scan stops producing it. A math push also drops the morning its row is no longer `sendable` (`report.todos`); a
  Claude push stays whatever the math says. One push per league at a time; the packet only reads the memory.
- IR slot moves: `ff packet` notes who sits in each league's IR slot in `data/projlog/ir_moves.json` (`src/ff/rulings.py`
  `note_ir_roster`, before the injury rule runs, so the morning he comes off IR already counts) and stamps `left` when a
  player comes off the slot and `stashed` + `added` (the names that joined the roster that run) when one goes on. A player
  who left the slot in the last `IR_REENTRY_DAYS` (10) is not stashed again unless he is out `IR_REENTRY_WEEKS` (3) or more;
  the hold row says the tag is bouncing. The activate row names the drop as "added when he was stashed <date>" when it is
  the body that stash brought in. Rides the `projlog` branch.
- Checklist ledger: `ledger.Spots` (re-exported as `report._Spots`) hands out roster spots (open bench spot first, then the cheapest drop not already
  named), so an activation and a pickup never spend the same drop. It also counts bodies per position against ESPN's
  caps (`settings.position_limits`): a trade row that brings in a WR at the cap says which WR to drop in the trade
  screen, and skips that when a pickup above it already dropped one. Waiver rows say `claim` (still on waivers, with the
  priority) or `add` (free agent) from `waiver_status` in the snapshot; in a rolling-priority league (`settings.waiver_order`
  from ESPN's `waiverOrderReset`) a claim row also prices the priority it spends (`model/waivers.py` `priority_cost`: the
  value of holding #N less that of holding last, over the wire's claim-worthy upgrades with `RIVAL_CLAIM_P` per team ahead,
  times `(weeks-1)/(2*weeks)`) and says "worth it" or "pass"; a weekly reset to reverse standings costs nothing and prints nothing.
