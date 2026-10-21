# Plan: the backtest harness

Status: harness built 2026-10-20 in one PR (TODO D8): `src/ff/backtest.py`, `ff replay-pull`, `ff backtest`; first real
run 2026-10-20 (D11) on 2026 weeks 1-6, the tables in `docs/accuracy.md`; 2025 cannot be replayed (ESPN keeps a completed
season's scores, not its lineups: "What the first run found"). The numbers in the synthetic-check section are synthetic.
Written: 2026-10-20 against `main` at 5d705c1; D11 findings added the same day.
TODO ids: D8 (the harness); D11 (the live replay, the first real numbers); D12 (the scanner replay); D13 (the wire body with
no preseason total, the scanner replay's first finding; done 2026-10-21, `docs/accuracy.md` "The claim ranking").
Still open: none.

For an agent running or extending the backtest, or reading its tables before changing a constant in `model/lineup.py`
or `model/projections.py`. ROADMAP item 8 in one line: replay a season with the same code and measure, so a model
change is a number, not a vibe.

## The question, split in two

The card makes two kinds of claim a season can grade. "This lineup wins 71% of the time" is a probability; over a
season of matchups the 70% bin should win about 70%, and if it wins 58% the sigma under every P(win) is too small.
"Give X for Y, +2.1 a week" is a forecast of a points difference; the weeks after the trade say what it was.

Both need the same thing the live pipeline throws away every Tuesday: every roster in the league as it stood before
kickoff, the projection each player carried then, and what he scored. ESPN keeps exactly that in the box score of
every past week (`projected_points` per scoring period is the number it showed before that week's games, `points`
the final, `lineupSlotId` the seat the manager chose), for every season since 2019, in the league's own scoring.

## The replay file

`ff replay-pull --season 2025` writes `data/replay/2025-<league>.json` per league in `leagues.toml` (`backtest.pull_replay`,
read-only, the cookies as for any ESPN read; `espn.connect(ref, season)` opens the past season). One week is one
scoring period that is a whole matchup period: every week of the regular season, and a playoff round that is one
week. A two-week final is skipped (`skipped_weeks`): ESPN's per-period box score carries the period's roster but the
matchup's running total, and nothing in it says which half of the points is which. A week nobody has played yet is
left out, so `--season 2026` replays the current season up to last week. Each week records `first_kickoff` (the
earliest game date among its players) so a trade's close date can be placed on it.

Each matchup: `home`, `away` (team ids), both recorded scores, `playoff`, and both rosters, one row per entry:
`espn_id`, `name`, `pos`, `team`, `eligible` (starter slots only), `slot` (as set, `BE`/`IR` for the bench), `proj`,
`actual`, `bye`. `version` is `REPLAY_VERSION`; `load_replay` refuses an older file.

Version 2 (D12 step 2, 2026-10-20) adds `players`, the universe the scanner replay builds its wire and its
rest-of-season prior from: every player in ESPN's ownership-sorted list (`espn.player_universe`, one
`kona_player_info` pull at the current period, `limit` 1500, the stats filter naming periods 0-18), keyed by `espn_id`
(an int after `load_replay`): `name`, `pos`, `team`, `eligible`, `proj_season` (the static preseason total),
`bye_weeks`, and `weeks` (`{period: {"proj", "actual"}}` for every period the payload carries). `universe_size` is the
pull's length and `universe_missing` the rostered players it does not hold (beyond the list, or with no `stats` block;
such a player is left out and priced from his box-score rows alone). `docs/plans/scanner-replay.md` says what each
field feeds. A version-1 file is refused; `ff replay-pull` again is the fix (the box-score half is unchanged).

A completed season is not in the archive at all: every week of 2025 came back with scores and no roster on either side
(`pull_replay` says so, `NO_LINEUPS`, instead of espn-api's KeyError). Only the current season replays.

What the archive lost, so the replay is read for what it scores and not more:

| the live model has | the replay has | so the replay scores |
|---|---|---|
| ESPN + Sleeper blend, FantasyPros fallback, the Vegas and wind multipliers | ESPN's number alone | the P(win) arithmetic and the sigma prior on ESPN's number, not the blend (the projlog and `ff accuracy` score the blend on the live season) |
| the week's designation (`P_ZERO`, `QUESTIONABLE_BY_WEEKDAY`), Claude's `p_zero` | the designation as of today, which is not the week's; the replay keeps none | nothing about sit risk: everyone sits at the floor, and ESPN's zero on a game week reads as a certain zero (`row_proj`), since ESPN projects zero for a player it knew was out |
| the opponent's lineup as set from Saturday, projected before | the opponent's set lineup | what the live packet uses from Saturday on (`LINEUP_SET_DAYS`); the Tuesday number is not replayed |
| `hold` (`MIN_SWAP_GAIN`) on this week's card | the exact search | the objective, not the churn rule |

## Scorer one: `lineup_calibration`

`ff backtest` (every file under `data/replay/`, or `--replay` paths; `--json` for the dict). Per replay:

- **Calibration.** One row per matchup: the model's P(win) for the home side's set lineup against the away side's
  (`lineup.as_set` on both, `win_prob`), against who won (a tie is 0.5). The away side is the same row mirrored and is
  not counted twice. `brier` (0.25 is a coin flip), `log_loss`, `ece` (the n-weighted gap between what each bin
  predicted and what it won) and the ten `bins` with n. A bin that promises 0.8 and wins 0.6 is the sigma reading
  too small; one that promises 0.8 and wins 0.9 is too wide. The prior under every number is `BASE_SIGMA` and
  `CV_FLOOR`, so this table and `ff accuracy --fit` are two views of the same question; the fit sees each player,
  this sees the sum.
- **Optimizer.** One row per team-week: the set lineup, the highest-points lineup and the P(win) lineup against the
  opponent's set lineup, each scored with the players' actuals against the opponent's recorded score. `pts` and
  `win_rate` for the three; `ev_over_set` is what the manager left on the bench by the projections' own ranking (the
  cheapest edge there is: in the synthetic check a manager who benches his best RB every week leaves 5.3 a week and
  9 points of win rate); `differs` is the team-weeks where the P(win) lineup was not the highest-points lineup, the
  only weeks the objective can earn or lose anything, with both lineups' win rates there, the P(win) the model said it
  was buying (`gain_promised`, the mean `win_gain`) and what it bought (`gain_realized`). Under `DIFFERS_MIN_N`
  (20) of those weeks the row says it is not a verdict. This is where `MIN_WIN_GAIN` (1.5pp) gets its number: if
  `gain_realized` tracks `gain_promised`, the floor can come down; if it does not, the floor is doing its job.
- `score_mismatch` counts a side whose starters' actuals do not sum to ESPN's score within `SCORE_TOL`: a roster
  entry the box score did not carry. It is counted, never patched.

## Scorer two: `trade_hits`

`ff backtest --trades`: every offer of mine ESPN executed (`status: accepted` in `data/projlog/offer_outcomes.json`,
the projlog branch restored first) against its league's replay. `week_after` places the `closed` date on the first
replayed week whose kickoff is after it; from there to the last replayed week, each week's points of the players I got
minus the players I gave, averaged into `realized_ppw`. A week any of them was on nobody's roster is `missing`, not
a zero. `predicted_ppw` is the scan's `my_delta_ppw` for the same package the morning the offer was seen
(`rulings.predicted_ppw`, written into the outcome from this PR on; earlier entries have none), and `hit` is the two
agreeing in sign. The replay must be the same season as the trade (`--season 2026` for this season's offers).

As of 2026-10-20 the outcome log holds one executed offer (L1, 2026-10-14, Hubbard for Rodriguez, Tuten and Coker)
and no prediction on it, so the first row will show a realized number only. The hit rate is a number worth quoting
at ten or so executed trades, which is seasons away at this rate; the scanner replay (D12) is where a sample comes
from before then.

## The synthetic check (what `tests/test_backtest.py` holds the harness to)

A 12-team, 60-week replay whose actuals are drawn from the model's own mixture (`p_zero` 0.02, the house sigma):
360 matchups, Brier 0.20, ECE 0.07 (sampling noise at 36 a bin), the bins at 0.7 and above promising 0.81 and
winning 0.83. The same replay with actuals three times as wide: Brier 0.26, ECE 0.16, the same bins promising 0.81
and winning 0.59. That is the signature of a sigma too small, and what the first real table is read against. Managers
who set the highest-points lineup leave 0.0 a week; one who benches his best RB leaves 5.3 and 0.09 of win rate.

## Leakage rules (the harness keeps them; a change to it must too)

- A lineup is chosen on `proj` and scored on `actual`; no actual is read before a choice is made.
- The opponent's distribution is his set lineup's projection, never his score.
- `row_proj` goes through `projections.blend` with ESPN as the only source, so the sigma and the floor are the live
  code's, not a copy; a change to the prior changes the backtest the same morning.
- The replay is never written by the briefing run and never committed (`data/replay/` is ignored); it is pulled by
  hand, once per season per league, and re-pulled when `REPLAY_VERSION` moves.

## What the first run found (D11, 2026-10-20)

The tables and the two rulings (the sigma prior: no direction, stays; `MIN_WIN_GAIN`: stays, `differs` is 0, 15 and 0)
are in `docs/accuracy.md`. The three things this plan could not know:

- `box_scores` on a past season returns no week: 2025 came back with both scores and no roster on either side under
  `mMatchupScore`, `mScoreboard`, `mBoxscore`, `mMatchup` and the `leagueHistory` endpoint, and `mRoster` with a past
  `scoringPeriodId` is the final roster (same players, same slots in periods 1, 8 and 17) with that period's stats.
  espn-api's "most recent season" is literal. The replay is the live season, re-pulled when the tables are refreshed;
  a season's sample ends when the season does, about 250 matchups across the three leagues.
- The archived `projected_points` is the number as of kickoff: identical to the projlog's last pre-kickoff `espn_pts`
  for 32 of 42 week-6 players, the rest revised before kickoff (up to 2.4 points), and a late scratch zeroed (Judkins,
  13.53 in the Sunday log). That zero is the one bit of hindsight in the replay (`row_proj` reads it as a certain
  zero): 19 of 322 zero-projection game-week rows were seated by their managers, 3 scored.
- `score_mismatch` fired 0 times in 192 team-weeks.

## Still to do

- **D12**, the scanner replay (on the live season: a completed season has no lineups, above): planned 2026-10-20 in
  `docs/plans/scanner-replay.md` (the player universe as the pool, the chart off, `scan_hits` and `claim_hits`, five steps);
  done 2026-10-21: the probe of ESPN's past-period player list (`scripts/probe_replay_pool.py`), the universe pull (replay
  version 2, above), the two scorers (`ff backtest --scan`, `ff backtest --claims`) and the first real tables
  (`docs/accuracy.md`, "The scanner replay"). What they found is D13 (a wire body with no preseason total is priced
  from his last game or two) and the three constant re-reads D14-D16. D17 (2026-10-21) added the third scorer,
  `prior_hits` (`ff backtest --prior`): every body's week-w price against his points a game after, rostered and wire
  apart, under the prior `season_pg` fades and its alternatives; the prior stays (`docs/accuracy.md`, "The rest-of-season
  prior"), re-read at the end of the regular season (D18).
