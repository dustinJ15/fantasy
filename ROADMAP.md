# Roadmap — making the analysis genuinely sharp

For Dustin and anyone deciding what to build next. The ordered, actionable backlog is `TODO.md` (one PR per item, each with its
evidence and a done-when); this file is the direction only, and a finished item is marked done in one line with its TODO id.

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
  The measurement to date (weeks 1-4 of 2026, scored 2026-10-08) and how to read it: `docs/accuracy.md`.
- Considered and skipped: CBS/Yahoo scraping (ToS), NFL.com (game discontinued for 2026), numberFire (dead).
  Optional paid upgrade: FantasyPros official API ($8.99/mo) for the true stat consensus; Subvertadown for K only.

## Where it's honestly weak
- **Projections are still borrowed.** Same information everyone has; the edge is in how it's used, not the numbers.
- **Variance is a prior, not fitted.** Per-position sigma is a guess scaled by consensus disagreement.
- **Usage / expected-points signals are thin** until ~week 4 (one-game samples now). No 2026 snap counts in nflverse yet.
- **K / DST** use consensus, which is weak there; implied team totals from Vegas are fetched but not yet fed into K/DST projections.

## Improvements, in order of expected value

1. **Fitted projection model (week 4+).** The in-season half is done 2026-10-20 (TODO D1, with A1 and D7): `model/projections.py` builds the rest-of-season level from season-to-date points per game, moved toward what his targets and carries are worth (`opportunity_mult`, half weight, RB/WR/TE), with the preseason total as a prior that fades by game six and the weekly blend shrunk in; the rival's view (`espn_pg`) stays on ESPN's numbers, which is where the trade scanner's private edge sits. Design: `docs/plans/in-season-projection.md`. The historical half (TODO D10, planned 2026-10-21 in `docs/plans/fitted-projection.md`): each term fitted on nflverse weekly stats 2016–2025 in the live arithmetic's own shape, leave-one-season-out (`opfit.py`, `ff fit-opportunity`). Step 1 done 2026-10-21: the half weight is a fitted one per position (0.57-0.67), QB reads his pass attempts, and the clip is off inside the data. Step 2 done 2026-10-21: each defense's schedule-adjusted points allowed at the position (`model/usage.py` `opponent_factors`, through last week) multiplies this week's number by a fitted `OPPONENT_K` (0.09-0.25) held to ±10%. Steps 3-4 done 2026-10-21: the implied total refit (`VEGAS_K` QB 0.41) and the recent usage trend (`TREND_K`). Step 5 done 2026-10-21 (`ff backtest --fit`): the fitted weekly number mixed with ESPN's beats ESPN alone held out at RB and WR but reads 1-4 points low, and the comparison with the live blend is under the minimum sample, so it stays a rest-of-season read; D21 re-reads it at the season's end.
2. **Calibrated variance.** Fit per-position projection-to-actual error (STDpa) from FantasyPros historical ECR archive (`db_fpecr.parquet` in dynastyprocess/data) vs actual points. Replace `BASE_SIGMA` / `CV_FLOOR` priors. Improves every P(win) and title-odds number.
3. **Expected fantasy points (xFP) properly.** Port ffverse/ffopportunity logic (situation-based expected points per target/carry) instead of the flat 1.55/target proxy in `usage.py`. Sharper buy-low / sell-high flags.
4. **Weather into projections.** Done 2026-10-08 (TODO D5): `model/projections.py` `wind_mult` discounts QB/WR/TE and K when the kickoff forecast (`sources/weather.py`, Open-Meteo at the home stadium) is over `WIND_MPH_START`, linearly to `WIND_PENALTY_AT_CAP` at `WIND_MPH_CAP`; domes and a missing forecast read 1.0. `VEGAS_K` is fitted on 2016-2025 closing lines (TODO D10 step 3, 2026-10-21: QB 0.41, the rest kept); whether it double counts ESPN's number is D10 step 5.
5. **Playoff schedule weighting.** Done 2026-10-08 (TODO D4) as odds weighting: `model/season.py` `week_weight` prices each of the league's playoff weeks (`settings.playoff_weeks`, never a hard-coded 15–17) at my playoff odds × `TITLE_RUN_MULT` (1.5), so a dead team prices a week-16 bye or return at nothing and a lock above a regular week; the hold / drop rule uses the same number and the card prints "playoff weeks 15-17 weighted ×1.4". The schedule-adjusted points-allowed factor (capped at ±10%) is done 2026-10-21 as item 1's step 2 (`OPPONENT_K`, `opponent_mult` in `model/projections.py`); the ±10% cap is kept because the fit says it helps.
6. **League-mate behavior model.** From ESPN transaction history: who trades, who overreacts to a bad week, who bids on hype. Use to rank trade partners and to time offers (e.g., pitch after their loss).
7. **Waiver-priority strategy.** Done 2026-10-08 (TODO D3): `model/waivers.py` `priority_cost` prices holding priority #N against holding last over the wire's claim-worthy upgrades (`RIVAL_CLAIM_P` per team ahead, discounted over the weeks left), and a claim row in a rolling-priority league says "worth it" or "pass" with both numbers; a weekly reset costs nothing and prints nothing.
8. **Backtesting harness.** Built 2026-10-20 (TODO D8): `ff replay-pull` archives a season's ESPN box scores (both lineups as set, the pre-kickoff projection and the actual per player) and `ff backtest` replays it through the same code: a P(win) reliability table and Brier score for the lineups that played, the optimizer's lineup against the one the manager set, and `--trades` scores every executed offer week by week against the delta the scan promised. Design: `docs/plans/backtest.md`. Not yet run on a real season (TODO D11); the scanner and waiver replay, which the trade hit rate needs for a sample, is TODO D12. Without this, model changes are vibes.
9. **Discord delivery + trash talk.** `DISCORD_WEBHOOK` per league; Claude drafts recaps and the trade pitch, Dustin approves before posting.
10. **Speed.** Packet build is now ~6s per league. Monte Carlo could be vectorized further if sims are raised above 5000.

## Guardrails that stay
- Read-only against ESPN. No lineup / waiver / trade writes, no chat posting.
- Code owns state and math; Claude owns judgment over unstructured text and prose. Every number in the briefing comes from `ff`.
