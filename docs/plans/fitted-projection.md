# Plan: the fitted projection model (TODO D10)

Status: planned 2026-10-21; step 1 done the same day (the opportunity weight and clip, the pass-attempt term: `src/ff/opfit.py`,
`ff fit-opportunity`, the constants adopted in `model/projections.py` and `model/usage.py`). Steps 2-5 are in TODO.md under D10.
Written: 2026-10-21 against `main` at 3db45b8 (a session with the network and no cookies: nflverse reachable, ESPN not).
TODO ids: D10 (steps 2-5); D2 is the variance fit the same way, on the projlog; D13 the floor prior for a wire body.
Still open: D10.

For an agent fitting a projection constant to past seasons, or taking a D10 step. ROADMAP item 1's historical half in one
line: the in-season model (`docs/plans/in-season-projection.md`) reads a player's rest of season from his season so far,
moved toward what his opportunity was worth, and every number in that arithmetic was a prior; nflverse has ten seasons of
weekly stats, so each term can be fitted in the live arithmetic's own shape and scored out of sample before it is adopted.

## The rule for every step

- **The shape is the live code's.** The fit does not build a second model to be ported later; it fits the constant the
  live function reads (`opportunity_mult`'s weight, `VEGAS_K`, the opponent cap), with the training row built the way
  the live read builds its inputs (the same game count as `usage.season_summary`, the same xFP-lite expression,
  `usage.xfp_lite_expr`). A fitted number drops in with no change to the function.
- **Out of sample or not at all.** Leave-one-season-out over 2016-2025: the constant fitted on nine seasons, scored on the
  tenth, pooled over the ten held-out seasons. The verdict is `fit` only when that beats the constant as it stands; the
  fitter prints `keep prior` otherwise and nothing is copied. After adoption a re-run reads the fit against itself and
  says keep, until a new season moves it.
- **Code owns the numbers.** `ff fit-opportunity` prints; the constant is copied by hand with the sample size and the
  date in its comment and the old value kept beside it (D2's rule). A judgment about the shape (a schedule, a per-position
  clip) is a question in this plan, decided on the printed table, never a constant tuned by eye.
- **The replay and the projlog score what the fit cannot.** The training data is nflverse PPR; the card is ESPN's league
  scoring with the preseason prior and the weekly blend folded in. Whether a fitted term still earns its place inside
  that arithmetic is the backtest's question (`docs/plans/backtest.md`, the 2026 replay) and the projlog's (`ff accuracy`),
  on the live season, at the sample D2 waits for.

## Step 1: the opportunity weight, the clip and the pass attempt (done 2026-10-21)

### The training row

`opfit.training_frame` over `usage.weekly_usage` for 2016-2025 (REG only, QB, RB, WR, TE): one row per player-game of a
season, at the week that game was played, with his season so far on one side and the rest of it on the other:

| column | is | from |
|---|---|---|
| `games`, `ppg`, `xfp_pg` | games, PPR points a game and xFP-lite a game over his games before that week | the inputs `opportunity_mult` reads; a game is a week with a stat row, as `season_summary` counts it, so a bye is no game |
| `future_ppg` | PPR points a game over his games from that week on | the truth: the rest-of-season per-game level the live number is a forecast of |

A row needs `OPPORTUNITY_MIN_GAMES` (2) games before (the live read waits for that), `FIT_MIN_GAMES_AFTER` (3) after (a
target over fewer games is one game of noise) and `FIT_MIN_PPG` (5.0 PPR a game) so far (the card prices rostered bodies
and the top of the wire, not the tail). 23,096 rows: QB 3,481, RB 6,128, WR 9,883, TE 3,604.

### The fit

The model is `opportunity_mult`'s, `future_ppg ≈ ppg * (1 - w + w * clip(xfp_pg / ppg))`, which is `ppg + w * x` with
`x = ppg * (ratio - 1)`, so `w` has a closed form per clip (`fit_w`, least squares on `future_ppg - ppg`, held to [0, 1]:
a share) and the clip is a grid (`CLIP_LO_GRID` × `CLIP_HI_GRID`). One clip for every position (the constant is one
tuple), chosen by the pooled leave-one-season-out error over the four (`choose_clip`); then the weight per position at
that clip (`fit_position`), with the per-fold weights and the weight by games played for the reader. The pass attempt
first (`fit_attempt_value`): QB weeks with an attempt, PPR points less `XFP_PER_CARRY` a carry, least squares through the
origin on attempts; the training frame then prices attempts at that value, so the pair is adopted together.

### What it printed (2016-2025, 2026-10-21)

```
XFP_PER_ATTEMPT now 0.0; fit 0.415 on 5992 QB weeks (0.393-0.448 by season; attempts and carries both free: 0.381 / 0.964)
OPPORTUNITY_RATIO_CLIP now (0.7, 1.4) (pooled rmse 4.1781); fit (0.3, 2.0) (pooled rmse 4.1565); no clip at all 4.1565
```

| pos | n | weight now | fit | rmse w=0 | rmse now | rmse fit | folds | weight by games played (2-3, 4-6, 7-10, 11-17) |
|---|---|---|---|---|---|---|---|---|
| QB | 3481 | 0 (reads 1.0) | 0.568 | 4.889 | 4.889 | 4.385 | 0.545-0.597 | 0.69, 0.59, 0.49, 0.36 |
| RB | 6128 | 0.5 | 0.644 | 4.747 | 4.480 | 4.436 | 0.613-0.665 | 0.79, 0.64, 0.51, 0.46 |
| WR | 9883 | 0.5 | 0.578 | 4.395 | 4.159 | 4.142 | 0.543-0.604 | 0.73, 0.61, 0.37, 0.36 |
| TE | 3604 | 0.5 | 0.674 | 3.702 | 3.461 | 3.410 | 0.651-0.711 | 0.78, 0.69, 0.54, 0.53 |

The per-opportunity refit, for information: RB 1.39 a target, 0.66 a carry, 0.025 an air yard; WR 1.53, 0.96, 0.017;
TE 1.56, 1.23, 0.023 (the hand-set 1.55 / 0.62 / 0.02 stay; a per-position value is ROADMAP item 3).

Adopted: `OPPORTUNITY_WEIGHT = {"QB": 0.57, "RB": 0.64, "WR": 0.58, "TE": 0.67}`, `OPPORTUNITY_RATIO_CLIP = (0.3, 2.0)`,
`XFP_PER_ATTEMPT = 0.415`. The tests that pin the D1 arithmetic (`tests/test_projections.py`, the A1 fixture) now derive
from the constants; the plan's worked example in `docs/plans/in-season-projection.md` is left at the 0.5 prior and says so.

### What the fit found

- **The opportunity read is worth having, and more than half.** Against no read at all (w = 0), the 0.5 prior took
  6-7% off the rest-of-season error at RB, WR and TE; the fitted weights take another 0.5-1.5%. Every fold's weight sits
  within 0.03 of the whole-sample one in every position: it is one number per position.
- **QB reads his attempts.** A pass attempt is worth 0.415 PPR points at the league average (0.39-0.45 in every season
  of the ten), and a QB's rest of season moves 0.57 of the way toward what his attempts and carries were worth: 10% off
  the error against reading 1.0. With carries free the fit says a QB carry is worth 0.96, not the back's 0.62 (a
  running QB's carries are goal-line heavy); the carry stays at `XFP_PER_CARRY` and the attempt value absorbs it, since
  the proxy is one formula and the ratio is what moves the level.
- **The clip is off inside the data.** The ratios the data holds run 0.41-1.83 between the 1st and 99th percentiles,
  and no clip at all scores the same pooled error as the grid's best; the prior's lower bound (0.7) held up 5% of QB,
  RB and WR rows and 14% of TE rows (a touchdown-heavy start that then regressed) and cost 0.02 of error. The clip stays
  as a guard on a bad row the training data cannot show (a nflverse game count that disagrees with ESPN's, which puts a
  phantom zero game in `ppg`), at bounds outside the ratios the data holds.
- **The weight falls with games played.** 0.7-0.8 at two or three games, 0.35-0.5 past ten, in every position: a
  young season's points are mostly noise around his usage, a long one's are mostly his. A linear or `1/games` schedule
  fitted leave-one-season-out buys 0.01-0.02 of rmse over the flat weight, pooled, and in the 11-17 bucket no form
  (flat, schedule or the 0.5 prior) is separable from the others by more than 0.02. One constant stays (question 1).
- **The late-season read is where nothing helps.** Past ten games every weight scores within noise of w = 0.4; the
  gain of the whole read is in weeks three to ten, which is also where the live arithmetic still carries the preseason
  prior (gone after six games) and where the trade scanner's buy-low and sell-high rows come from.

### What the fit could not see

- **The live context.** On the card the opportunity-moved `ytd_pg` is blended with the preseason prior (`season_pg`,
  gone after six games) and shrunk halfway toward the weekly blend (`per_game`). The training row has neither: no
  preseason total exists for 2016-2025 in ESPN's scoring, and no weekly consensus. The weight is the opportunity piece
  in isolation; whether the whole number is better on the card is the 2026 replay's question (step 5) and the projlog's.
- **ESPN's scoring.** The ratio is unitless by construction (both sides nflverse PPR), so the weight carries over; the
  error figures are PPR points, not the league's.
- **A nflverse game count against ESPN's.** The one place the clip matters, and the training frame uses nflverse on both
  sides, so it never fires there.
- **Survivorship.** A row needs three games after it, so a player hurt for the year at week w has no row at week w. The
  weight is fitted on the players who kept playing, which is the population the read prices (a player out for the
  season is priced by `weeks_out`, not by his usage).
- **The clip grid is chosen on the same folds it is scored on**: 49 grid points, and the pooled error moves 0.02 across
  the whole grid, so the choice is not a tuned number but a reading that the clip does nothing; the bounds adopted are
  the grid's edge, which is why the plan says "off inside the data" and not "fitted to 0.3 and 2.0".

## Steps 2-5 (one PR each, in order; the done-when of each)

2. **The opponent factor** (ROADMAP item 5's open piece: the schedule-adjusted points-allowed factor, capped at ±10%).
   From the same weekly stats: PPR points allowed to each position by each defense over the season so far, divided by
   what the offenses it faced score elsewhere (one pass of adjustment), as a multiplier on *this week's* number.
   Training row: a player at a week, `ppg` so far and his opponent's factor so far, truth his points that week; model
   `points ≈ ppg * (1 + k * (factor - 1))`, closed form in `k`, capped, leave-one-season-out, per position. Done when
   `fit_opponent` prints `k` per position against no factor and the cap, and the factor is wired into `blend` as a
   this-week multiplier beside `VEGAS_K` with its own `sources` field and flag. What it must not read: the week's own
   box score in the factor (through week w-1 only), and the factor is applied to the matchup-neutral number, never to
   ESPN's (whose analysts already look at the matchup; whether it double counts is step 5's question).
3. **The implied-total term.** `VEGAS_K` per position was set by hand (2026-09). nflverse `schedules` carries
   `spread_line` and `total_line` for every game since 1999, so the implied team total of every training game is
   `total / 2 ± spread / 2`. Same row as step 2 with the implied total in place of the factor, model
   `points ≈ ppg * (1 + k * (implied / LEAGUE_AVG_IMPLIED - 1))`, closed form in `k`. Done when the fitter prints
   `VEGAS_K` per position next to the constants with the verdict; adopted the same way. The live source
   (`sources/vegas.py`) is unchanged.
4. **The recent-usage trend.** The last three games' opportunity share against the season's (`tgt_share`, carries a
   game) as a second term on the rest-of-season level: `level ≈ ppg * (1 - w + w * ratio) * (1 + t * (recent / season - 1))`.
   Training row as step 1 with the trend added; `t` fitted at the adopted `w`, leave-one-season-out. Done when the
   fitter prints `t` per position with the verdict and, if `fit`, `opportunity_mult` reads it from `usage.signals`.
   The prior is zero (the public finding is that a share change persists only when a role changed, which the number
   cannot tell from a blowout).
5. **The blend with consensus by out-of-sample error.** The point of the item: the fitted weekly number (steps 2-3 on
   `ppg` so far) against ESPN's weekly number for the same player-week, on the 2026 replay (`players[].weeks[].proj`
   and `actual`, three leagues, every rostered and universe player) and the projlog (`espn_pts`, `sleeper_pts`, the
   blend, the actual). The mixing weight is the inverse-error one over the scored weeks, per position, refused under
   `projlog.FIT_MIN_N` as D2. Done when `ff backtest --fit` (or `ff accuracy --fit-blend`) prints the fitted number's
   MAE beside each source's and the mixing weight, and the plan says whether the fitted model enters `blend` as a third
   source at that weight or stays a rest-of-season read only. Needs the replay files and the cookies.

## Leakage rules (the fitter keeps them; a step must too)

- A training row's inputs are the games before its week; the truth is the games from that week on. Nothing on the
  right-hand side is read before the row's week (`training_frame` builds both from one sorted pass with the row's own
  game subtracted from the prefix).
- Folds are whole seasons: a player's rows of one season are never split between training and test.
- The verdict compares the fitted constant out of sample against the constant as it stands scored in place (a constant
  has no fold), so it is conservative: a fit that only ties reads `keep prior`.
- The fitter writes nothing: no constant changes without a hand copy and the comment that names the sample and the date.

## Questions, as decided

1. **A weight schedule by games played instead of one constant?** No. The fit says the weight falls with the sample
   (the table above), but a schedule buys 0.01-0.02 of rmse, under what the clip grid moves, and the live arithmetic
   already fades the preseason prior over the same games. Revisit only if step 5 scores the early-season read as the
   place the card is wrong.
2. **A clip per position?** No. Per-position picks on the grid differed (WR and TE wanted the upper bound at 1.2, QB
   and RB at 3.0) by less than 0.03 of rmse, which is the grid's noise; one tuple, chosen pooled.
3. **Refit the per-target, per-carry and per-air-yard values?** No. The least-squares values (RB 1.39 / 0.66 / 0.025,
   WR 1.53 / 0.96 / 0.017, TE 1.56 / 1.23 / 0.023) are printed for information; a per-position value is the proper xFP
   of ROADMAP item 3, and the ratio's weight was fitted at the hand-set values, so changing them means refitting it.
4. **A QB carry at the back's value?** Yes, held at `XFP_PER_CARRY`; the attempt value is fitted with carries held
   there, so a running QB's rushing is under-priced by about 0.34 a carry and his ratio reads a little low. The joint
   fit is printed; a per-position carry value is question 3's work.
5. **Train on play-by-play, as the item said?** Not for step 1: the weekly stats carry the opportunities the proxy
   prices (targets, carries, air yards, attempts) and the points, which is all the live read uses. Play-by-play is
   needed when a term reads a situation (red-zone share, down and distance), which is ROADMAP item 3, not this plan.
