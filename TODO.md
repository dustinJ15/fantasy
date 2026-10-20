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

(none open)

## Tier C — operations

(none open)

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
- [ ] **D12 (L). The scanner replay.** `docs/plans/backtest.md` "Still to do": price every rival package
  and every claim each replayed week with `model/trades.py` and `model/waivers.py` and score them against the weeks
  that followed; the trade and waiver hit rates need this sample, the outcome log has one executed trade. On the live
  season only: D11 (2026-10-20) found ESPN serves no lineups for a completed season. Needs the
  free-agent pool per past week (probe `kona_player_info` with a past `scoringPeriodId`). Plan in `docs/plans/` first.
- [ ] **D10 (L, after D12). The fitted projection model.** ROADMAP item 1's historical half: train on nflverse
  play-by-play 2016-2025, per-player weekly points ~ f(opportunity share, team implied total, opponent
  schedule-adjusted points allowed, recent usage trend), blended with consensus by out-of-sample error. Its first
  deliverable is the fitted weight that replaces `OPPORTUNITY_WEIGHT` (0.5) and the clip in `model/projections.py`
  (`docs/plans/in-season-projection.md`), and a pass-attempt term so QB stops reading 1.0; the backtest harness
  (`docs/plans/backtest.md`) is how it is scored. Plan in `docs/plans/` first.
- [ ] **D9 (S). The variance sign on a trade's `my_gain`.** `docs/plans/trade-acceptance.md` question 4: a consolidation
  (fewer, bigger starters) gets +10% on `my_gain` when my playoff odds are under 40% and -10% when they are over 70%,
  the research's Skinner result (an underdog buys variance, a favorite buys floor); title odds as the objective only
  once the sim runs 10k for the top three, which the `MUST_TRY_PPW` comment says it cannot today. After B16.

## Tier E — tests that would catch model errors

(none open)
