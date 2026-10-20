# Projection accuracy, by source and position

Status: measurement, re-run with `uv run ff accuracy` (the projlog branch restored first: `scripts/projlog_push.sh --restore`)
and `uv run ff backtest` / `ff backtest --trades` (the replays pulled first: `ff replay-pull --season 2026`).
Written: 2026-10-08 against the week 1-4 logs; moved here from ROADMAP.md on 2026-10-20 (Docs-1); the backtest tables added
2026-10-20 (D11).
TODO ids: D2 (adopt the fitted variance once a position has 150 scored forecasts); D12 (the scanner replay).
Still open: D2, D12.

For an agent or Dustin deciding whether a source earns its weight (ROADMAP: re-weight or drop a source only if it trails the
blend by more than 5% for six or more weeks), or whether the P(win) prior and the optimizer's floor hold up against a season
(`docs/plans/backtest.md` says what the replay scores and what it cannot). The rows are what `ff accuracy` and `ff backtest`
printed; the read under each table is the decision.

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

## The backtest: 2026 weeks 1-6, pulled and scored 2026-10-20

`ff replay-pull --season 2026` for the three leagues, then `ff backtest` and `ff backtest --trades` (D11, the first real run of
the D8 harness). 2025 does not exist as a replay: ESPN keeps a completed season's scores and not its lineups (below), so the
sample is the live season up to last week, re-pulled each time the tables are refreshed.

What the first run found out (the three questions `docs/plans/backtest.md` could not answer from the synthetic check):

- **A completed season has no lineups.** Every week of 2025 came back with both scores and no roster on either side, in all
  three leagues, under every view tried (`mMatchupScore`, `mScoreboard`, `mBoxscore`, `mMatchup`, the `leagueHistory` endpoint);
  `mRoster` with a past `scoringPeriodId` returns the final roster, same players and same slots in periods 1, 8 and 17, with
  that period's stats attached. espn-api's "most recent season" docstring is right. `pull_replay` now fails with that sentence
  (`backtest.NO_LINEUPS`) instead of a KeyError. The current season does serve the period's roster: the 2026 week-1 and week-6
  rosters differ on every team (one to nine players moved).
- **The archived `projected_points` is the pre-kickoff number.** Against the projlog's last pre-kickoff `espn_pts` row for
  2026 week 6: 42 players in both, 32 identical to the cent, 35 within half a point. The rest moved between the Sunday-morning
  log and kickoff (Shakir 9.20 to 11.55, Taylor 18.77 to 19.56, three Thursday players by about half a point from the Saturday
  log). One is the caveat: Judkins was 13.53 in the Sunday log and 0.00 in the archive, a late scratch ESPN zeroed at kickoff.
  So the archive is the number as of kickoff, later than the briefing's number, and its zeros carry a little hindsight the
  Saturday lineup did not have: of 322 zero-projection rows on a game week, 3 scored and 19 were seated by their managers.
  Nothing in it is a post-game revision (Hubbard 14.82 projected, 19.1 scored).
- **`score_mismatch` fired 0 times** in 192 team-weeks: every side's starters sum to ESPN's score within `SCORE_TOL`.

### P(win) calibration of the set lineups

`brier` is 0.25 for a coin flip; the bins are the model's P(win) for the home side's set lineup against the away side's, against
who won. n is one row per matchup.

| league | n | Brier | log loss | ECE |
|---|---|---|---|---|
| L1 | 36 | 0.2245 | 0.6382 | 0.152 |
| L2 | 30 | 0.2009 | 0.5778 | 0.064 |
| L3 | 30 | 0.2168 | 0.6234 | 0.109 |

| P(win) bin | L1 n | L1 predicted | L1 won | L2 n | L2 predicted | L2 won | L3 n | L3 predicted | L3 won | pooled n | pooled predicted | pooled won |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.1-0.2 | 1 | 0.12 | 0.00 | 2 | 0.13 | 0.00 | 0 | — | — | 3 | 0.13 | 0.00 |
| 0.2-0.3 | 3 | 0.23 | 0.33 | 1 | 0.28 | 0.00 | 2 | 0.28 | 0.00 | 6 | 0.26 | 0.17 |
| 0.3-0.4 | 6 | 0.37 | 0.17 | 3 | 0.36 | 0.33 | 0 | — | — | 9 | 0.37 | 0.22 |
| 0.4-0.5 | 6 | 0.45 | 0.50 | 8 | 0.45 | 0.38 | 10 | 0.44 | 0.30 | 24 | 0.45 | 0.38 |
| 0.5-0.6 | 13 | 0.54 | 0.69 | 10 | 0.54 | 0.50 | 11 | 0.54 | 0.55 | 34 | 0.54 | 0.59 |
| 0.6-0.7 | 3 | 0.63 | 0.67 | 3 | 0.65 | 0.67 | 6 | 0.67 | 0.83 | 12 | 0.65 | 0.75 |
| 0.7-0.8 | 3 | 0.74 | 0.33 | 1 | 0.77 | 1.00 | 1 | 0.76 | 1.00 | 5 | 0.75 | 0.60 |
| 0.8-0.9 | 1 | 0.80 | 1.00 | 0 | — | — | 0 | — | — | 1 | 0.80 | 1.00 |
| 0.9-1.0 | 0 | — | — | 2 | 0.95 | 1.00 | 0 | — | — | 2 | 0.95 | 1.00 |

The pooled column is the three leagues' bins summed, n-weighted (96 matchups): the 0.7+ bins hold 8 matchups, predicted 0.81
and won 0.75; the under-0.3 bins hold 9, predicted 0.21 and won 0.11.

Read: better than a coin flip in every league (Brier 0.20-0.22) and nowhere near the over-confident signature of the synthetic
check (0.26 with the 0.7+ bins winning 0.59). The tails are too thin to read: the 0.7+ bins are 3, 3 and 1 matchups, and they
point in opposite directions (L1 won 1 of 3 in 0.7-0.8, L2 and L3 won every one). The middle leans under-confident in L3 and
pooled (0.4-0.5 won 0.38, 0.6-0.7 won 0.75: more spread than the 0.45 and 0.65 promised), which would say the sigma is too
wide, but one bin at n 5 swings 0.2 on a single matchup. **Ruling on the sigma prior: no direction; `BASE_SIGMA` and
`CV_FLOOR` stay.** The plan's test (the 0.7+ bins off by more than their sampling noise, the same way, in all three leagues)
is not met and cannot be met before the season ends: at 16 matchups a league-week the 0.7+ bins reach about 20 pooled by the
last regular-season week. Re-pull and re-run then; the fitter (`ff accuracy --fit`, D2) owns the value if the direction shows.

### The optimizer against the lineups managers set

Each row is one team-week against the opponent's recorded score; `set` is the lineup as the manager left it, `highest points`
the projections' own best lineup, `P(win)` the objective the card uses. `left on the bench` is highest points minus set.

| league | team-weeks | set pts | set win | highest pts | highest win | P(win) pts | P(win) win | left on the bench /wk | differs (n, min 20) | differs: highest win | differs: P(win) win | promised | realized |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L1 | 72 | 118.1 | 0.500 | 119.9 | 0.514 | 119.9 | 0.514 | +1.8 | 0 | — | — | — | — |
| L2 | 60 | 131.3 | 0.500 | 131.3 | 0.517 | 132.2 | 0.533 | -0.0 | 15 | 0.600 | 0.667 | +0.047 | +0.067 |
| L3 | 60 | 120.5 | 0.500 | 123.3 | 0.550 | 123.3 | 0.550 | +2.8 | 0 | — | — | — | — |

Read: the managers in L1 and L3 leave 2-3 points a week on the bench by ESPN's own ranking, the ones in L2 none (they
out-pick ESPN's number by a hair, which is noise). The P(win) lineup was the highest-points lineup in every one of L1's and
L3's 132 team-weeks and differed in 15 of L2's 60; where it differed it won 0.667 to the highest-points lineup's 0.600,
realizing +0.067 of win rate on a promised +0.047. That is the right direction and under `DIFFERS_MIN_N`. **Ruling on
`MIN_WIN_GAIN` (1.5pp): stays.** The floor comes down only when `differs` reaches 20 with `gain_realized` at least half of
`gain_promised`, which at this rate is a few weeks away in L2 alone and never in L1 or L3, where the objective and the points
agree.

### Trades ESPN executed

`ff backtest --trades` against the 2026 replay. `realized /wk` is the points the players I got scored minus the ones I gave,
per replayed week after the close, bench or not (the plan's definition; a 3-for-1 counts all three).

| league | gave | got | closed | from week | weeks | missing | realized /wk | predicted /wk | hit |
|---|---|---|---|---|---|---|---|---|---|
| L1 | Chris Rodriguez Jr., Bhayshul Tuten, Jalen Coker | Chuba Hubbard | 2026-10-14 | 6 | 1 | 0 | -26.8 | — | — |

Read: one trade, one week (Hubbard 19.1 against Tuten 24.7, Coker 15.7 and Rodriguez 5.5 on the bench), no prediction recorded
on it (the outcome predates `rulings.predicted_ppw`). Not a number to act on; the row is here so the next one has a neighbour.
