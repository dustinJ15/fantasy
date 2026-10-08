# Roadmap — making the analysis genuinely sharp

The ordered, actionable backlog is `TODO.md` (one PR per item, each with its evidence and a done-when). This file is the direction.

Honest status of the model and what would move the needle, in priority order. Current standing in all three leagues: not yet
dominant, which the model attributes to variance.

## Where the edge is today
- **Trade scanner**: evaluates every 1-for-1 and 2-for-1 against every rival by both sides' lineup delta and re-simulated title odds. Nobody in a 12-team league does this by hand. This is the biggest structural advantage.
- **Win-probability lineups**: maximizes P(beat this week's opponent), not expected points. Favorites get floor, underdogs get ceiling, automatically.
- **Injury-aware distributions + Claude research**: designation → probability of a zero, adjusted by morning news.
- **Monte Carlo season sim**: consistent title-odds yardstick for every decision.
- **Hurt players get a verdict**: `weeks_out` (designation default, Claude's research overrides) nets games missed out of every
  rest-of-season number, and `model/injuries.py` says IR-stash, trade, drop or hold with the weeks weighted by playoff odds.
  Design and the open calls: `docs/plans/injured-player-decision.md`.

## Projection sourcing (decided 2026-09-10, research-backed)
- Equal-weight mean of stat-based sources: ESPN (Mike Clay) + Sleeper (Rotowire). FantasyPros rank-to-points is a fallback
  only (it is a rank lookup, not a stat projection). Vegas implied team total is a small multiplicative adjuster
  (`VEGAS_K` in projections.py), never averaged in. Rationale: Fantasy Football Analytics' 12-season study shows equal-weight
  averaging beats accuracy-weighting because source accuracy doesn't persist year to year.
- `ff log-projections` records every source daily to `data/projlog/` (committed by the routine); `ff accuracy` reports MAE
  and bias by source × position once weeks complete. Re-weight or drop a source only if it trails the blend by >5% for 6+ weeks.
  Scoring (fixed 2026-10-08, TODO A2): each player's last pre-kickoff row against ESPN's actual in that league's scoring,
  one row per league; before that the harness scored Monday's banked points against themselves (blend MAE 0.11 at TE).
  Weeks 1-4 of 2026, scored honestly:

  | pos | source | n | MAE | bias |
  |---|---|---|---|---|
  | D/ST | espn_pts | 10 | 4.46 | -0.98 |
  | D/ST | blend | 10 | 4.78 | -0.37 |
  | D/ST | fp_pts | 10 | 5.21 | -0.21 |
  | D/ST | sleeper_pts | 10 | 5.21 | 0.23 |
  | K | sleeper_pts | 10 | 4.5 | 0.17 |
  | K | fp_pts | 10 | 4.56 | 0.64 |
  | K | espn_pts | 10 | 4.77 | 1.81 |
  | K | blend | 10 | 4.83 | 1.07 |
  | QB | sleeper_pts | 18 | 8.22 | 4.29 |
  | QB | espn_pts | 18 | 8.43 | 3.92 |
  | QB | blend | 18 | 8.48 | 4.21 |
  | QB | fp_pts | 18 | 8.68 | 4.3 |
  | RB | blend | 49 | 5.79 | -0.77 |
  | RB | fp_pts | 49 | 5.8 | -0.78 |
  | RB | sleeper_pts | 49 | 5.85 | -0.82 |
  | RB | espn_pts | 49 | 5.95 | -0.45 |
  | TE | fp_pts | 21 | 6.45 | -3.81 |
  | TE | espn_pts | 21 | 6.87 | -4.28 |
  | TE | sleeper_pts | 21 | 6.93 | -3.9 |
  | TE | blend | 21 | 6.97 | -4.05 |
  | WR | sleeper_pts | 46 | 5.9 | -0.41 |
  | WR | espn_pts | 46 | 6.01 | -0.74 |
  | WR | fp_pts | 46 | 6.01 | -0.47 |
  | WR | blend | 46 | 6.16 | -0.35 |

  Read: no source trails the blend by 5% anywhere; the sources sit within a few tenths of each other and of the blend,
  which is noise at n of 18-49 (one week is 10-15 rows per position). QBs were over-projected (bias +4) and TEs
  under-projected (-4) in these four weeks, a calibration question for A5/D2, not a sourcing one. The pre-fix logs lose
  Monday-night players and anyone the stale clock locked at zero (see `projlog.py`); logs from 2026-10-08 on carry
  `actual_prev` and score everyone.
- Considered and skipped: CBS/Yahoo scraping (ToS), NFL.com (game discontinued for 2026), numberFire (dead).
  Optional paid upgrade: FantasyPros official API ($8.99/mo) for the true stat consensus; Subvertadown for K only.

## Where it's honestly weak
- **Projections are still borrowed.** Same information everyone has; the edge is in how it's used, not the numbers.
- **Variance is a prior, not fitted.** Per-position sigma is a guess scaled by consensus disagreement.
- **Usage / expected-points signals are thin** until ~week 4 (one-game samples now). No 2026 snap counts in nflverse yet.
- **K / DST** use consensus, which is weak there; implied team totals from Vegas are fetched but not yet fed into K/DST projections.
- **Weather** is fetched per game but not applied to projections.

## Improvements, in order of expected value

1. **Fitted projection model (week 4+).** Train on nflverse play-by-play 2016–2025: per-player weekly points ~ f(opportunity share, team implied total, opponent schedule-adjusted points allowed, recent usage trend). Blend with consensus by out-of-sample error. Expected gain: the only place a real, private edge exists.
2. **Calibrated variance.** Fit per-position projection-to-actual error (STDpa) from FantasyPros historical ECR archive (`db_fpecr.parquet` in dynastyprocess/data) vs actual points. Replace `BASE_SIGMA` / `CV_FLOOR` priors. Improves every P(win) and title-odds number.
3. **Expected fantasy points (xFP) properly.** Port ffverse/ffopportunity logic (situation-based expected points per target/carry) instead of the flat 1.55/target proxy in `usage.py`. Sharper buy-low / sell-high flags.
4. **Weather into projections** (Vegas is done). Apply wind >15 mph penalty to passing/K; calibrate `VEGAS_K` from the projection log after ~6 weeks.
5. **Playoff schedule weighting.** Multiply ROS value by a schedule-adjusted points-allowed factor for weeks 15–17 (read from league settings). Cap at ±10%. Best acted on weeks 6–10.
6. **League-mate behavior model.** From ESPN transaction history: who trades, who overreacts to a bad week, who bids on hype. Use to rank trade partners and to time offers (e.g., pitch after their loss).
7. **Waiver-priority strategy** (all three leagues use priority, not FAAB): value of *holding* #1 priority vs using it; only recommend a claim when the target clears a threshold relative to expected future claims.
8. **Backtesting harness.** Replay 2025 with the same code; measure lineup P(win) calibration, trade evaluator hit rate, and waiver recommendations vs. actual outcomes. Without this, model changes are vibes.
9. **Discord delivery + trash talk.** `DISCORD_WEBHOOK` per league; Claude drafts recaps and the trade pitch, Dustin approves before posting.
10. **Speed.** Packet build is now ~6s per league. Monte Carlo could be vectorized further if sims are raised above 5000.

## Guardrails that stay
- Read-only against ESPN. No lineup / waiver / trade writes, no chat posting.
- Code owns state and math; Claude owns judgment over unstructured text and prose. Every number in the briefing comes from `ff`.
