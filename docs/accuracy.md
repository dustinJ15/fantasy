# Projection accuracy, by source and position

Status: measurement, re-run with `uv run ff accuracy` (the projlog branch restored first: `scripts/projlog_push.sh --restore`)
and `uv run ff backtest` / `ff backtest --trades` / `--scan` / `--claims` (the replays pulled first: `ff replay-pull --season 2026`).
Written: 2026-10-08 against the week 1-4 logs; moved here from ROADMAP.md on 2026-10-20 (Docs-1); the backtest tables added
2026-10-20 (D11); the scanner replay tables 2026-10-21 (D12 step 5).
TODO ids: D2 (adopt the fitted variance once a position has 150 scored forecasts); D13 (the wire body with no preseason total,
done 2026-10-21: this week's number as the stand-in prior, the claim tables below re-printed on it); D14, D15, D16 (re-read
`CLAIM_WORTHY_PPW`, `MUST_TRY_PPW`, `SEND_MIN_PPW` at the end of the regular season).
Still open: D2, D14, D15, D16.

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
scorers; `ff backtest --prior`, D17, scores the price behind every row the same way, below). Every regular-season week with a later replayed week, every team as me: a week-1 package or claim is graded on
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

L1: weeks 1-5 graded through week 6, 60 team-weeks, 1171 rows, 67 adds the managers made (3 more not in the universe)
L2: weeks 1-5 graded through week 6, 50 team-weeks, 1774 rows, 71 adds the managers made
L3: weeks 1-5 graded through week 6, 50 team-weeks, 950 rows, 72 adds the managers made (2 more not in the universe)

| league | sample | n | bodies | hit | promised /wk over the starter | realized /wk |
|---|---|---|---|---|---|---|
| L1 | every row | 1171 | 129 | 0.63 | -2.22 | -2.78 |
| L1 | every row, nobody at zero | 1155 | 129 | 0.63 | -2.21 | -2.70 |
| L1 | every row, touching a zero | 16 | 5 | 0.88 | -2.86 | -8.73 |
| L1 | the card's first claim | 60 | 10 | 0.62 | -0.52 | -3.92 |
| L1 | the card's first claim, both on the field after | 29 | 8 | 0.62 | -1.07 | +0.81 |
| L1 | the card's first claim, a body dark after | 31 | 4 | 0.61 | -0.01 | -8.33 |
| L1 | the card's first claim, dark, no preseason total | 30 | 3 | 0.60 | -0.06 | -9.36 |
| L1 | claim-worthy | 22 | 8 | 0.46 | +1.85 | -1.57 |
| L1 | claim-worthy, both on the field after | 10 | 4 | 0.90 | +1.80 | +4.40 |
| L1 | claim-worthy, a body dark after | 12 | 5 | 0.08 | +1.89 | -6.54 |
| L1 | claim-worthy, dark, no preseason total | 11 | 4 | 0.00 | +1.93 | -9.16 |
| L1 | the managers' adds | 67 | 63 | 0.40 | -3.59 | +0.57 |
| L2 | every row | 1773 | 159 | 0.59 | -2.04 | -1.27 |
| L2 | every row, nobody at zero | 1750 | 158 | 0.59 | -2.03 | -1.19 |
| L2 | every row, touching a zero | 23 | 7 | 1.00 | -2.85 | -7.31 |
| L2 | the card's first claim | 50 | 14 | 0.36 | +0.20 | -4.73 |
| L2 | the card's first claim, both on the field after | 21 | 8 | 0.52 | -0.85 | +1.95 |
| L2 | the card's first claim, a body dark after | 29 | 6 | 0.24 | +0.96 | -9.57 |
| L2 | the card's first claim, dark, no preseason total | 29 | 6 | 0.24 | +0.96 | -9.57 |
| L2 | claim-worthy | 52 | 30 | 0.44 | +1.62 | -1.56 |
| L2 | claim-worthy, both on the field after | 30 | 23 | 0.73 | +1.50 | +3.58 |
| L2 | claim-worthy, a body dark after | 22 | 8 | 0.04 | +1.79 | -8.55 |
| L2 | claim-worthy, dark, no preseason total | 21 | 7 | 0.00 | +1.83 | -9.10 |
| L2 | the managers' adds | 71 | 69 | 0.44 | -3.13 | +1.17 |
| L3 | every row | 946 | 146 | 0.61 | -2.11 | -2.86 |
| L3 | every row, nobody at zero | 939 | 146 | 0.61 | -2.11 | -2.84 |
| L3 | every row, touching a zero | 7 | 4 | 0.57 | -2.62 | -6.03 |
| L3 | the card's first claim | 50 | 14 | 0.56 | -0.48 | -7.84 |
| L3 | the card's first claim, both on the field after | 24 | 9 | 0.50 | -0.72 | -0.49 |
| L3 | the card's first claim, a body dark after | 26 | 5 | 0.61 | -0.25 | -14.63 |
| L3 | the card's first claim, dark, no preseason total | 26 | 5 | 0.61 | -0.25 | -14.63 |
| L3 | claim-worthy | 17 | 10 | 0.23 | +1.70 | -10.17 |
| L3 | claim-worthy, both on the field after | 7 | 6 | 0.57 | +1.47 | +1.31 |
| L3 | claim-worthy, a body dark after | 10 | 4 | 0.00 | +1.86 | -18.21 |
| L3 | claim-worthy, dark, no preseason total | 10 | 4 | 0.00 | +1.86 | -18.21 |
| L3 | the managers' adds | 72 | 70 | 0.53 | -2.85 | -1.99 |

| league | START NOW rows | n | hit | promised this week | realized |
|---|---|---|---|---|---|
| L1 | every row | 20 | 0.70 | +2.76 | +2.35 |
| L2 | every row | 66 | 0.68 | +3.53 | +2.80 |
| L2 | the card's first claim | 5 | 0.40 | +3.27 | -2.08 |
| L2 | the card's first claim, both on the field after | 3 | 0.67 | +4.12 | -1.20 |
| L2 | claim-worthy | 6 | 0.33 | +2.21 | -0.72 |
| L2 | claim-worthy, both on the field after | 4 | 0.50 | +2.32 | +0.62 |
| L3 | every row | 25 | 0.48 | +2.12 | -1.76 |
| L3 | the card's first claim | 2 | 0.00 | +2.63 | -12.74 |
| L3 | claim-worthy | 2 | 0.00 | +2.63 | -12.74 |

| promised /wk | sample | L1 n | L1 hit | L1 realized | L2 n | L2 hit | L2 realized | L3 n | L3 hit | L3 realized |
|---|---|---|---|---|---|---|---|---|---|---|
| under 0 | every row | 1018 | 0.67 | -2.88 | 1568 | 0.61 | -1.32 | 823 | 0.64 | -2.89 |
| 0-1 | every row | 52 | 0.33 | -2.44 | 110 | 0.46 | -0.45 | 51 | 0.39 | -3.14 |
| 1-2 | every row | 66 | 0.41 | -1.75 | 73 | 0.42 | -0.69 | 48 | 0.42 | -2.25 |
| 2-4 | every row | 35 | 0.29 | -2.24 | 22 | 0.27 | -3.23 | 24 | 0.33 | -2.54 |
| 4+ | every row | 0 | — | — | 0 | — | — | 0 | — | — |
| under 0 | the card's first claim | 39 | 0.77 | -4.68 | 21 | 0.62 | -3.16 | 30 | 0.80 | -7.26 |
| 0-1 | the card's first claim | 9 | 0.44 | -0.90 | 7 | 0.14 | -2.34 | 7 | 0.29 | -1.10 |
| 1-2 | the card's first claim | 9 | 0.33 | -2.08 | 17 | 0.23 | -5.24 | 10 | 0.20 | -10.93 |
| 2-4 | the card's first claim | 3 | 0.00 | -8.56 | 5 | 0.00 | -12.94 | 3 | 0.00 | -19.13 |
| 4+ | the card's first claim | 0 | — | — | 0 | — | — | 0 | — | — |
| under 0 | claim-worthy | 0 | — | — | 0 | — | — | 0 | — | — |
| 0-1 | claim-worthy | 0 | — | — | 0 | — | — | 0 | — | — |
| 1-2 | claim-worthy | 16 | 0.44 | -1.52 | 42 | 0.48 | -0.62 | 13 | 0.31 | -8.66 |
| 2-4 | claim-worthy | 6 | 0.50 | -1.69 | 10 | 0.30 | -5.49 | 4 | 0.00 | -15.07 |
| 4+ | claim-worthy | 0 | — | — | 0 | — | — | 0 | — | — |
| under 0 | the managers' adds | 58 | 0.40 | +0.30 | 62 | 0.45 | +1.19 | 60 | 0.55 | -2.35 |
| 0-1 | the managers' adds | 4 | 0.25 | +0.40 | 5 | 0.60 | +3.34 | 9 | 0.44 | -0.57 |
| 1-2 | the managers' adds | 3 | 0.67 | +7.19 | 2 | 0.00 | -3.46 | 2 | 0.50 | +2.11 |
| 2-4 | the managers' adds | 2 | 0.50 | -1.29 | 2 | 0.00 | -0.10 | 1 | 0.00 | -1.00 |
| 4+ | the managers' adds | 0 | — | — | 0 | — | — | 0 | — | — |

Read (the tables above are the re-print of 2026-10-21 with the D13 floor in; the first print's numbers are in the bullets
where they differ): the card's first claim per team-week realized 3.9 to 7.8 a week *under* the starter he displaces, in all
three leagues, on a promise near zero; the claim-worthy rows (an upgrade of a point or more, the rows `priority_cost` prices
live) promised +1.6 to +1.9 and realized -1.6, -1.6 and -10.2 with a hit rate of 0.23 to 0.46; the managers' own adds, which
the ranking priced at -3 to -4 a week (bench depth, handcuffs, a streamer), realized +0.6, +1.2 and -2.0. On its face the
ranking is worse than the league. It is not that simple, and the rows say why.

- **The top of the ranking is bodies that went dark.** A hand count over the scored rows (`claim_week` then
  `score_claims`, the claimed player's actuals in every later week): 36 of L1's 60 first claims, 34 of L2's 50 and
  26 of L3's 50 scored zero in every week after the claim, and those 96 rows are 5, 7 and 5 distinct players (Carson
  Wentz in week 2 is the first claim for seven to nine teams in every league; David Njoku, Demarcus Robinson, Mack
  Hollins, Tyquan Thornton, Marcus Mariota the rest): a fill-in starter whose starter came back, a body hurt the next
  week. Every one of the 96 has `proj_season` 0: ESPN gave him no preseason total, so `season_pg` has no prior to fade
  and the rest-of-season price is his last game or two. The same number reaches the live ranking through
  `projected_total_points`, so this is the live card's shape too, less the signals the replay lacks (the designation,
  Sleeper's trend, FantasyPros' rest-of-season rank, Claude's read of why he was on the wire). Since 2026-10-21 the hand
  count is a printed row: `ff backtest --claims` splits every sample by whether the claimed body or the displaced starter
  went dark after the row (`both on the field after`, `a body dark after`, `dark, no preseason total`) with the distinct
  bodies behind each n.
- **The floor (D13, 2026-10-21): this week's number is the prior a body with no preseason total fades.** Scored on the
  wire bodies within three points of a starter in weeks 1-5 (his price at week w against his own points a game after it):
  with no prior the no-prior body read +0.6, +0.8 and +1.0 a game over what he scored, 3.5, 3.4 and 3.35 mean absolute;
  with this week's matchup-neutral number as the prior `season_pg` fades (`level_prior` in `blend`) +0.5, +0.7 and +0.9
  and 3.3 in all three; the position's replacement level as the prior was worse than no prior on every row set (+0.6 to
  +1.2, 3.4) and needs a second pricing pass, so it is not built. What the floor moved: the one-game spike (a kicker at
  13.5 a game after a 19-point week now reads 8.9; the 4+ bin of the first table, two kickers and a QB, is empty) and
  nothing else. L1's first claim went from -4.55 to -3.92 and its claim-worthy rows from -2.60 to -1.57 (hit 0.37 to
  0.46); L2 and L3 barely moved (-4.98 to -4.73, -7.57 to -7.84), because their dark first claims are the QBs ESPN
  itself projected at 16-18 that week (Wentz, Lock, Mariota): the floor prices him at ESPN's number, which is right,
  and he went dark for a reason no price sees (the starter came back). The clean rows did not move (claim-worthy, both
  on the field: +4.7 to +4.4, +3.7 to +3.6, +1.6 to +1.3). A second finding, not this fix: the in-range wire body *with* a
  preseason total is under-priced by that prior (bias -1.3, -1.2 and -1.1 a game, 3.4 mean absolute; this week's number
  as his prior too would read +0.3 and 3.2): scored on everyone under "The rest-of-season prior" below (D17, 2026-10-21),
  the prior stays.
- **Where the body stayed on the field the ranking has edge.** The claim-worthy rows with neither the claimed player
  nor the displaced starter dark: L1 n 10, hit 0.90, promised +1.7, realized +4.7; L2 n 29, hit 0.76, promised +1.5,
  realized +3.7; L3 n 6, hit 0.67, promised +1.4, realized +1.6 (the same hand count). Under-promised, not over: the
  starter a claim displaces is the weakest at his slot by `mu_ros`, and he lost his job or his health as often as the
  wire body did.
- **The one-week promise reads honestly.** START NOW rows (`delta_week` at 1.5 or more) promised +2.9, +3.5 and +2.3
  this week and realized +2.6, +2.8 and -4.7: two leagues within half a point at n 16 and 66, L3 at n 17 one bad
  Sunday wide. The week-w projection is ESPN's own; the one-week read adds nothing to it and loses nothing.
- **The reliability rows have the winner's-curse shape step 4 predicted**, at full size: the 0-1 and 1-2 bins realize
  one to two points under their promise in every league, every sample; the 4+ bin was one to two players before the D13
  floor and is empty with it.
- **The sample is five weeks and a handful of bodies.** The team-weeks are not independent: one wire player's next
  month swings seven to twelve rows at once. n in these tables is rows; the bodies behind the top rows are five to
  eight per league.

**Ruling on `CLAIM_WORTHY_PPW` (1.0): stays.** The clean claim-worthy rows realize more than they promise in all three
leagues, which argues for no higher bar; the dark ones are a pricing hole, not a threshold one (the bar cannot tell a
hot fill-in from a starter). Re-read with the D13 floor in (2026-10-21, above): stays. Again at the end of the regular season (TODO D14 holds the line).

### The rest-of-season prior

`ff backtest --prior` (D17, 2026-10-21): every body priced in weeks 1-5, rostered (`WeekInputs.everyone`: the number behind
the hold, trade and drop rows, and the starter a claim displaces) and wire (`pool`) apart, his price at week w
(`mu_ros_active`, the healthy per-game level `season_pg` and `per_game` build) against his points a game over the weeks
after it (every later week with an actual is a game, a zero on a game week included, his bye none; `on the field after`
drops the rows where he scored zero in every one), under the prior `season_pg` fades today and the alternatives D17 named.
`stays`: ESPN's preseason total per NFL game, this week's matchup-neutral number in its place when he has none (D13), over
`PRIOR_FADE_GAMES` (6); `faster`: the same prior over three games; `larger`: the larger of the total and this week's
number; `week`: this week's number whether or not he has a total; `none`: his own games alone. `wire near a starter` is
the wire body within three points of the weakest rest-of-season starter he could displace on some roster
(`PRIOR_NEAR_PPW`): the rows the claim ranking prints, the D13 and D17 sample. Each cell is bias / mean absolute error in
points a game, over zero over-priced; the rows with no total are one price under `stays`, `larger` and `week` (he fades
this week's number already) and print for the fade and for `none`.

| league | sample | n | bodies | stays | faster | larger | week | none |
|---|---|---|---|---|---|---|---|---|
| L1 | rostered, a total | 816 | 195 | -0.30 / 4.65 | +0.24 / 4.81 | +1.15 / 4.85 | +1.14 / 4.85 | +1.02 / 5.13 |
| L1 | rostered, a total, on the field after | 749 | 187 | -1.02 / 4.37 | -0.43 / 4.55 | +0.51 / 4.54 | +0.51 / 4.54 | +0.47 / 4.95 |
| L1 | wire, a total | 1132 | 258 | -0.99 / 2.44 | -0.94 / 2.55 | -0.48 / 2.50 | -0.56 / 2.56 | -0.92 / 2.78 |
| L1 | wire near a starter, a total | 239 | 90 | -1.62 / 3.72 | -1.11 / 3.80 | -0.18 / 3.58 | -0.22 / 3.62 | -0.28 / 3.92 |
| L1 | wire near a starter, a total, on the field after | 231 | 87 | -1.86 / 3.66 | -1.35 / 3.73 | -0.40 / 3.50 | -0.44 / 3.54 | -0.49 / 3.86 |
| L1 | rostered, no total | 143 | 39 | +2.75 / 4.41 | +2.59 / 4.30 | +2.75 / 4.41 | +2.75 / 4.41 | +2.41 / 4.34 |
| L1 | wire near a starter, no total | 151 | 55 | +1.12 / 4.06 | +0.94 / 4.03 | +1.12 / 4.06 | +1.12 / 4.06 | +0.83 / 4.02 |
| L2 | rostered, a total | 723 | 177 | -0.20 / 4.66 | +0.35 / 4.84 | +1.23 / 4.89 | +1.22 / 4.89 | +1.14 / 5.19 |
| L2 | rostered, a total, on the field after | 664 | 171 | -0.96 / 4.33 | -0.37 / 4.53 | +0.55 / 4.53 | +0.54 / 4.53 | +0.55 / 4.95 |
| L2 | wire, a total | 1225 | 278 | -0.98 / 2.54 | -0.91 / 2.65 | -0.45 / 2.61 | -0.52 / 2.67 | -0.88 / 2.88 |
| L2 | wire near a starter, a total | 387 | 139 | -1.30 / 3.74 | -0.89 / 3.86 | -0.16 / 3.77 | -0.19 / 3.81 | -0.31 / 4.01 |
| L2 | wire near a starter, a total, on the field after | 371 | 134 | -1.60 / 3.66 | -1.20 / 3.76 | -0.45 / 3.65 | -0.48 / 3.69 | -0.61 / 3.90 |
| L2 | rostered, no total | 115 | 36 | +2.54 / 4.79 | +2.47 / 4.79 | +2.54 / 4.79 | +2.54 / 4.79 | +2.26 / 4.90 |
| L2 | wire near a starter, no total | 188 | 68 | +1.56 / 4.01 | +1.35 / 3.91 | +1.56 / 4.01 | +1.56 / 4.01 | +1.23 / 3.87 |
| L3 | rostered, a total | 708 | 175 | -0.14 / 4.72 | +0.41 / 4.91 | +1.31 / 4.97 | +1.31 / 4.97 | +1.21 / 5.28 |
| L3 | rostered, a total, on the field after | 653 | 170 | -0.86 / 4.41 | -0.24 / 4.63 | +0.68 / 4.64 | +0.67 / 4.64 | +0.68 / 5.09 |
| L3 | wire, a total | 1240 | 282 | -1.00 / 2.53 | -0.94 / 2.63 | -0.48 / 2.59 | -0.55 / 2.64 | -0.89 / 2.86 |
| L3 | wire near a starter, a total | 285 | 108 | -1.76 / 3.77 | -1.32 / 3.83 | -0.51 / 3.61 | -0.55 / 3.63 | -0.66 / 3.92 |
| L3 | wire near a starter, a total, on the field after | 279 | 103 | -1.95 / 3.69 | -1.52 / 3.74 | -0.71 / 3.49 | -0.75 / 3.52 | -0.86 / 3.82 |
| L3 | rostered, no total | 96 | 30 | +2.80 / 5.12 | +2.74 / 5.11 | +2.80 / 5.12 | +2.80 / 5.12 | +2.58 / 5.31 |
| L3 | wire near a starter, no total | 163 | 58 | +1.24 / 4.19 | +1.01 / 4.08 | +1.24 / 4.19 | +1.24 / 4.19 | +0.86 / 4.02 |

Read:

- **The finding holds, and reads larger on everyone than the claim tables' sample did.** The in-range wire body with a
  total is priced 1.3 to 1.8 a game under what he scored after in all three leagues (1.6 to 2.0 on the rows where he
  stayed on the field), the whole wire a point under: his total is a backup's, and through week 5 the fade still gives it
  a sixth to five sixths of the weight while he is producing.
- **`larger` is the one prior that removes it, and it costs the rostered body more.** On the in-range wire body it reads
  -0.2 to -0.5 and lowers the error in two leagues (3.72 to 3.58, 3.77 to 3.61; L2 flat). On the rostered body with a
  total, 816, 723 and 708 rows, it reads +1.2 to +1.3 over where `stays` is within 0.3 of zero, and his error goes up 0.2
  to 0.25; the wire as a whole reads worse too. The `week` column says why: this week's number carries ESPN's weekly
  optimism (+1.1 to +1.3 on the rostered body on its own), which the fading total damps; on the wire body the weekly
  number is small enough that the same optimism is the lesser error.
- **`faster` is worse than `stays` on every sample with a total.** The level of the prior is the question, not the fade.
- **The bodies with no total read as D13 left them**: `none` a little better on the wire (2.73 against 2.81) and worse
  on a roster. The rostered body with no total reads +2.5 to +2.8 over (+1.6 to +1.9 on the field; 96 to 143 rows, 30 to
  39 bodies) under every prior, a finding the claim tables could not see: TODO D19.
- **The sample is five weeks of one season and the same bodies in every league.** n is rows; one player's next month
  swings five rows at once, and the three leagues share a wire.

**Ruling on the prior (2026-10-21): stays.** One number prices a body wherever he sits, and a claim row compares him with a
rostered starter priced the same way, so the prior that fixes the wire body's point is paid by every rostered body on the
card. The under-pricing is a known bias of the claim ranking (the clean claim-worthy rows realize more than they promise,
above) and `CLAIM_WORTHY_PPW`'s re-read is where it is priced (D14). Re-read on the full-season replay (D18): `larger`
takes over if it lowers the rostered body's error too, or if the in-range wire bias passes two points while the rostered
one holds within half a point of zero.

**The rostered body with no total (D19, 2026-10-21): the row was a leak, not a pricing bias.** The bodies behind it were
Hurts, Achane, Pittman, Dart, Jayden Reed and Jonathon Brooks: starters priced healthy at week w who went dark after,
every one on IR or Out on the day of the pull. ESPN zeroes the season row (period 0's `projected_points`) of a player it
lists on IR or Out that day (Hurts read a total of 0 with 82 points banked; of the universe's IR bodies at QB, RB, WR and
TE, 80 had no total and 8 did; Questionable and Doubtful leave it alone), so "no total" in a replay pulled mid-season is
"hurt today" for a body the live packet priced with his total every week until he was hurt: a selection on the future
that no prior removes, and neither `level_prior` nor `weeks_out` owns. The pull now keeps `total_zeroed` (no total and
IR or Out on the pull day, `backtest.TOTAL_ZEROED_STATUSES`: the one thing it reads from today's designation) and the
tables set those bodies aside; a file pulled before the flag prints a warning. Re-pulled 2026-10-21, weeks 1-5 graded
through week 6 (the rows with a total are unchanged; `larger` and `week` equal `stays` on a no-total body and are left out):

| league | sample | n | bodies | stays | faster | none |
|---|---|---|---|---|---|---|
| L1 | rostered, no total | 76 | 21 | +0.33 / 3.13 | +0.18 / 3.02 | +0.08 / 3.09 |
| L1 | rostered, total zeroed on the pull day | 67 | 18 | +5.49 / 5.86 | +5.33 / 5.76 | +5.06 / 5.75 |
| L1 | wire near a starter, no total | 123 | 40 | +0.06 / 3.66 | -0.14 / 3.64 | -0.27 / 3.62 |
| L2 | rostered, no total | 56 | 18 | -0.83 / 3.33 | -0.83 / 3.42 | -0.96 / 3.63 |
| L2 | rostered, total zeroed on the pull day | 59 | 18 | +5.74 / 6.17 | +5.60 / 6.09 | +5.31 / 6.10 |
| L2 | wire near a starter, no total | 147 | 50 | +0.61 / 3.54 | +0.38 / 3.43 | +0.27 / 3.40 |
| L3 | rostered, no total | 53 | 16 | -0.42 / 3.44 | -0.39 / 3.48 | -0.42 / 3.78 |
| L3 | rostered, total zeroed on the pull day | 43 | 14 | +6.76 / 7.18 | +6.59 / 7.11 | +6.28 / 7.21 |
| L3 | wire near a starter, no total | 136 | 42 | +0.20 / 3.69 | -0.05 / 3.58 | -0.19 / 3.53 |

Read: the genuine no-total rostered body (a kicker or D/ST, a fill-in QB, a backup) reads within a point of zero in all
three leagues (+0.3, -0.8, -0.4; the kickers alone were +0.3, -0.4 and -0.6 before the split), and the zeroed bodies
+5.5 to +6.8, a starter who got hurt under any price. The D13 wire sample (`wire near a starter, no total`) carried the
same bodies: +1.1 to +1.6 in the table above, +0.1 to +0.6 with them apart, and there `none` reads 0.05 to 0.15 better
in error, while on the rostered no-total body it reads 0.3 worse in two leagues; the D13 prior stays (it was adopted to
keep a one-game kicker off the top of the claim ranking, which the error alone does not price) and is re-read with D18.
The claim tables' `no_prior` and `dark_no_prior` splits hold the same zeroed bodies and are not yet read apart (TODO D20).
