# Plan: the scanner replay (every trade row and every claim row of every replayed week, graded)

Status: steps 1 and 2 done (TODO D12), the rest planned. Written 2026-10-20 in a session without `leagues.toml`; the probe
(`scripts/probe_replay_pool.py`, the free-agent pool of a past week) ran later that day on all three leagues and its
findings are under "What the probe found" below, with the one change they make to the pull. The harness this extends:
`docs/plans/backtest.md` (D8, D11).
Written: 2026-10-20 against `main` at 4a67182; the probe's findings added against 4230107, the universe pull against eafbcf0.
TODO ids: D12 (steps 3-5, in order, in TODO.md).
Still open: D12 steps 3-5.

For an agent building or reading the scanner replay: the part of the backtest that grades the trade scan (`model/trades.py`
`scan`) and the waiver ranking (`model/waivers.py` `rank_free_agents`) rather than the lineup. ROADMAP item 8's second
half in one line: the outcome log has one executed trade and will have ten in a few seasons; a replayed season has
every package the scan would have proposed each week, for every team, against the weeks that followed. That sample
is where the trade and waiver hit rates come from before the log can supply them.

## The question

The card makes two more claims a season can grade. "Give X for Y, +2.1 a week" (`my_delta_ppw`, the lineup delta
`season.season_value` prices week by week) is a forecast of the points difference the swap makes over the rest of the
season. "Claim Z, +1.4/wk over your RB2" (`delta_over_starter`, or a one-week fill-in's `delta_week`) is a forecast of
what the claimed body scores over the starter he displaces. Both are made on a Tuesday from the rosters and the wire as
they stood; the replay has every roster as it stood before every kickoff, and with one more pull (the player universe,
below) it has the wire too.

The lineup backtest asks the question from my seat only because P(win) is per matchup. The scanner replay asks it from
every seat: each team-week, the scan runs as if that team were me (`my_id` is the team under test, the other teams are
its rivals, its wire is the pool that week), which multiplies the sample by the team count. A 10-team league over 13
weeks is 130 team-weeks and some thousand priced packages; three leagues, three thousand. The claim rows likewise.

## What the scan needs that the replay does not yet carry

`REPLAY_VERSION` 1 keeps each matchup's two rosters with `proj` and `actual` for the week. `scan` and `rank_free_agents`
need the rest-of-season view of every player and the pool nobody held. Where each input comes from, and what it
cannot come from:

| the live scan has | the replay can have | from |
|---|---|---|
| every roster, this week's projection per player | the same | the box scores already pulled (`pull_replay`) |
| the free-agent pool (`espn.free_agent_rows`, top 300 by ownership) | the pool as of week w = the player universe minus everyone on a week-w roster | one pull of the universe per league per season (`kona_player_info`, no status filter, sorted by ownership, `limit` 1500 holds the whole list; the probe found 1054) |
| `proj_season` (ESPN's preseason total, the fading prior) | the same number: it is static for the season | the universe pull's `projected_total_points` |
| `actual_season` and `games_played` as of week w (`season_pg`) | the sum and count of the player's actuals in periods 1..w-1 | the universe pull's per-period stats (with `filterStatsForCurrentSeasonScoringPeriodId` 0..18 in the filter every player carries every period's `points` and `projected_points`; without it only the pull's own period) |
| Sleeper, FantasyPros, the Vegas line, the wind, the usage read | nothing | ESPN's number alone, as the lineup replay; the blend is scored by the projlog |
| the designation (`P_ZERO`, `weeks_out`) | none; ESPN projects zero for a player it knew was out that week (`row_proj`) | a package or claim touching a player at zero that week is flagged `touches_zero` and the tables print with and without them: the live scan would have priced his return week, the replay prices him as healthy from next week |
| FantasyCalc `values` (the chart: `fairness`, `is_star`, the lowball veto, `name_value_drop`) | none; FantasyCalc keeps no archive | `values={}`: `fairness` returns None, no package is a lowball or asks for a star, `app_grade` still runs on ESPN's numbers. The acceptance score runs on the rest of its signals; the tables say the chart was off |
| `team_meta` (record, ESPN's `trades` and `acquisitions` counters) | the record as of week w from the replay's own scores in weeks 1..w-1; the counters not at all (today's only) | `standings_at(rep, w)`; counters None |
| `playoff_pct` per team (the sim) | the sim on the week-w record, the week-w strengths and the preseason schedule | the replay's later regular-season matchups are the schedule (fixed before the season, so not a leak); `model/sim.py` `simulate` |
| the outcome log's per-rival prior (`history`), `recent_decline` | none | the acceptance score without them |
| `trending` (Sleeper adds) | none | zero for everyone |
| the waiver rank and `waiver_order` | neither is archived | `priority_cost` is not priced; the replay scores `claim_gain` against what the claim bought, not whether the priority was worth spending |

So the replay prices the lineup-delta half of a trade row and the upgrade half of a claim row with the live arithmetic,
and the acceptance half with the chart missing. That is the half that can be graded against points anyway; whether the
rival would have said yes has no truth in a replay (ESPN's `mTransactions2` history does carry the trades rivals made
among themselves, a later step if the acceptance score ever needs grading).

## The replay file, version 2

`pull_replay` adds `players`, the universe: one row per player in the ownership-sorted `kona_player_info` pull (the
whole list, about 1050 players at `limit` 1500: every player rostered in any week plus the wire, the probe below),
keyed by `espn_id`: `name`, `pos`, `team`, `eligible`, `proj_season` (the preseason total), `bye_weeks`, and `weeks`:
`{period: {"proj": x, "actual": y}}` for every period the payload carries (the filter below makes that every period;
a period with a projection and no final yet carries `proj` alone). The matchup rows keep their version-1 shape.
`REPLAY_VERSION` becomes 2 and `load_replay` refuses a version-1 file (re-pull; the box-score half is unchanged, only
the universe is new). JSON strings the `players` and `weeks` keys; `load_replay` turns both back into ints, so
`rep["players"][espn_id]["weeks"][w]` reads as written.

`pull_replay` records `universe_size` and `universe_missing`: how many players on any week's roster are absent from
the universe pull (a player rostered in week 3, cut, and now below the ownership cut-off, or one the list carries
with no `stats` block at all: he has neither a season total nor a period, so he is left out of `players` and
counted). The probe says the list ends before the ownership cut-off bites; a missing player is priced from his
box-score rows alone (this week's `proj` only, no season prior).

Built 2026-10-20 (step 2): `espn.player_universe` is the pull (`UNIVERSE_LIMIT` 1500, `UNIVERSE_PERIODS` 0-18, no
status filter, espn-api `Player` objects so the per-period `stats` parse as everywhere else), `backtest._universe_row`
and `backtest.universe` the rows and the two counts, `pull_replay` calls it once at `league.current_week` after the
box scores. The synthetic replay (`tests/test_backtest.py` `synthetic_replay`) carries a universe: every rostered
player with his box-score week and a draw of the same shape in every other week, plus `WIRE_PER_POS` free agents per
position, everyone with a preseason total. Step 3 may reshape the synthetic rosters (today each team-week draws fresh
players, so a week-w package has no later weeks of its own players to grade) when it needs them to persist.

## The two scorers

### `scan_hits` (`ff backtest --scan`)

For each replayed week w (the regular season only: a package proposed in the playoffs has no weeks to grade) and each
team as `my_id`:

1. Build every roster from the week-w box scores as `PlayerProj` through `projections.blend` with ESPN as the only
   source, as `row_proj` does, but with the rest-of-season inputs: `proj_season` from the universe, `actual_season`
   and `games_played` summed from the universe's periods 1..w-1 (a period with no game, the bye, counts no game; a
   zero on a game week counts a game, as ESPN's `appliedAverage` does), `weeks_remaining` the weeks to the last
   replayed week. `replay_proj(row, universe, w, weeks_remaining)` is that function; `row_proj` stays for the lineup
   scorer.
2. The pool: universe minus everyone rostered in week w, as `PlayerProj` the same way; `replacement_levels` over
   rostered plus pool; `SeasonCtx.build(w, weeks_remaining, reg_season_weeks, None, fas=pool, playoff_weeks=...)`.
3. `scan(my_id, rosters, slots, repl, team_meta, {}, limits=..., roster_max=..., ctx=ctx, playoff_pct=odds,
   reg_season_weeks=...)` with `top` large enough to keep every package the hard rules let through (the live `top`
   10 is a card limit, not a model one; the replay wants the sample). Each candidate keeps `give`, `get`,
   `my_delta_ppw`, `their_delta_ppw`, `p_accept`, and the ids of both sides.
4. Score each candidate against weeks w+1 .. the last replayed regular-season week, two ways:
   - `realized_ppw`: the raw points difference, `score_trade`'s definition (the players I get minus the players I
     give, bench or not, per week), so the live outcome log and the replay are on one scale. With the universe every
     player has an actual every week, so `missing` is a cut player the universe pull did not reach, counted as in
     `trade_hits`.
   - `realized_lineup_ppw`: what `my_delta_ppw` actually forecasts. For each later week t, the week-w roster with and
     without the swap, each seated by the highest-points lineup on that week's `proj` (`lineup.optimize`, objective
     `ev`) and scored with the actuals, the difference averaged. The roster is frozen at week w (the team's later
     moves are not replayed); the leakage rule holds because the seat is chosen on `proj` and scored on `actual`.
5. The tables, over all candidates and over the top 3 per team-week by `p_accept × my_delta_ppw` (the card's
   ranking): n, `hit` rate (sign agreement of `my_delta_ppw` with `realized_lineup_ppw`), the mean predicted against
   the mean realized, and a reliability table by predicted bin (under 1, 1-2, 2-4, over 4 a week) with the realized
   mean and n in each. A bin that promises 3 and realizes 1 is the season pricing reading too much into a week-w
   projection; one that realizes 3 is a forecast worth sending. The same tables split by `touches_zero`.

### `claim_hits` (`ff backtest --claims`)

For each regular-season week w and each team as `my_id`: `rank_free_agents(pool, my_lineup, my_bench, repl,
weeks_remaining, 0, {}, week_lineup=..., lineup_slots=slots)` with `my_lineup` the rest-of-season starters
(`season.starters_ros` per position, as the packet builds it) and `week_lineup` the week-w highest-points lineup. Each
row keeps `delta_over_starter`, `slot`, `delta_week`, `week_slot`, the displaced starter's id (the weakest at `slot`
by `mu_ros`, which `own_starter_value` finds and the replay records).

Scored two ways, matching the two claims the row makes:

- `realized_over_starter`: over weeks w+1 .. the end, the claimed player's actual minus the displaced starter's actual,
  averaged; `hit` is the sign against `delta_over_starter`. The displaced starter is fixed at week w.
- `realized_week`: the week-w actual of the claimed player minus the displaced week starter's week-w actual, against
  `delta_week`, for rows the card would have printed as START NOW (`delta_week` at or over the row's own 1.5 bar).

Tables as for trades: n, hit rate, predicted against realized by bin, over all rows and over the claim-worthy ones
(`delta_over_starter >= CLAIM_WORTHY_PPW`), which are the rows `priority_cost` would price live.

A third table costs nothing and reads the card against the league: the adds the managers actually made between week w
and w+1 (a player on no week-w roster and on one in week w+1) scored the same way. If the card's top claim realizes
more than the managers' actual adds, the wire read has edge; if not, the ranking is the problem, not the wire.

## The synthetic check (what `tests/test_backtest.py` holds it to)

`synthetic_replay` grows a universe: the rostered players plus a wire of a few dozen per position with the same
projection shape, every player with a preseason total and actuals in every week. Three properties:

- Actuals drawn from the projections (the house sigma): the scan's hit rate over packages with `my_delta_ppw` over
  2 reads well above a coin flip and the realized mean tracks the predicted mean within the sampling error of the
  bin; the claim rows likewise.
- Actuals shuffled across players within a position (no information in the projections): hit rate at a coin flip,
  realized means near zero in every bin. A harness that reads edge there is leaking.
- A week-w candidate's inputs never read a week-w or later actual: a test that poisons every actual from week w on
  with a sentinel and checks the priced `my_delta_ppw` and `delta_over_starter` are unchanged.

## Leakage rules (added to the harness's)

- The scan at week w reads: `proj` for week w, actuals for periods under w, the preseason total, the preseason
  schedule, the record as of week w. Never an actual from week w on, never today's roster, designation, ownership or
  waiver status.
- The pool at week w is the universe minus the week-w rosters, never today's free agents (the probe's first question
  is whether ESPN's past-period pool is the week's or today's; the plan assumes today's, as `mRoster` was in D11).
- Scoring reads actuals from week w+1 on (week w itself for `realized_week`), and seats a later week's lineup on that
  week's `proj`, never its `actual`.

## The steps (TODO D12, in order; each one PR)

1. **The probe** (XS, done 2026-10-20): `uv run python scripts/probe_replay_pool.py --league L1 --week <a past
   week>`; its four answers and the pull's shape are under "What the probe found".
2. **The universe pull** (S, done 2026-10-20): `REPLAY_VERSION` 2, `players` in the replay from one `kona_player_info`
   pull at the current period with `limit` 1500 and `filterStatsForCurrentSeasonScoringPeriodId` 0..18 (the probe),
   `universe_size` and `universe_missing` (a player with no `stats` block counts as missing), `load_replay` refusing
   version 1; the synthetic replay grows the universe. The re-pull of the three leagues (`ff replay-pull --season 2026`)
   needs the cookies and is the first thing step 3 does: the version-1 files under `data/replay/` are refused until then.
3. **`scan_hits`** (M): `replay_proj`, `standings_at`, the pool, the sim, the scan per team-week, the two realized
   scores, the tables, `ff backtest --scan`; the three synthetic properties as tests.
4. **`claim_hits`** (S): the claim rows per team-week, the two realized scores, the managers' actual adds, `ff
   backtest --claims`.
5. **The first real tables** (XS, after the pull): `docs/accuracy.md` gets the scan and claim tables for 2026 to
   date, read the way this plan says; what they say about `MUST_TRY_PPW`, `SEND_MIN_PPW` and `CLAIM_WORTHY_PPW` is a
   TODO line each, not a constant change in the same PR.

## What the probe found

Run 2026-10-20 (current week 7) on L1 week 4, L2 week 4, L3 weeks 2 and 4, `--size 1000`; the three leagues and the
two weeks agree on every answer. Beyond the four questions, three scratch reads against L1 settled how the universe
pull is shaped.

1. **The past-period pool is today's.** The FREEAGENT/WAIVERS list for `scoringPeriodId` 4 held 21 (L1), 21 (L2) and
   28 (L3) players who sat on a week-4 box-score roster; week 2 in L3, 32. The pool at week w is the universe minus
   the week-w rosters, as the plan assumed; ESPN keeps no past pool.
2. **The per-period projection is the box score's.** Every rostered player's `projected_points` for period 4 in the
   player list equalled the box score's pre-kickoff number (198/198, 173/173, 167/167, largest gap 0.0), and the
   same number comes back whether the list is pulled at `scoringPeriodId` 4 or 7: the past weeks' projections are
   frozen as of kickoff, so one pull at the current period carries them all. The one miss: a player with no `stats`
   block at all (Tyreek Hill in L1, on a bench all season at 0.0); he is priced from his box-score rows alone and
   counted, as `universe_missing` says.
3. **Coverage.** The deepest rostered player sat at ownership rank 307 (L1 w4), 375 (L2 w4), 261 (L3 w4) and 338
   (L3 w2); a pull of 300 misses 0-2 of them, 600 and 1000 miss none. The ownership-sorted list ends at 1054 players
   in L1 (a `limit` of 1500 returns that many), so the pull takes the whole list: `limit` 1500, nothing to tune.
4. **The past-period payload is today's.** Over the 1000 players both pulls carried, `injuryStatus`, `percentOwned`
   and `onTeamId` differed on none between the `scoringPeriodId` 4 and 7 payloads; the 30 (L1) and 48 (L3 w2)
   rostered-that-week players the past payload puts on another team are all on today's team. The replay keeps
   neither the designation nor the ownership, as planned; the week-w roster comes from the box scores only.

What the scratch reads added, which change the pull and nothing else in the plan:

- **One pull carries every period only with the stats filter.** The plain `kona_player_info` pull carries the pull's
  own period alone (period 4's `proj` and `actual` at `scoringPeriodId` 4; period 7's `proj` at 7). With
  `"filterStatsForCurrentSeasonScoringPeriodId": {"value": [0, 1, ..., 18]}` in the `x-fantasy-filter` players
  block, one pull at the current period carries `proj` for periods 1-18 and `actual` for every played period, and
  period 0 keeps the season rows (leave 0 out and the season total vanishes). `pull_replay` sends that filter.
- **The season projected total is static and is the live `proj_season`.** The season row (`statSplitTypeId` 0,
  `statSourceId` 1, the `projected_total_points` `espn_api` reads) is identical in the `scoringPeriodId` 4 and 7
  pulls on 659/659 players, and it is not the sum of the weekly projections (McCaffrey 223.5 against 344.9 summed):
  a separate preseason figure, the same one `season_pg` fades live. The season actual row carries `appliedAverage`,
  but the replay sums periods 1..w-1 itself, as planned.
- **A zero on a game week has an actual row** (349 rows at exactly 0.0 in period 4); a bye week has none (46 players
  with rows in 4 and 6 and none in 5). Counting actual rows in periods under w as games played is therefore right for
  a bye and counts an inactive game as a game, which is what `appliedAverage` does too.
- The future weeks' projections are real weekly numbers (period 8 differs from period 9 on 392 of 661 players), not
  one figure copied; the scan does not read them (the rest-of-season price comes from `proj_season` and the fade),
  but the file keeps them because they come free.
