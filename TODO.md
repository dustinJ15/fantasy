# TODO — the backlog, one PR per item

Findings from the 2026-10-08 line-by-line review, ordered by how much each one changes the numbers Dustin acts on.
ROADMAP.md says where the model should go; this file says what to do next and how to know it is done. Pick the
top unchecked item in the highest tier, make one PR, delete it, add a row to the CLAUDE.md failure table if the fix
closes a failure mode. Line numbers are as of commit 82c3480.

Sizes: XS under an hour, S a morning, M a day or two, L a week with a plan in `docs/plans/`.

## Working an item in a fresh session

Dustin's prompt is one line: "Read CLAUDE.md and TODO.md, take the top unchecked item (or item <id>), fix it, and open a PR."
The session then:

1. Reads CLAUDE.md (the boundary rule, the layout, the failure table) and this file. Reads the files the item names
   before touching anything; the line numbers drift, the function names do not.
2. Reproduces the finding first: a failing test, or the probe the item describes (`uv run ff briefing --demo`, a
   fixture from `tests/`, the projlog branch via `git fetch origin projlog`). An item that cannot be reproduced is
   reported back, not fixed on faith.
3. Fixes that one item and nothing else. Scope creep is the thing this list exists to prevent; a second finding on
   the way is a new line here, not a second change in the PR.
4. Adds the test that would have caught it, runs `uv run pytest` and `uv run ruff check`, and `uv run ff briefing
   --demo --short` to see the card still renders.
5. Deletes the finished item from this file (a ticked box is not a record: anything learned goes to the CLAUDE.md
   failure table when the fix closes a failure mode Dustin could see in an email, or to the relevant `docs/plans/`
   file otherwise). The commit history is the log of what was done.
6. Opens a PR titled after the item id and its first clause; the body says what was wrong, what changed, how it was
   verified. Code reaches the cloud routine only after merge to main.

Rules that hold for every item: read-only against ESPN; code owns numbers, Claude owns prose; never commit
`briefing.md`, `overrides.json`, `reads.json`, `data/`, `leagues.toml` or `ops.local.md`; a test that only asserts
"no exception" does not count as the test.

## Tier A — bugs that distort every number today

(none open)

## Tier B — checklist and ledger bugs

- [ ] **B1 (S). One drop is spent twice.** `src/ff/report.py:359` reserves only `ir` and `trade` verdict
  players. A `drop`-verdict player is noted (`:362-366`) but never added to `reserved` or `spots.dropped`, so
  `_drop_order` (`:58-60`) hands him out again as the drop for a waiver pickup. Reproduced: two adds against one
  freed spot. `note(drop=)` then runs twice for him, so `cut()` position counts are off by one.
  Fix: add drop-verdict names to `reserved` (or `dropped`) when the row carries an `add`.
  Done when: a test with an injury drop plus a start-worthy pickup names two different drops.

- [ ] **B2 (S). Activation folding is order-dependent.** `report.py:288-312` folds the activate row's drop into
  the drop row only when the activate row comes first; `injuries.decide` orders by `mu_ros_active`, so a cheap
  returning player and a dearer season-ender print both "drop Dart to make room" and "drop Dart: out for the
  season; add X". Pre-compute the activations' drops before emitting any row.
  Done when: `tests/test_review_fixes.py` runs the Daniels/Dart case in both orders.

- [ ] **B3 (S). A remembered push stays "do this one" after the math stops supporting it.**
  `report.py:415-423` never re-checks `sendable` on a remembered math push, and `push_line` still says "too
  good to let slide". Drop a math-sourced push whose row is no longer `sendable`; keep Claude-sourced pushes.

- [ ] **B4 (S). Pushes reopen the morning after a decline.** `src/ff/rulings.py:106-118`: once the sent offer
  leaves `pending_trades`, a `sent` push with `closed != today` falls through to a new `open`. A `sent` or
  `skipped` push should stay closed for `SKIP_DAYS` unless Claude rules `push` again.

- [ ] **B5 (S). Offer outcomes mislabel.** `rulings.py:185-190`: an offer I withdrew, or a counter he accepted
  under a different id, is recorded as his decline and penalises him for 7 days. `:187` compares the expiry
  date only, in machine-local (UTC) time, so an offer that lapsed at 9 PM Denver reads "declined". `:215`
  treats `expired` like `declined` in `history`. Separate withdrawn, expired and declined; only declined should
  carry the `recent_decline` factor.

- [ ] **B6 (S-M). The drop criterion is `mu_ros` alone.** `report.py:60`. It ignores `market.redraft_value`
  and `trend_30d` (already on each roster row via `enrich`), handcuff status, bye timing and this week's
  `p_zero`. A rookie RB the market prices highly is cut before a WR4 nobody would trade for, and the card never
  shows the two numbers side by side. Show market value next to the drop and penalise cutting a player the
  market would pay for (he is trade bait, see the `trade` verdict).

- [ ] **B7 (S). The cover row is not executable.** `report.py:232-234` takes the first waiver at the position
  regardless of `on_waivers` ("add Backup K before kickoff" for a claim that lands Wednesday) and takes no
  spot from the ledger, so no drop is named.

- [ ] **B8 (XS). A skipped hold loses its strike in the HTML.** `src/ff/email_html.py:199` strips `~~` from
  `hold_line`, the only skip marker on holds; the markdown keeps it, the email does not.

- [ ] **B9 (XS). Row ids can collide.** `trade:<get>` (`report.py:446`) ignores `give`; `waiver:<name>` is shared
  by the Waiver and Open-spot rows. Latent today; `apply_reads` would rule both with one key.

## Tier C — operations

- [ ] **C1 (S). The projlog push step fails as written.** `scripts/cloud_setup.sh:31-33` restores
  `data/projlog` as untracked files; `.claude/skills/briefing/SKILL.md:110` then runs
  `git checkout -B projlog FETCH_HEAD`, which git refuses when those files differ, and the fallback branches off
  main and is rejected non-fast-forward. The agent has been improvising each morning (`origin/projlog` has
  commits through 2026-10-07), which is how a day's rulings get lost. Make it a worktree or a stash-free
  copy-and-commit; test it in CI with a scratch remote.

- [ ] **C2 (S). The Gmail doorbell can miss a second proposal in the same thread.**
  `scripts/gmail_trade_doorbell.gs:25` searches `-label:ff-alerted`, `:137` labels the thread, `:110` fires only
  on the newest message. ESPN's subject is identical each time, so a second proposal threads under an already
  labelled one and is never seen. Dedupe per message id (Script Properties or a message-level marker) and add a
  two-messages-in-one-thread case to `gmail_trade_doorbell.test.js`.

- [ ] **C3 (XS). The poller has blind spots.** `.github/workflows/trade-poll.yml:59-60` skips Monday and UTC
  hours 0-11 with a 6h window; evening offers (prime trade time in Denver) wait for the morning briefing.

- [ ] **C4 (XS, routine settings). The briefing cron drifts and the Sunday run is early.** `0 12 * * *` UTC is
  6 AM Denver only during DST; after 2026-11-01 it is 5 AM. Sunday's lineup check at 6 AM MT predates the
  11:30 ET inactives. Use `CRON_TZ=America/Denver` and add a Sunday 9:45 MT run (ops.local.md, not the repo).

- [ ] **C5 (S). The email body is assembled by the LLM.** `briefing/SKILL.md:99-103` has the model paste the
  HTML into the Gmail tool and check `wc -c`. `ff email` already exists (`src/ff/mail.py`); give the cloud env
  `GMAIL_USER`/`GMAIL_APP_PASSWORD` and make the skill call it, with the paste as the fallback.

- [ ] **C6 (XS). Sleeper's week can differ from ESPN's on Monday and Tuesday.** `packet.py:313` fetches
  Sleeper projections for `sleeper.state().week`; ESPN's `current_week` rolls Tuesday. Use the league's week.

## Tier D — where real edge would come from (after Tier A)

- [ ] **D1 (M-L). In-season rest-of-season projection.** Season-to-date points per game, target and carry share
  from `model/usage.py` (computed, rendered nowhere, moves no number), and the weekly blend, with the
  preseason total as a prior that fades by week 6. This is ROADMAP item 1 and the only private edge; plan in
  `docs/plans/`.
- [ ] **D2 (M). Fitted variance** per position from the projlog (fixed 2026-10-08: `ff accuracy` scores pre-kickoff
  forecasts against ESPN's actuals): fit `BASE_SIGMA` and `CV_FLOOR` in `model/projections.py` from the residuals
  (the "then M" half of the old A5). Then `MIN_WIN_GAIN` in `model/lineup.py` (1.5pp since 2026-10-08) can come down.
- [ ] **D3 (M). Waiver priority value.** All three leagues use priority, the model prices FAAB only
  (`model/waivers.py`). A `claim` row should weigh what spending priority N costs against expected future claims.
- [ ] **D4 (M). Playoff schedule weighting** for weeks 15-17 (ROADMAP 5); best acted on weeks 6-10, so now.
- [ ] **D5 (S). Weather into projections.** Fetched per game (`sources/weather.py`), applied nowhere. Wind over
  15 mph: penalty on passing and K.
- [ ] **D6 (S). Research prompt upgrades.** `briefing/SKILL.md:23` budgets ~10 searches for three leagues;
  `:39` says Questionable plus limited Friday is 0.25 while the code's Friday default is 0.30; no guidance on
  `mu_mult`; snap share, route share, depth-chart changes and weather are never asked for. `trade-offer/SKILL.md:17`
  omits `weeks_out` and `ros_mult`, so research on a hurt player cannot reach the math, and `:21` lets the read
  argue with the verdict in prose instead of ruling on it.
- [ ] **D7 (S). Email context.** Per-player opponent and implied total (`sources.implied_total`), kickoff day
  (Thursday players need their moves first), usage trend, and p(accept) on the trade row, not only the word.
- [ ] **D8 (L). Backtest harness** (ROADMAP 8): replay 2025 for lineup P(win) calibration and trade hit rate.

## Tier E — tests that would catch model errors

- [ ] **E1.** `tests/test_lineup.py:69-77` "underdog prefers variance" passes with variance ignored (the WR also
  wins on EV). Give the high-variance player a lower EV.
- [ ] **E2.** `tests/test_packet_synthetic.py:155-170` reconstructs the expected rows from the block it tests
  and branches on the output; `:155`'s `or any(p_zero == 1.0)` is always true.
- [ ] **E3.** Regression tests for B1, B2, B3, B4 and `_Spots.cut` reaching the `stuck` branch.
- [ ] **E4.** `tests/test_email_html.py:124` `assert "Title" not in html` breaks on any name containing "Title".
- [ ] **E5.** `tests/test_season.py:616` accepts any `accept_word`; `test_sim.py` has no symmetry check (four
  equal teams should each sit near 25%).
- [ ] **E6.** `tests/test_waivers.py` pins FAAB constants for a feature no league uses; waiver priority has none.
