# Projection accuracy, by source and position

Status: measurement, re-run with `uv run ff accuracy` (the projlog branch restored first: `scripts/projlog_push.sh --restore`)
and `uv run ff backtest` / `ff backtest --trades` / `--scan` / `--claims` (the replays pulled first: `ff replay-pull --season 2026`).
Written: 2026-10-08 against the week 1-4 logs; moved here from ROADMAP.md on 2026-10-20 (Docs-1); the backtest tables added
2026-10-20 (D11); the scanner replay tables 2026-10-21 (D12 step 5).
TODO ids: D2 (adopt the fitted variance once a position has 150 scored forecasts); D13 (the wire body with no preseason total);
D14, D15, D16 (re-read `CLAIM_WORTHY_PPW`, `MUST_TRY_PPW`, `SEND_MIN_PPW` at the end of the regular season).
Still open: D2, D13, D14, D15, D16.

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

## The scanner replay: 2026 weeks 1-5, graded through week 6, pulled and scored 2026-10-21

`ff replay-pull --season 2026` for the three leagues (the version-2 file: the player universe, 1054 players in each), then
`ff backtest --scan` and `ff backtest --claims` (D12 step 5, the first real run of `docs/plans/scanner-replay.md`'s two
scorers). Every regular-season week with a later replayed week, every team as me: a week-1 package or claim is graded on
five weeks, a week-5 one on week 6 alone. What the replay cannot carry, and the tables are read with: FantasyCalc keeps no
archive, so the scan ran with no market values (no lowball veto, no star, no throw-in; `p_accept` on the other signals and
with no truth to grade it against); Sleeper keeps no archive of adds and ESPN none of the waiver order, so the claim ranking
ran with no trend and the priority a claim spends was not priced; the archive keeps no designation, so a player ESPN had at
zero that week is priced as healthy from the next (the `touching a zero` rows) and a player hurt after the row is a healthy
body who scored nothing.

### The trade scan

`promised /wk` is `my_delta_ppw`, the lineup delta the card prints; `realized lineup /wk` is what it forecasts (the week-w
roster with and without the swap, each seated by the highest-points lineup on each later week's projection and scored with
the actuals, the week-w wire in both); `realized raw /wk` is `score_trade`'s definition (the players got minus the players
given, bench or not, the outcome log's scale). `hit` is the sign of the lineup number against the promise. The card's top 3
are the three packages per team-week by `p_accept × my_delta_ppw`.

L1: packages proposed in weeks 1-5, graded through week 6, 60 team-weeks, 2141 packages, the sim at 1000 draws
L2: packages proposed in weeks 1-5, graded through week 6, 50 team-weeks, 845 packages, the sim at 1000 draws
L3: packages proposed in weeks 1-5, graded through week 6, 50 team-weeks, 1534 packages, the sim at 1000 draws

| league | sample | n | hit | promised /wk | realized lineup /wk | realized raw /wk |
|---|---|---|---|---|---|---|
| L1 | every package | 2141 | 0.56 | +1.73 | +1.73 | +2.28 |
| L1 | every package, nobody at zero | 2043 | 0.55 | +1.74 | +1.66 | +2.28 |
| L1 | every package, touching a zero | 98 | 0.66 | +1.64 | +3.29 | +2.32 |
| L1 | the card's top 3 | 178 | 0.69 | +2.68 | +4.94 | +8.52 |
| L1 | the card's top 3, nobody at zero | 173 | 0.69 | +2.68 | +4.94 | +8.50 |
| L1 | the card's top 3, touching a zero | 5 | 0.60 | +2.90 | +4.88 | +9.35 |
| L2 | every package | 845 | 0.53 | +1.24 | +1.38 | -0.13 |
| L2 | every package, nobody at zero | 809 | 0.53 | +1.25 | +1.27 | -0.31 |
| L2 | every package, touching a zero | 36 | 0.67 | +1.06 | +3.82 | +3.99 |
| L2 | the card's top 3 | 145 | 0.57 | +1.54 | +1.87 | +1.31 |
| L2 | the card's top 3, nobody at zero | 132 | 0.55 | +1.57 | +1.72 | +1.39 |
| L2 | the card's top 3, touching a zero | 13 | 0.77 | +1.21 | +3.42 | +0.53 |
| L3 | every package | 1534 | 0.51 | +1.51 | +1.17 | +0.39 |
| L3 | every package, nobody at zero | 1504 | 0.51 | +1.52 | +1.09 | +0.46 |
| L3 | every package, touching a zero | 30 | 0.80 | +1.41 | +5.17 | -3.15 |
| L3 | the card's top 3 | 150 | 0.54 | +2.20 | +1.06 | -0.42 |
| L3 | the card's top 3, nobody at zero | 148 | 0.54 | +2.20 | +1.05 | -0.29 |
| L3 | the card's top 3, touching a zero | 2 | 0.50 | +2.12 | +1.69 | -10.25 |

| promised /wk | sample | L1 n | L1 hit | L1 realized | L2 n | L2 hit | L2 realized | L3 n | L3 hit | L3 realized |
|---|---|---|---|---|---|---|---|---|---|---|
| 0-1 | every package | 458 | 0.47 | -0.32 | 310 | 0.57 | +2.03 | 401 | 0.49 | +0.22 |
| 1-2 | every package | 1077 | 0.54 | +1.38 | 480 | 0.50 | +0.78 | 813 | 0.51 | +1.18 |
| 2-4 | every package | 534 | 0.65 | +3.58 | 55 | 0.56 | +2.88 | 307 | 0.56 | +2.40 |
| 4+ | every package | 72 | 0.67 | +6.32 | 0 | — | — | 13 | 0.39 | +0.92 |
| 0-1 | the card's top 3 | 3 | 0.67 | +2.11 | 21 | 0.71 | +2.06 | 7 | 0.57 | -1.61 |
| 1-2 | the card's top 3 | 55 | 0.56 | +0.58 | 95 | 0.55 | +1.99 | 54 | 0.44 | -1.31 |
| 2-4 | the card's top 3 | 94 | 0.76 | +6.16 | 29 | 0.52 | +1.36 | 82 | 0.63 | +3.20 |
| 4+ | the card's top 3 | 26 | 0.73 | +10.10 | 0 | — | — | 7 | 0.14 | -2.99 |

Read: the lineup promise is calibrated at this size. Every package in L1 promised +1.73 a week and realized +1.73; L2 +1.24
against +1.38; L3 +1.51 against +1.17. The reliability rows hold their order in every league: the 2-4 bin realizes +2.4 to
+3.6 with a hit rate of 0.56 to 0.65, the 1-2 bin +0.8 to +1.4 at a coin flip, the 0-1 bin -0.3 to +2.0 at a coin flip. The
card's top 3 beat their promise in L1 (+2.7 promised, +4.9 realized, hit 0.69) and L2 (+1.5, +1.9) and fell short in L3
(+2.2, +1.1, the 4+ bin there 7 packages at -3.0). The winner's curse the synthetic season showed (1.4 promised, 0.6
realized) is not in the real one: the synthetic's packages were selected on a few games of noise, the real ones on a preseason
total and five games. The raw delta sits well above the lineup delta in L1 (+8.5 a week on the top 3): the 2-for-1s, whose
bench points the lineup number rightly ignores. Three cautions. Five weeks, graded on one to five weeks each, and the same
players recur across teams, so n is packages, not independent outcomes. The chart was off: some of these packages the live
scan would veto as a lowball or refuse to send for a star, and whether the rival says yes has no truth here. The
`touching a zero` rows realize two to four points over the rest (a player ESPN zeroed in week w who came back the next):
the live scan would have priced his return week and promised less. **Ruling on `MUST_TRY_PPW` (2.0): stays**: the bar
sits where the 2-4 bin starts realizing its promise in all three leagues (TODO D15 re-reads it at the end of the regular
season). **Ruling on `SEND_MIN_PPW` (1.0): stays**: the 0-1 bin is noise in every league (hit 0.47 to 0.57, realized either
side of zero), and the 1-2 bin realizes under a point in L2 with a coin-flip hit, which is the case for 1.5 if it holds at
the end of the regular season (TODO D16).

### The claim ranking

`promised /wk over the starter` is `delta_over_starter`, the upgrade the card prints over the weakest rest-of-season starter
at the row's slot; `realized /wk` is the claimed player's actual minus that starter's, averaged over the later weeks, the
starter fixed at week w. START NOW rows are the ones with `delta_week` at 1.5 or more, graded on week w alone against the
week starter they displace. The managers' adds are the players on no week-w roster and on one in week w+1, priced at week
w for the team that added them exactly as a claim row.

L1: weeks 1-5 graded through week 6, 60 team-weeks, 1233 rows, 67 adds the managers made (3 more not in the universe)
L2: weeks 1-5 graded through week 6, 50 team-weeks, 1772 rows, 70 adds the managers made (1 more not in the universe)
L3: weeks 1-5 graded through week 6, 50 team-weeks, 962 rows, 71 adds the managers made (3 more not in the universe)

| league | sample | n | hit | promised /wk over the starter | realized /wk |
|---|---|---|---|---|---|
| L1 | every row | 1233 | 0.64 | -1.85 | -2.86 |
| L1 | every row, nobody at zero | 1216 | 0.63 | -1.84 | -2.77 |
| L1 | every row, touching a zero | 17 | 0.88 | -2.71 | -9.17 |
| L1 | the card's first claim | 60 | 0.55 | -0.21 | -4.55 |
| L1 | claim-worthy | 27 | 0.37 | +1.98 | -2.60 |
| L1 | the managers' adds | 67 | 0.49 | -3.78 | +0.41 |
| L2 | every row | 1772 | 0.59 | -1.89 | -1.26 |
| L2 | every row, nobody at zero | 1749 | 0.58 | -1.87 | -1.17 |
| L2 | every row, touching a zero | 23 | 1.00 | -2.80 | -7.57 |
| L2 | the card's first claim | 50 | 0.38 | +0.26 | -4.98 |
| L2 | claim-worthy | 52 | 0.46 | +1.71 | -1.02 |
| L2 | the managers' adds | 70 | 0.44 | -3.05 | +1.25 |
| L3 | every row | 959 | 0.60 | -2.00 | -2.73 |
| L3 | every row, nobody at zero | 952 | 0.60 | -1.99 | -2.71 |
| L3 | every row, touching a zero | 7 | 0.57 | -2.62 | -6.03 |
| L3 | the card's first claim | 50 | 0.54 | -0.43 | -7.57 |
| L3 | claim-worthy | 12 | 0.33 | +1.80 | -6.57 |
| L3 | the managers' adds | 71 | 0.54 | -2.92 | -2.01 |

| league | START NOW rows | n | hit | promised this week | realized |
|---|---|---|---|---|---|
| L1 | every row | 16 | 0.69 | +2.91 | +2.57 |
| L2 | every row | 66 | 0.68 | +3.53 | +2.80 |
| L2 | the card's first claim | 5 | 0.40 | +3.27 | -2.08 |
| L2 | claim-worthy | 6 | 0.33 | +2.21 | -0.72 |
| L3 | every row | 17 | 0.29 | +2.27 | -4.71 |
| L3 | the card's first claim | 1 | 0.00 | +3.59 | -7.74 |

| promised /wk | sample | L1 n | L1 hit | L1 realized | L2 n | L2 hit | L2 realized | L3 n | L3 hit | L3 realized |
|---|---|---|---|---|---|---|---|---|---|---|
| under 0 | every row | 1016 | 0.69 | -3.16 | 1524 | 0.61 | -1.34 | 827 | 0.64 | -2.76 |
| 0-1 | every row | 62 | 0.40 | -1.60 | 117 | 0.42 | -1.23 | 46 | 0.28 | -5.38 |
| 1-2 | every row | 57 | 0.42 | -1.05 | 71 | 0.51 | +0.47 | 34 | 0.44 | -1.94 |
| 2-4 | every row | 72 | 0.29 | -2.13 | 44 | 0.34 | -1.74 | 35 | 0.34 | -1.17 |
| 4+ | every row | 26 | 0.50 | -0.06 | 16 | 0.50 | -0.18 | 17 | 0.59 | +1.20 |
| under 0 | the card's first claim | 36 | 0.78 | -5.08 | 20 | 0.75 | -4.94 | 28 | 0.79 | -7.33 |
| 0-1 | the card's first claim | 7 | 0.29 | -2.11 | 12 | 0.08 | -3.84 | 12 | 0.17 | -7.58 |
| 1-2 | the card's first claim | 9 | 0.33 | -0.26 | 10 | 0.20 | -4.10 | 7 | 0.43 | -3.88 |
| 2-4 | the card's first claim | 6 | 0.00 | -9.62 | 8 | 0.12 | -7.86 | 2 | 0.00 | -19.24 |
| 4+ | the card's first claim | 2 | 0.00 | -7.67 | 0 | — | — | 1 | 0.00 | -16.64 |
| under 0 | claim-worthy | 0 | — | — | 0 | — | — | 0 | — | — |
| 0-1 | claim-worthy | 0 | — | — | 0 | — | — | 0 | — | — |
| 1-2 | claim-worthy | 17 | 0.41 | -0.88 | 39 | 0.51 | +0.01 | 8 | 0.50 | -2.60 |
| 2-4 | claim-worthy | 8 | 0.38 | -4.98 | 13 | 0.31 | -4.08 | 3 | 0.00 | -13.79 |
| 4+ | claim-worthy | 2 | 0.00 | -7.67 | 0 | — | — | 1 | 0.00 | -16.64 |
| under 0 | the managers' adds | 59 | 0.46 | -0.63 | 60 | 0.45 | +1.24 | 60 | 0.55 | -2.39 |
| 0-1 | the managers' adds | 4 | 0.75 | +9.71 | 5 | 0.60 | +2.11 | 7 | 0.43 | -0.85 |
| 1-2 | the managers' adds | 1 | 1.00 | +22.33 | 1 | 1.00 | +6.00 | 2 | 0.50 | +1.80 |
| 2-4 | the managers' adds | 3 | 0.67 | +1.14 | 3 | 0.00 | -0.96 | 2 | 0.50 | +1.58 |
| 4+ | the managers' adds | 0 | — | — | 1 | 0.00 | -0.33 | 0 | — | — |

Read: the card's first claim per team-week realized 4.5 to 7.6 a week *under* the starter he displaces, in all three
leagues, on a promise near zero; the claim-worthy rows (an upgrade of a point or more, the rows `priority_cost` prices
live) promised +1.7 to +2.0 and realized -1.0 to -6.6 with a hit rate of 0.33 to 0.46; the managers' own adds, which the
ranking priced at -3 to -4 a week (bench depth, handcuffs, a streamer), realized +0.4, +1.3 and -2.0. On its face the
ranking is worse than the league. It is not that simple, and the rows say why.

- **The top of the ranking is bodies that went dark.** A hand count over the scored rows (`claim_week` then
  `score_claims`, the claimed player's actuals in every later week): 36 of L1's 60 first claims, 34 of L2's 50 and
  26 of L3's 50 scored zero in every week after the claim, and those 96 rows are 5, 7 and 5 distinct players (Carson
  Wentz in week 2 is the first claim for seven to nine teams in every league; David Njoku, Demarcus Robinson, Mack
  Hollins, Tyquan Thornton, Marcus Mariota the rest): a fill-in starter whose starter came back, a body hurt the next
  week. Every one of the 96 has `proj_season` 0: ESPN gave him no preseason total, so `season_pg` has no prior to fade
  and the rest-of-season price is his last game or two. The same number reaches the live ranking through
  `projected_total_points`, so this is the live card's shape too, less the signals the replay lacks (the designation,
  Sleeper's trend, FantasyPros' rest-of-season rank, Claude's read of why he was on the wire). A new TODO line (D13)
  is that floor; the replay shows the size of the hole, not the fix.
- **Where the body stayed on the field the ranking has edge.** The claim-worthy rows with neither the claimed player
  nor the displaced starter dark: L1 n 10, hit 0.90, promised +1.7, realized +4.7; L2 n 29, hit 0.76, promised +1.5,
  realized +3.7; L3 n 6, hit 0.67, promised +1.4, realized +1.6 (the same hand count). Under-promised, not over: the
  starter a claim displaces is the weakest at his slot by `mu_ros`, and he lost his job or his health as often as the
  wire body did.
- **The one-week promise reads honestly.** START NOW rows (`delta_week` at 1.5 or more) promised +2.9, +3.5 and +2.3
  this week and realized +2.6, +2.8 and -4.7: two leagues within half a point at n 16 and 66, L3 at n 17 one bad
  Sunday wide. The week-w projection is ESPN's own; the one-week read adds nothing to it and loses nothing.
- **The reliability rows have the winner's-curse shape step 4 predicted**, at full size: the 0-1 and 1-2 bins realize
  one to two points under their promise in every league, every sample; the 4+ bin is one to two players.
- **The sample is five weeks and a handful of bodies.** The team-weeks are not independent: one wire player's next
  month swings seven to twelve rows at once. n in these tables is rows; the bodies behind the top rows are five to
  eight per league.

**Ruling on `CLAIM_WORTHY_PPW` (1.0): stays.** The clean claim-worthy rows realize more than they promise in all three
leagues, which argues for no higher bar; the dark ones are a pricing hole, not a threshold one (the bar cannot tell a
hot fill-in from a starter). Re-read after D13 and at the end of the regular season (TODO D14 holds the line).
