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

- [ ] **B12 (M). Split `report.todos` before the next fix lands in it.** `report.py` is 961 lines and `todos` is
  124 of them: the roster-spot ledger (`_Spots`), the per-kind row builders (`_injury_items`, `_cover_items`, waiver,
  open-spot, trade), the push selection, the row ordering and the id scheme (`_unique_ids`) all run in one pass over
  one `out` list. Eleven of the 2026-10-08 fixes (B1, B2, B3, B6, B6b, B7, B9, B11 and the E tests) each added a
  special case to that pass, and the next bug there will be an interaction between two of them, which is the kind a
  per-item test does not catch. Split it into three seams with no behaviour change: the ledger (`_Spots`, drop cost,
  caps) as its own module; one builder per row kind that takes the ledger and returns rows; and `todos` reduced to
  ordering, push selection and `_unique_ids` over the builders' output. `trades.scan` (202 lines) has the same shape
  and can follow in a second item. Done when: every existing test in `tests/test_card.py` and
  `tests/test_review_fixes.py` passes unchanged, `ff briefing --demo` renders byte-identical markdown before and
  after, and no function in `report.py` is over 60 lines. This is a refactor, so the playbook's reproduce step is
  the byte-identical demo output, not a failing test.

## Tier C — operations

- [ ] **C5 (S). The email body is assembled by the LLM.** `briefing/SKILL.md:99-103` has the model paste the
  HTML into the Gmail tool and check `wc -c`. `ff email` already exists (`src/ff/mail.py`); give the cloud env
  `GMAIL_USER`/`GMAIL_APP_PASSWORD` and make the skill call it, with the paste as the fallback.

- [ ] **C8 (XS). `ff accuracy` scores up to Sleeper's week, not the league's.** Found while fixing C6 (2026-10-08):
  `cli.py` `accuracy` passes `sleeper.state().get("week", 1)` to `projlog.accuracy` as the current week. The packet no
  longer reads Sleeper's clock anywhere; the harness should take the week from the newest log row (or a `--week`
  flag), so a Monday run does not score the week in progress, or skip the one just finished.

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

(none open)
