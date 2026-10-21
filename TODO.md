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
- [ ] **D14 (XS, end of the regular season). Re-read `CLAIM_WORTHY_PPW` (1.0)** on the full-season claim replay
  (`ff replay-pull --season 2026`, `ff backtest --claims`; the D13 floor is in since 2026-10-21): the ruling of 2026-10-21
  is stays, on clean claim-worthy rows of n 10, 30 and 7 realizing +4.4, +3.6 and +1.3 against a promise of +1.5; the bar
  moves only if the 1-2 bin's clean rows realize under a point in all three leagues over the season. Read it without the
  claimed bodies ESPN zeroed on the pull day (`total zeroed on the pull day`, D20): they are a replay-pull artifact, priced
  on the floor where the live card had their total.
- [ ] **D18 (XS, end of the regular season). Re-read the rest-of-season prior** on the full-season replay (`ff backtest
  --prior`, `docs/accuracy.md` "The rest-of-season prior"): the ruling of 2026-10-21 is stays, the larger of the total and
  this week's number fixing the in-range wire body (-1.6 to -0.2) at +1.2 on every rostered body; it takes over if it
  lowers the rostered body's error too, or the in-range wire bias passes two points with the rostered one within half a
  point of zero.
- [ ] **D21 (XS, end of the regular season). Re-read the blend question** on the full-season replay and the projlog
  (`ff backtest --fit`, `docs/plans/fitted-projection.md` step 5): the ruling of 2026-10-21 is the fitted weekly number
  stays a rest-of-season read, not a third source of `blend` (mixed with ESPN at ~0.47 it beat ESPN alone held out by
  0.2-0.3 at RB and WR, tied TE, lost QB, while reading 1.2-4 points low; the projlog's league-keyed rows were 10-21 a
  position, under `projlog.FIT_MIN_N`). It enters `blend` only once its bias is taken out on the training weeks and the
  three-source mix (ESPN, Sleeper, fitted) beats the live blend held out on the projlog's table at `FIT_MIN_N`. Read
  `OPPONENT_K` RB on the same run: the opponent on top of ESPN's number cost RB 0.07-0.10 in every sample.
- [ ] **D15 (XS, end of the regular season). Re-read `MUST_TRY_PPW` (2.0)** on the full-season scan replay
  (`ff backtest --scan`, minutes per league): the ruling of 2026-10-21 is stays, the 2-4 bin realizing +2.4 to +3.6 in
  all three leagues on five weeks; the bar moves down only if the 1-2 bin realizes its promise at a hit rate over 0.55 in
  all three, up only if the 2-4 bin falls under +2.
- [ ] **D16 (XS, end of the regular season). Re-read `SEND_MIN_PPW` (1.0)** on the same scan replay: the 0-1 bin is noise
  in every league (hit 0.47-0.57, realized -0.3 to +2.0) and the 1-2 bin realized +0.78 in L2 at a coin flip; 1.5 is the
  case if the 1-2 bin realizes under a point in two leagues over the season, and a ruling on it is one line here, not a
  constant change without the table.
- [ ] **D9 (S). The variance sign on a trade's `my_gain`.** `docs/plans/trade-acceptance.md` question 4: a consolidation
  (fewer, bigger starters) gets +10% on `my_gain` when my playoff odds are under 40% and -10% when they are over 70%,
  the research's Skinner result (an underdog buys variance, a favorite buys floor); title odds as the objective only
  once the sim runs 10k for the top three, which the `MUST_TRY_PPW` comment says it cannot today. After B16.

## Tier E — tests that would catch model errors

(none open)
