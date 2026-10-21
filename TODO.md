# TODO — the backlog, one PR per item

Findings from the 2026-10-08 line-by-line review, ordered by how much each one changes the numbers Dustin acts on.
ROADMAP.md says where the model should go; this file says what to do next and how to know it is done. Pick the
top unchecked item in the highest tier, make one PR, delete it, add a row to the CLAUDE.md failure table if the fix
closes a failure mode. Name functions and constants, never line numbers; they drift.

Sizes: XS under an hour, S a morning, M a day or two, L a week with a plan in `docs/plans/`.

## Working an item in a fresh session

Dustin's prompt is one line: "Read CLAUDE.md and TODO.md, take the top unchecked item (or item <id>), fix it, and open a PR."
Run as a loop, one fresh session per item: `docs/ralph-loop.md`.
The session then:

1. Reads CLAUDE.md (the boundary rule, the layout, the failure table) and this file. Reads the files the item names
   before touching anything; the line numbers drift, the function names do not.
2. In the cloud, runs `bash scripts/cloud_setup.sh` before anything that touches ESPN: it writes `.env` and
   `leagues.toml` from the environment variables (`ESPN_S2`, `SWID`, `LEAGUES_TOML`) and runs `ff doctor`. The
   cookies are in the `fantasy` environment; a session that skips this reports "no cookies" or "no leagues.toml"
   and leaves a live pull, the replay files or a probe undone (four of the eight Tier D sessions on 2026-10-20 did).
3. Reproduces the finding first: a failing test, or the probe the item describes (`uv run ff briefing --demo`, a
   fixture from `tests/`, the projlog branch via `git fetch origin projlog`). An item that cannot be reproduced is
   reported back, not fixed on faith.
4. Fixes that one item and nothing else. Scope creep is the thing this list exists to prevent; a second finding on
   the way is a new line here, not a second change in the PR.
5. Adds the test that would have caught it, runs `uv run pytest` and `uv run ruff check`, and `uv run ff briefing
   --demo --short` to see the card still renders.
6. Deletes the finished item from this file (a ticked box is not a record: anything learned goes to the CLAUDE.md
   failure table when the fix closes a failure mode Dustin could see in an email, or to the relevant `docs/plans/`
   file otherwise). The commit history is the log of what was done.
7. Opens a PR titled after the item id and its first clause; the body says what was wrong, what changed, how it was
   verified. Code reaches the cloud routine only after merge to main.

Rules that hold for every item: read-only against ESPN; code owns numbers, Claude owns prose; never commit
`briefing.md`, `overrides.json`, `reads.json`, `data/`, `leagues.toml` or `ops.local.md`; a test that only asserts
"no exception" does not count as the test.

## Tier A — bugs that distort every number today

(none open)

## Tier B — checklist and ledger bugs

(none open)

## Tier C — operations

- [ ] **C7 (M). The email goes out over HTTPS: an Apps Script relay in place of SMTP.** C5/C6 made `ff email`
  (`src/ff/mail.py`, Gmail SMTP on port 465) the send path, and the 2026-10-21 check from a fresh `fantasy` session
  showed why it never sends there: the cloud container's egress is a web proxy that carries HTTP and HTTPS only, so
  `smtplib.SMTP_SSL("smtp.gmail.com", 465)` times out after 60 s with Network access on Full, and the skill falls back
  to the connector paste every morning (the credentials were removed from the environment the same night). The fix is
  a relay the proxy can reach: a Google Apps Script web app in Dustin's account (`scripts/gmail_send_relay.gs`, setup
  in `scripts/gmail_send_relay.md`, next to the doorbell's `gmail_trade_doorbell.gs`) that takes a POST of
  `{token, subject, to, markdown, html}` and calls `GmailApp.sendEmail` with the HTML body and the markdown as the
  plain part; `mail.send` POSTs to `FF_MAIL_RELAY_URL` with `FF_MAIL_RELAY_TOKEN` when both are set, falls back to
  SMTP when only `GMAIL_USER`/`GMAIL_APP_PASSWORD` are, and `mail.status()` / `ff doctor` name which path. Byte for
  byte stays: the test holds the relay payload's html and markdown to the files. The `.gs` gets a Node test like
  `scripts/gmail_trade_doorbell.test.js` (a bad token is a 403, a missing field is a 400, one send per request).
  Both skills keep their fallback wording; `docs/operations.md` lists the two new env vars and the deploy steps.

## Tier D — where real edge would come from (after Tier A)

- [ ] **D2 (S, waiting on data). Adopt the fitted variance** per position. The fitter exists since 2026-10-08
  (`ff accuracy --fit`, `projlog.sigma_fit`): it fits `BASE_SIGMA` and `CV_FLOOR` in `model/projections.py` to the blend
  residuals in the optimizer's own shape and refuses a position under `projlog.FIT_MIN_N` (150) scored forecasts. As
  of 2026-10-20 (weeks 1-6 scored) the samples are QB 31, RB 70, WR 67, TE 31, K 16, D/ST 16, so every constant is
  still the prior. A scored week adds about 11 RB, 11 WR, 5 QB and TE, 3 K and D/ST: RB and WR cross 150 once week
  13-14 of 2026 is scored (the week-14 or week-15 log), QB and TE late in 2027, K and D/ST not before 2029 (pool them
  across positions or lower the bar with a reason). Checked 2026-10-20: `ff accuracy --fit` printed `keep prior` on
  every row, nothing to adopt; do not pick this item again before the week-14 log is in. When a row says `fit`: copy the printed pair into `model/projections.py` with the sample size and
  date in the comment and the old value kept, and only then revisit `MIN_WIN_GAIN` in `model/lineup.py` (1.5pp): the
  early fits read wider than the priors (RB 10.8 vs 6.5, WR 12.2 vs 6.5), so the floor comes down only if a real fit
  says sigma is smaller, and in proportion. Code owns the numbers: take what the fitter prints or leave the prior.
- [ ] **D13 (S, needs the replay files). The floor prior for the wire body with no preseason total.** The first claim
  replay (`docs/accuracy.md`, "The claim ranking", 2026-10-21): the card's first claim per team-week realized 4.5-7.6 a
  week under the starter it displaces, and every one of the 96 first-claim rows whose body scored zero in every later
  week (five to seven distinct players per league, Carson Wentz in week 2 the first claim for most of every league) has
  `proj_season` 0: ESPN gave him no preseason total, `season_pg` in `model/projections.py` has no prior to fade, and his
  rest-of-season price is his last game or two (`tests/test_backtest.py`, the `_dark_replay` test: 19.5 a game after
  one 25-point game, 11.2 for the same games with a prior). The live ranking reads the same `projected_total_points`.
  Done 2026-10-21 (a session without `leagues.toml`, so no replay to decide on): `score_claims` marks `claimed_dark` /
  `starter_dark`, `claim_hits` splits every sample into `nobody_dark`, `went_dark` and `dark_no_prior` with the
  distinct `bodies` behind each n, `blend` records `prior_pg` in `sources` and each claim row carries `no_prior`;
  `ff backtest --claims` prints them. Left: the floor itself (the position's replacement level, or ESPN's weekly
  number alone until he has a month of games), decided on those printed rows: pull the replay (`ff replay-pull
  --season 2026`, the cookies), read the `dark, no preseason total` and `both on the field after` rows, build the
  floor in `blend` (replacement level needs a second pass: `replacement_levels` runs after everyone is priced), and
  print the tables again. Not a `CLAIM_WORTHY_PPW` change: the clean claim-worthy rows realize more than they promise.
- [ ] **D14 (XS, end of the regular season). Re-read `CLAIM_WORTHY_PPW` (1.0)** on the full-season claim replay after
  D13 (`ff replay-pull --season 2026`, `ff backtest --claims`): the ruling of 2026-10-21 is stays, on clean claim-worthy
  rows of n 10, 29 and 6 realizing +4.7, +3.7 and +1.6 against a promise of +1.5; the bar moves only if the 1-2 bin's
  clean rows realize under a point in all three leagues over the season.
- [ ] **D15 (XS, end of the regular season). Re-read `MUST_TRY_PPW` (2.0)** on the full-season scan replay
  (`ff backtest --scan`, minutes per league): the ruling of 2026-10-21 is stays, the 2-4 bin realizing +2.4 to +3.6 in
  all three leagues on five weeks; the bar moves down only if the 1-2 bin realizes its promise at a hit rate over 0.55 in
  all three, up only if the 2-4 bin falls under +2.
- [ ] **D16 (XS, end of the regular season). Re-read `SEND_MIN_PPW` (1.0)** on the same scan replay: the 0-1 bin is noise
  in every league (hit 0.47-0.57, realized -0.3 to +2.0) and the 1-2 bin realized +0.78 in L2 at a coin flip; 1.5 is the
  case if the 1-2 bin realizes under a point in two leagues over the season, and a ruling on it is one line here, not a
  constant change without the table.
- [ ] **D10 (L, planned). The fitted projection model.** Plan: `docs/plans/fitted-projection.md` (2026-10-21). ROADMAP
  item 1's historical half, on nflverse weekly stats 2016-2025 (`opfit.py`, `ff fit-opportunity`; the network, no
  cookies), each term fitted leave-one-season-out in the live arithmetic's own shape and adopted only when it beats the
  prior out of sample; the backtest harness (`docs/plans/backtest.md`) and the projlog score what the fit cannot. Step 1
  done 2026-10-21: `OPPORTUNITY_WEIGHT` and `OPPORTUNITY_RATIO_CLIP` fitted (QB 0.57, RB 0.64, WR 0.58, TE 0.67; the
  clip off inside the data) and `XFP_PER_ATTEMPT` (0.415), so QB reads his attempts. Left, one PR each, in order:
  2. the opponent factor (`opfit.fit_opponent`: points allowed per position by each defense over the season so far,
  adjusted for the offenses faced, as a capped multiplier on this week's number; ROADMAP item 5's open piece); 3. the
  implied-total term (`VEGAS_K` fitted on nflverse `schedules` `spread_line` / `total_line`, ROADMAP item 4's open
  calibration); 4. the recent-usage trend (the last three games' share against the season's, a second term on the
  rest-of-season level, the same closed form as step 1); 5. the blend with consensus by out-of-sample error (the
  historical model's weekly number against ESPN's in the 2026 replay and the projlog; needs the replay files and the
  cookies). Each step's done-when and what it must not read are in the plan.
- [ ] **D9 (S). The variance sign on a trade's `my_gain`.** `docs/plans/trade-acceptance.md` question 4: a consolidation
  (fewer, bigger starters) gets +10% on `my_gain` when my playoff odds are under 40% and -10% when they are over 70%,
  the research's Skinner result (an underdog buys variance, a favorite buys floor); title odds as the objective only
  once the sim runs 10k for the top three, which the `MUST_TRY_PPW` comment says it cannot today. After B16.

## Tier E — tests that would catch model errors

(none open)
