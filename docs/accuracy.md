# Projection accuracy, by source and position

Status: measurement, re-run with `uv run ff accuracy` (the projlog branch restored first: `scripts/projlog_push.sh --restore`).
Written: 2026-10-08 against the week 1-4 logs; moved here from ROADMAP.md on 2026-10-20 (Docs-1).
TODO ids: D2 (adopt the fitted variance once a position has 150 scored forecasts).
Still open: D2.

For an agent or Dustin deciding whether a source earns its weight (ROADMAP: re-weight or drop a source only if it trails the
blend by more than 5% for six or more weeks). The rows are what `ff accuracy` printed; the read under the table is the decision.

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
