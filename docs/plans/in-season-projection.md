# Plan: the in-season rest-of-season projection

Status: implemented 2026-10-20 in one PR (TODO D1): the opportunity read in `model/projections.py` `opportunity_mult`,
wired from `model/usage.py` `signals` through `packet._projs`. The two earlier pieces of the same number are A1
(2026-10-08, the season-to-date level with the fading prior) and D7 (the usage cell on the card).
Written: 2026-10-20 against `main` at 9f3c08a (462 tests passing).
TODO ids: D1; the fitted model that replaces the prior weight is D10 (step 1 done 2026-10-21: `OPPORTUNITY_WEIGHT` is
fitted per position, QB included, and the clip is off inside the data; `docs/plans/fitted-projection.md`).
Still open: D10.

For an agent touching the rest-of-season level (`season_pg`, `per_game`, `opportunity_mult`) or the usage proxy
(`usage.season_summary`). The container had no ESPN cookies and no nflverse cache, so the worked example below is the
A1 fixture (St. Brown on 2026-10-08) with his usage reconstructed from the public box scores; nothing here needed a
live pull, the arithmetic is the test.

## The number, in one line

`mu_ros_active`, the per-game expectation when he plays, is

    level  = w_prior * proj_season / 17  +  (1 - w_prior) * ytd_pg * opportunity_mult
    mu_ros_active = 0.5 * level + 0.5 * mu_neutral        (when he is expected to play this week; `level` alone when not)

with `w_prior = max(0, 1 - games / PRIOR_FADE_GAMES)` (gone after six games), `ytd_pg` ESPN's season total over his
games played, `mu_neutral` the matchup-neutral weekly blend (ESPN + Sleeper, before Vegas and wind), and
`opportunity_mult` the piece D1 adds. `mu_ros` is that times `avail_ros` (the injury horizon, `docs/plans/injured-player-decision.md`).

## What D1 adds: the opportunity read

`model/usage.py` has priced every player's season since 2026-09 (`xfp_lite`: targets at 1.55, carries at 0.62, air
yards at 0.02, league-average PPR values) and rendered a target share or a carries-a-game figure on the card since D7,
but no number moved. `opportunity_mult(pos, usage)` moves one:

    ratio = clip(xfp_pg / ppg, OPPORTUNITY_RATIO_CLIP)      # both nflverse PPR, so the ratio is unitless
    mult  = 1 - w + w * ratio                                # w = OPPORTUNITY_WEIGHT[pos], 0.5 for RB, WR, TE

and `ytd_pg` is multiplied by it before the prior fades in. A receiver who has scored 20% over what his targets are
worth reads 10% under his season average at the 0.5 prior; a back whose carries outrun his points reads up. QB, K and
D/ST read 1.0: the proxy prices no pass attempt and nflverse has no kicks. A sample under `OPPORTUNITY_MIN_GAMES` (2)
reads 1.0. (Since 2026-10-21, D10 step 1, the weight is fitted per position, QB included at a fitted pass-attempt
value, and the clip is (0.3, 2.0): `docs/plans/fitted-projection.md`. The arithmetic below is at the 0.5 prior.)

Why a ratio and not xFP itself: `xfp_lite` and `ppg` are PPR points from nflverse; `ytd_pg` is league scoring from
ESPN. Their ratio needs no scoring table and survives a half-PPR league, at the cost of mis-weighting a reception
against a carry there. The proper expected-points port (ROADMAP item 3, ffopportunity's situation-based values in the
league's scoring) replaces the proxy, not the shape.

Why half: the public expected-points work (ffopportunity, the PFF and Fantasy Points pieces on points over expected)
agrees that over- and under-performance against opportunity regresses hard from one stretch of games to the next while
opportunity itself persists; a half-and-half read is the prior. A fitted weight needs the backtest (D8) or a scored
projlog that logs `opp_mult` next to the forecast; neither exists yet, so the constant is a prior and says so.

Why clipped at 0.7-1.4: a two-game sample, or a nflverse row whose game count disagrees with ESPN's (a game he was
active for and scored nothing), can say 2x. Nothing says 2x.

## Worked example (the A1 fixture)

St. Brown on 2026-10-08: 91.3 points in 4 games (22.8 a game), preseason total 246.2 (14.5 a game over 17), weekly
blend 18.0, 13 weeks left. Usage reconstructed: 24 targets and five touchdowns, `xfp_pg` 18.3 against `ppg` 22.8.

| | before D1 | after D1 |
|---|---|---|
| `opp_mult` | (none) | 0.5 + 0.5 × 18.3 / 22.8 = 0.90 |
| level | 2/6 × 14.5 + 4/6 × 22.8 = 20.0 | 2/6 × 14.5 + 4/6 × 22.8 × 0.90 = 18.5 |
| `mu_ros_active` | 0.5 × 20.0 + 0.5 × 18.0 = 19.0 | 0.5 × 18.5 + 0.5 × 18.0 = 18.3 |
| `espn_pg` (the rival's view) | 0.5 × 20.0 + 0.5 × 18.0 = 19.0 | unchanged: 19.0 |

The rival's app still shows him 19.0; mine says 18.3. That gap, in both directions, is the only private number the
trade scanner has: a sell-high is a player whose `mu_ros_active` sits under his `espn_pg`, a buy-low the reverse.
`tests/test_projections.py::test_a_td_heavy_start_is_regressed_toward_the_targets_and_the_rival_still_sees_espn`
is this table.

## How to read it in the packet and on the card

- `sources.opp_mult` on every player: 1.0 when opportunity had no say (QB, K, D/ST, no nflverse row, under two games).
- `flags` carries `opp:x0.90` when the multiplier moved the level 5% or more; the roster table's flags column prints it.
- `sources.espn_pg` never sees it: that is the number his manager's app shows, and `acceptance.py` prices offers
  against it.
- `shared.usage_error` in the packet means nflverse was unreachable: every `opp_mult` is 1.0 that morning and the
  card is A1's card. Harmless, like the blank usage cells.

## Questions, as decided

1. **Does opportunity move this week's `mu`?** No. This week's number is the matchup's (ESPN, Sleeper, Vegas, wind);
   the season-to-date read is a level, and the weekly sources already fold a player's usage into their stat lines.
2. **Does it move `espn_pg`?** No, by construction: `espn_pg` exists to say what a rival sees.
3. **QB?** No, until the proxy prices a pass attempt. A QB's TD rate regresses too, but `xfp_lite` has no term for
   him and a 1.0 is honest.
4. **Fade the weight with games like the prior?** No; the clip does that job at small samples, and the half weight is
   the number a fit would replace. One constant is easier to fit than a schedule. (Measured 2026-10-21, D10 step 1:
   the fitted weight does fall with games played, 0.7-0.8 at two or three games to 0.35-0.5 past ten, and a schedule
   buys 0.01-0.02 of out-of-sample rmse; one constant stays.)

## Deviations

None from the item: season-to-date points per game, the target and carry opportunity, and the weekly blend, with the
preseason total fading by game six, are all in `mu_ros_active` now. The fitted historical model ROADMAP item 1
describes (2016-2025 play-by-play, opponent adjustment, usage trend) is a different size of work and is D10.
