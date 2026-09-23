# Plan: what to do with an injured player (hold / IR / drop / trade)

Status: implemented in the same PR, under the recommendation on each open question below. Written 2026-09-23 against
`main` at 72ee11c (75 tests passing); two things moved during the build and are noted under **Deviations** at the end.
Every finding below was re-run in this checkout with a probe script; the container had no ESPN cookies, no
`leagues.toml` and no `data/cache`, so anything that needs a live ESPN pull is marked **needs live pull**.

## The answer in five lines

1. One new number carries the injury into the rest-of-season view: `weeks_out` (expected games missed, counting
   this week). Code derives a default from the ESPN and Sleeper designations; Claude overrides it from the beat
   writers via `overrides.json`. Code never reads prose, Claude never writes a verdict.
2. `mu_ros` becomes availability-weighted: `mu_ros = mu_ros_active * (weeks_remaining - weeks_out) / weeks_remaining`.
   Every existing consumer of `mu_ros` (replacement levels, VORP, waiver deltas, `depth`, `my_assets`, the drop
   candidate, `lineup_strength`) becomes injury-aware without being edited.
3. The `min(p.p_zero, 0.15)` cap in `lineup_strength` goes away; the rest-of-season view uses one flat residual
   sit-risk for everyone, because the injury now lives in `mu_ros`.
4. A new `model/injuries.py` produces one verdict per hurt player, in this order: **IR** if a slot is free and he is
   eligible; **trade** if the scan found a sendable package that ships him; **drop** if the best free agent is worth
   clearly more over the weeks that still matter than he is on return; **hold** otherwise. Weeks are weighted by the
   playoff odds the sim already computes.
5. It surfaces as a new checklist row kind `injury` (id `injury:<player-slug>`), rendered by `report.todos` and
   `email_html` like every other row, and a `drop` or `trade` verdict needs Claude's ruling in `reads.json` the
   way trade rows already do.

## What I checked, and where the handoff was incomplete

All six findings reproduce. Probe output (`PYTHONPATH=. uv run python probe.py`, identical `mu_ros=14`):

| case | weekly ev | trade-math ev |
|---|---|---|
| OUT (`p_zero=1.0`) | 0.0 | 11.9 |
| healthy (`p_zero=0.02`) | 13.72 | 13.72 |

Overrides on an `INJURY_RESERVE` player with `proj_week=12, proj_season=180, weeks_remaining=12`:

| override | `mu` | `p_zero` | `mu_ros` |
|---|---|---|---|
| none | 12.0 | 1.0 | 13.5 |
| `p_zero: 1.0, mu_mult: 0.5` | 6.0 | 1.0 | 13.5 |

So finding 4 is exact: neither lever reaches `mu_ros`. Corrections and additions:

- **Finding 3 (drop candidate) is two-sided.** `_drop_candidate` is a bare `min(mu_ros)` over everyone not in the
  recommended lineup, and that set includes the player sitting in the IR slot. When ESPN zeroes an IR player's
  `proj_season` (the probe shows `proj_week=0, proj_season=0` gives `mu_ros=0`; the comment in `trades.depth`
  says the author has seen exactly that), the IR-slotted player becomes the named drop. That drops a free stash to
  make room for a waiver add, which is the opposite mistake from the one the handoff describes. Which mistake
  happens on a given morning depends on what ESPN put in `proj_season`, which the code does not control.
- **Finding 3, the "too valuable or invisible" split, has the same root.** Whether a hurt player is offerable today
  is decided by ESPN's opaque handling of `proj_season`, not by anything in this repo. The plan removes that
  dependence rather than patching either branch.
- **Finding 5, IR eligibility: the snapshot carries no eligibility flag.** `espn_api.football.Player` exposes
  `injured: bool` and `eligibleSlots`; `espn.py:110` strips `IR` (slot 21) out of `eligible` because it is in
  `NON_STARTER`, and `injured` is never copied into `PlayerRow`. My recollection is that ESPN lists slot 21 in
  `eligibleSlots` for healthy players too, so it is not a usable signal, and ESPN enforces the rule at move time
  from `injuryStatus` (IR always; OUT in most leagues since 2020). **Needs live pull** to confirm; step 0 below.
  Until then the code treats `{INJURY_RESERVE, OUT}` as IR-eligible behind one constant.
- **Upstream cause nobody named: OUT and IR players are never on the research list.** `packet.AMBIGUOUS` is
  `{QUESTIONABLE, DOUBTFUL, PROBABLE}`, so `shared.injury_watchlist` never contains a player who is actually out,
  and the briefing skill (step 3) never asks Claude how long he is out. There is no place today for a return
  timeline to enter the system even if Claude knew it.
- **Waivers compare free agents against the IR stash.** `analyze_league` passes `my_lineup_ros.bench` as
  `my_bench`, which includes IR-slotted players, so `worst_bench` can be the IR guy and every free agent scores
  bench value "over" him. Dropping an IR occupant frees an IR slot, not a bench spot, so he should not be in
  that comparison.
- **Probable pre-existing bug in `mu_ros` itself (needs live pull).** `proj_season` is espn-api's
  `projected_total_points`, which is ESPN's stat period 0 season total. The code names it `season_left` and
  divides by `weeks_remaining`. If ESPN's figure is the full-season number (games already played plus remaining
  projection), which is what I believe it is, `ros_pg` is inflated by `total_weeks / weeks_remaining`: about 13%
  at week 3, 2x by week 10, and worse for a player whose season total is mostly points already banked. Step 0
  settles this in one probe; the fix, if needed, is `(proj_season - points_to_date) / weeks_remaining` with
  `points_to_date` summed from `p.stats[w]["points"]`, which espn-api already carries. It is not part of the
  injury work but every number in this plan sits on top of it.

## Design

### The fields

`PlayerProj` gains four fields, all serialised into the packet by `to_dict`:

| field | meaning | source |
|---|---|---|
| `mu_ros_active` | per-game expectation in the games he plays (today's `mu_ros`, times `ros_mult`) | code |
| `weeks_out` | expected games missed from this week on, float, `>= 0` | designation default, override wins |
| `avail_ros` | `max(weeks_remaining - weeks_out, 0) / weeks_remaining` | code |
| `return_week` | `week + ceil(weeks_out)`, or `None` when that is past the last matchup period | code |

`mu_ros` keeps its name and becomes `mu_ros_active * avail_ros`: "what this roster spot yields per remaining week".
Keeping the name is deliberate. Fourteen call sites read `mu_ros` and every one of them means "rest-of-season
value", so the rename that would be most honest (`mu_ros_avg`) buys nothing but a bigger diff.

### Where `weeks_out` comes from

Default, in `projections.blend`, from the two designations already parsed there:

```python
MULTI_WEEK = {"INJURY_RESERVE": 4, "IR": 4, "PUP": 4, "NA": 1, "DNR": 1, "COV": 1, "SUSPENSION": 1, "SUS": 1}
SLEEPER_ROSTER_MULTI_WEEK = {"Injured Reserve": 4, "Physically Unable to Perform": 4}
weeks_out = max(p0, MULTI_WEEK.get(status, 0), MULTI_WEEK.get(sl_status, 0), SLEEPER_ROSTER_MULTI_WEEK.get(sl_roster, 0))
```

The `p0` term makes the single-week designations fall out for free: Questionable is 0.3 of a game, Doubtful 0.8,
Out 1.0. IR and reserve/PUP are a four-game minimum under NFL rules, so 4 is a floor, not an estimate; a suspension's
length is public and Claude sets it. Sleeper's `roster_status` (`status` in the player dump, already read into
`injury_table` as `roster_status`) is the freshest "he is on NFL IR" signal and is currently ignored.

Override, in `overrides.json`, two new keys next to the existing ones:

```json
{"<espn_id>": {"weeks_out": 6, "ros_mult": 0.9, "p_zero": 1.0, "note": "high ankle sprain, Schefter says 4-6 weeks"}}
{"<espn_id>": {"weeks_out": "season", "note": "torn ACL, placed on IR Tuesday"}}
```

- `weeks_out`: number, or the string `"season"` (code maps it to `weeks_remaining`). Wins over the default.
- `ros_mult`: multiplies `mu_ros_active` only (a player coming back from a hamstring at 85%, or a role change that
  is a rest-of-season statement). Default 1.0.
- `mu_mult` keeps today's meaning, this week only. `p_zero` keeps today's meaning, this week only; an override
  of `p_zero: 1.0` with no `weeks_out` implies `weeks_out = 1` through the `max(p0, ...)` above, which is what
  "ruled out" has always meant.

This is the "fix the override ordering" item from the handoff, done explicitly instead of by reordering. Moving
the override block above the `mu_ros` line would leak half of `mu_mult` into `mu_ros` through the
`0.5 * ros_pg + 0.5 * mu` blend, and nobody writing `mu_mult: 0.7` for "limited snaps in his first game back"
wants that to shave the rest of his season. Two levers with two meanings beats one lever with a side effect.

Timelines are not persisted. The cloud VM clones fresh, so an ACL in week 3 has to be re-stated every morning for
fourteen weeks. That is fine: the research list (below) is a handful of names, Sleeper's `injury_notes` usually
says "expected to miss the season" in so many words, and the skill tells Claude to skip the search when the note
already answers it. A ledger on the `projlog` branch was considered and rejected: it is state Claude would own,
which the boundary rule forbids, and a stale ledger is worse than a fresh default of 4.

### The rest-of-season view

`PlayerProj.ros()` keeps its `p_zero=0.05` default. `lineup_strength` changes from
`p.ros(min(p.p_zero, 0.15) if not (p.bye or p.locked) else 0.05)` to `p.ros()` for everyone. The 0.15 cap was
standing in for the missing injury term; with the injury in `mu_ros` it only double-counts. `needs()` already
calls plain `p.ros()`, so the two functions stop disagreeing about what rest-of-season means. Locked and bye
players are unaffected: `ros()` already clears both flags.

The residual 0.05 still applies to this week for a Questionable player whose `weeks_out` is 0.3, a double count of
about 0.3 × 0.05 of one game. Not worth a special case.

### Market values for a hurt player in the trade scan

With `mu_ros` weighted, `scan` finds "ship the hurt guy" packages on its own: shipping a 15-point RB who is out 4
of 12 weeks (`mu_ros` 10) for a healthy 12-point RB is `d_me` +2 and clears the 0.75 gate. What then kills the
candidate is the market check, because FantasyCalc still prices him at 15-point value: the `gv > rv * 2.2`
prefilter drops the package as absurd, and if it survives, `ratio < MARKET_FLOOR` marks it not sendable with
"market says I give more". The lag works against the seller here, not for him.

This is the judgment call the handoff asked to be flagged rather than picked. The options:

- **Trust the market as-is (conservative).** The scan proposes nothing until FantasyCalc reprices, days after the
  injury. Sell-before-the-reprice never appears in the email.
- **Discount the give side by availability (recommended).** For the prefilter and the `sendable` ratio, use
  `gv_eff = gv * max(avail_ros, 0.25)` for any give-side player with `weeks_out >= 1`; carry the raw `gv` in the row
  and add a `why` entry: `"market still prices {name} healthy ({gv}); he is out ~{weeks_out} wks"`. The row reaches
  the card, the caveat rides on it (the `warn` mechanism already exists), and Claude's mandatory ruling on every
  trade row decides whether this rival will bite. Cost of being wrong: one declined offer. Cost of the conservative
  option being wrong: the window closes unseen.
- **Use `trend_30d` to detect repricing** and skip the discount when the market already moved. Rejected for now:
  30-day trend is noisy and a lag detector built on it would need its own tuning. Revisit if the discount
  double-counts in practice.

The floor of 0.25 stops a season-ender from reading as free: a rival will not take him at any price in redraft, and
`my_assets` excludes him anyway once `mu_ros` is 0.

## The decision rule (`model/injuries.py`)

One function, `decide(p, roster, slots, lg_settings, week, waivers, trades, odds_me, ir_state) -> dict`, run for
each of my rostered players with `weeks_out >= 1` (or `slot == "IR"`), and a wrapper `injury_rows(...)` that
returns the list the packet carries. Nothing here reads prose.

### Week weights

```
w(t) = 1.0                     t in the regular season
w(t) = playoff_pct / 100       t in playoff_weeks
W_eff    = sum of w(t) over remaining weeks
back_eff = sum of w(t) over weeks >= return_week      (0 when return_week is None)
```

`playoff_pct` is my number from the sim already in `lg["odds"]`. `reg_season_weeks` needs adding to the packet's
per-league `settings` subset (it is in `LeagueSettings` but not copied into the block). This is what makes a
four-week injury in week 3 different from the same injury in week 11, and different again for a 9-2 team versus a
3-8 one: the 9-2 team's playoff weeks count almost fully, so a week-15 return is still worth holding for.

### Values

```
hold_ppw   = own_starter_value(p at mu_ros_active, ros_lineup_of_roster_without_p) floored at 0
             + DEPTH_WEIGHT * max(mu_ros_active - replacement[pos], 0)
hold_value = hold_ppw * back_eff
fa         = best non-streamer in lg["waivers"] eligible for a slot p could fill (else best overall), by the same value
drop_value = (max(fa.delta_over_starter, 0) + DEPTH_WEIGHT * max(fa.vorp, 0)) * W_eff
```

Both are marginal points over the lineup I would field without him plus depth value over the wire, over the same
weighted weeks, so they are comparable. `own_starter_value` and `rank_free_agents` already exist and are reused.

*Revision (first live run).* The first cut measured both sides against the starting lineup only. On a full roster
neither a hurt backup nor the best free agent starts, so every row read "0 vs 0, hold" and the drop verdict was
unreachable short of a season-ender. Two fixes: the `DEPTH_WEIGHT` term above (a quarter of the margin over
replacement level, the same idea `rank_free_agents` uses for bench value), and a dead-roster-spot rule: a player who
is out for the season, back only for weeks that no longer count, or below replacement when he is back is a drop
whether or not the wire has anyone, if he is the cheapest cut. The IR slot also went to the first hurt player by
value instead of the longest absence, so a one-week Out could take it from a four-week IR player; stashes now need
`IR_MIN_WEEKS` (2) and the open slots go to the highest `hold_value`. And `blend` was averaging the healthy per-game
number with this week's ~0 projection for anyone listed Out, halving it; this week now only counts when he is
expected to play it. Second revision: an IR move or a drop frees a bench spot, and the row now always names who
fills it (`fill_spot`): a pickup who starts or beats replacement, else a free-agent handcuff for one of my RB1s,
else the best body on the wire by the waiver score, labelled depth only. Below the wire is the bar for cutting a
player, not for leaving a slot empty.

### Verdict

Evaluated in this order; the first match wins:

1. **`ir`** when an IR slot is open (`ir_slots` minus roster players with `slot == "IR"`) and he is IR-eligible
   (`IR_ELIGIBLE = {"INJURY_RESERVE", "OUT"}` on ESPN status, or Sleeper roster status on NFL IR). Text: move him to
   IR, and if a waiver row exists, the pickup fits on the freed bench spot. When the slot is occupied by a player
   with `hold_value` below his, the verdict is still `ir`, with text saying who to swap out.
   If he is already in the IR slot: no row unless `return_week <= week + 1`, in which case the row is
   `activate`: he is back, the IR slot has to be cleared, and `_drop_candidate` names the corresponding drop.
2. **`trade`** when `lg["trades"]` holds a sendable candidate whose `give` includes him. Text names the package
   and points at the trade row id; hold is stated as the fallback.
3. **`drop`** when `drop_value - hold_value >= max(DROP_MARGIN, DROP_RATIO * hold_value)` with
   `DROP_MARGIN = 3.0` season points and `DROP_RATIO = 0.25`, and he is the cheapest drop on the roster
   (`_drop_candidate`, which after step 5 excludes the IR slot and uses the weighted `mu_ros`). A season-ender with
   no IR slot has `hold_value = 0` and drops for the first free agent worth anything. A hurt player who is not the
   cheapest drop gets `hold`, and the waiver row names whoever is.
4. **`hold`** otherwise, with the numbers in the text: back week N for M games at about X/game, best free agent
   adds Y/week, hold.

The margin is asymmetric on purpose. A drop is final and a rival can claim him; a hold is re-evaluated tomorrow.
Both constants are tunable and named in the open questions.

### Worked examples (17 matchup periods, playoffs 15-17, my playoff odds 60%)

| week | player | `weeks_out` | `back_eff` / `W_eff` | `hold_ppw` | `hold_value` | best FA | `drop_value` | IR slot | verdict |
|---|---|---|---|---|---|---|---|---|---|
| 3 | RB1, 15/g, ACL | season | 0 / 13.8 | 3.0 | 0 | +1.5/wk | 20.7 | open | `ir` |
| 3 | RB1, 15/g, ACL | season | 0 / 13.8 | 3.0 | 0 | +1.5/wk | 20.7 | none | `drop` |
| 3 | WR2, 12/g, high ankle | 4 | 9.8 / 13.8 | 3.0 | 29.4 | +1.0/wk | 13.8 | none | `hold` |
| 11 | TE1, 9/g, 4 wks, odds 20% | 4 | 0.6 / 4.6 | 4.0 | 2.4 | +0.8/wk | 3.7 | none | `hold` (margin not met) |
| 11 | TE1, same, odds 20% | 4 | 0.6 / 4.6 | 4.0 | 2.4 | +2.0/wk | 9.2 | none | `drop` |
| 11 | TE1, same, odds 90% | 4 | 2.7 / 6.7 | 4.0 | 10.8 | +2.0/wk | 13.4 | none | `hold` (gap 2.6, margin 2.7) |

The last two rows are the point of the weighting: same injury, same week, same free agent, and contention flips it.

## Changes, in order

Each step leaves `uv run ruff check . && uv run pytest && uv run ff briefing --demo` green (that is CI) and is
a separate commit. Steps 1 and 2 are the bug fixes and stand on their own; 3 onward is the feature.

### Step 0. Live-pull probe (Dustin, locally, before step 1 is merged)

`scripts/probe_injuries.py`, read-only: for every rostered player with any designation, print ESPN
`injuryStatus`, `injured`, whether raw `eligibleSlots` contains 21, `lineupSlot`, `proj_week`, `proj_season`,
sum of `stats[w].points` for played weeks and sum of `stats[w].projected_points` for remaining weeks; for two
healthy players print the same. Answers three things this plan assumes: whether `eligibleSlots` carries IR
eligibility, what ESPN does to `proj_season` on IR, and whether `proj_season` is full-season or remaining.
Also add `injured` and `ir_eligible_raw` (`"IR" in eligibleSlots` before the strip) to `PlayerRow` so the next
snapshot keeps the evidence.

### Step 1. `projections.py`: `weeks_out`, `ros_mult`, weighted `mu_ros`

- Tables `MULTI_WEEK` and `SLEEPER_ROSTER_MULTI_WEEK`; `blend` reads `sleeper["roster_status"]`.
- New `PlayerProj` fields with defaults (`weeks_out=0.0`, `avail_ros=1.0`, `mu_ros_active=None` filled from
  `mu_ros` in `__post_init__` so `tests/conftest.P` and every existing constructor keep working).
- Override keys `weeks_out` (number or `"season"`) and `ros_mult`; `flags` gain `llm:weeks_out` / `llm:ros`.
- `mu_ros = round(mu_ros_active * avail_ros, 2)`; `return_week` computed from `week` (new `blend` argument,
  passed by `packet._projs`, defaulting to `None` so the signature stays compatible).
- `ros()` unchanged.

Tests (`tests/test_projections.py`, new file):
- an IR designation with no override gives `weeks_out == 4` and `mu_ros == mu_ros_active * (W - 4) / W`;
- Sleeper roster status "Injured Reserve" alone does the same;
- `weeks_out: "season"` gives `mu_ros == 0` and `return_week is None`; `weeks_out` beyond `W` clamps the same way;
- `p_zero: 1.0` alone gives `weeks_out == 1`;
- `ros_mult: 0.8` scales `mu_ros_active` and `mu_ros`, leaves `mu` alone; `mu_mult` scales `mu`, leaves both
  `mu_ros` fields alone (this is the regression test for finding 4);
- Questionable gives `weeks_out == 0.3` and `avail_ros` just under 1.

### Step 2. `trades.py`: drop the cap, discount the give side

- `lineup_strength`: `p.ros()` for all. The 87% probe becomes a test: an OUT-this-week player with
  `weeks_out=1, W=12` scores `11/12` of healthy in `lineup_strength`; a `weeks_out="season"` player scores 0.
- `scan`: `gv_eff` as above for give-side players with `weeks_out >= 1`; new `why` entry; row carries
  `market_give` raw and `market_give_eff`.
- `depth` and `my_assets` unchanged; they now mean what their comments say.

Tests (`tests/test_trades.py`):
- `test_trade_math_sees_a_season_ender`: identical `mu_ros_active`, one with `weeks_out="season"`; the hurt one
  adds nothing to `lineup_strength`;
- `test_scan_offers_a_hurt_starter_for_a_healthy_lesser_one`: my RB1 out 4 of 12, rival has a healthy 12-point
  RB and an RB hole, FantasyCalc still values mine at 2x; the package is produced and `sendable`, with the
  market caveat in `why`;
- `test_scan_never_offers_a_season_ender`: `my_assets` excludes him.
- Existing 16 trade tests must pass unchanged; `test_an_out_for_the_season_body_is_not_a_backup` already
  constructs the `ros=0.0` case and keeps working.

### Step 3. `packet.py` and `waivers.py`: IR-aware bench, the research list

- `my_bench` passed to `rank_free_agents` excludes `slot == "IR"`.
- `shared.injured`: one entry per rostered player of mine with `weeks_out >= 1` or `slot == "IR"`:
  `{name, pos, team, league, espn_id, espn_status, sleeper_status, sleeper_roster_status, body_part, notes,
  weeks_out, weeks_out_source: "default"|"override", return_week, slot, override_note}`. `injury_watchlist` is
  left exactly as it is (Q/D/P, this week's sit risk).
- Block `settings` gains `reg_season_weeks`, `ir_slots`, `bench_slots`.
- `PACKET_VERSION` 5.

Tests: `test_packet_synthetic` asserts the new keys exist on the block and that a demo player given
`weeks_out: "season"` via overrides lands in `shared.injured` with `weeks_out_source == "override"`;
`test_waivers` gets a case where the IR occupant is not `worst_bench`.

### Step 4. `model/injuries.py`: the rule

As specified above; `injury_rows(lg_inputs) -> list[dict]` called from `analyze_league` after waivers and trades
(it consumes both), stored as `lg["injuries"]`, sorted by `mu_ros_active` descending. Each entry:
`{espn_id, name, pos, slot, weeks_out, return_week, avail_ros, mu_ros_active, hold_ppw, hold_value, drop_value,
back_eff, w_eff, ir_eligible, ir_open, ir_occupant, best_fa: {name, pos, delta_over_starter} | None,
trade_ids: [...], market: {redraft_value, trend_30d} | None, verdict, why: [...]}`.

Tests (`tests/test_injuries.py`, pure functions, fixtures from `conftest.P`):
- the six worked-example rows above, each as a test with the numbers asserted to a decimal;
- IR slot occupied by a lower-value stash gives `ir` with the swap named;
- already on IR and `return_week == week + 1` gives `activate`;
- not the cheapest drop gives `hold` even when `drop_value` is large;
- a sendable scan candidate shipping him gives `trade` and carries the trade row id.

### Step 5. `report.py`: the row, the drop candidate, lint, watch

- `_drop_candidate`: exclude `slot == "IR"`; keep `min(mu_ros)` (now injury-aware). Its docstring finally
  matches its body.
- `todos`: new kind `injury`, id `injury:<slug(name)>`, label `Hurt (IR)` / `Hurt (hold)` / `Hurt (drop)` /
  `Hurt (trade)` / `Back (activate)`, placed after `cover` and before `lineup`. Text patterns:
  - ir: `"{name} ({pos}) is out ~{n} wks (back wk {r}); move him to IR{, then add {fa} on the freed spot}"`
  - hold: `"{name} ({pos}) is out ~{n} wks, back wk {r} for {m} games at ~{x}/g; best FA adds +{y}/wk, hold him"`
  - drop: `"{name} ({pos}) is out ~{n} wks and worth ~{h} pts the rest of the way; drop him for {fa} (+{y}/wk)"`
  - trade: `"{name} ({pos}) is out ~{n} wks; the offer below ships him ({trade id}), else hold"`
  `n` prints as `"the season"` when `return_week` is None. The drop text and the waiver row's `; drop {drop}` must
  agree, which they do by construction once both read the same `_drop_candidate`.
- `read_lint`: an `injury` row whose verdict is `drop` or `trade` with no ruling is an error, same wording as the
  trade rule. `activate` and `hold` need no ruling.
- `watchlist` / `watch_line`: `shared.injured` rows join the Watch line as `"{name} Out ~{n} wks ({leagues})"`
  with the override note, so the across-leagues card shows timelines, not just game-time decisions.
- `render_detail` roster table: flags column gains `out ~{n}w, back wk {r}`.
- `AI_TELLS` and `voice_lint` unchanged.

Tests (`tests/test_card.py`): row ids and labels for each verdict; the IR occupant is never the drop candidate;
lint wants a ruling on a `drop` row and not on a `hold` row; a `skip` ruling strikes the row like any other.

### Step 6. `email_html.py`

- `LABELS["injury"] = ("HURT", "warn")`, with the verdict badge text `IR` / `HOLD` / `DROP` / `TRADE` /
  `ACTIVATE` chosen in `_todo_rows` the way trade rows pick `TRADE (reach)`; tone `bad` for drop, `info` for ir
  and activate, `warn` for hold and trade.
- `_status_cell`: append `back wk {r}` (or `season`) when `weeks_out >= 1`.
- No layout change; `test_email_html.test_render_email` gets one assertion that the badge and text render.

### Step 7. `demo.py` and the README images

- The synthetic league gets one player on IR with `proj_week=0` and one OUT starter, so `ff briefing --demo`
  shows an `injury` row and `test_demo` can assert it. `scripts/screenshots.sh` regenerates `examples/`.

### Step 8. Docs and the skill

- `.claude/skills/briefing/SKILL.md` step 3: research every entry in `shared.injured` for a return timeline
  (team statement, beat writer), skipping the search when `notes` already states it; step 4: the two new
  override keys, with the guide "IR 4 unless reported longer; 'season' for ACL/Achilles/season-ending surgery;
  suspension = games announced; ros_mult only for a changed role or a diminished return".
- `CLAUDE.md` step 4 schema line and the failure-modes table (new row: "email says hold a player who is done
  for the year" → `weeks_out` missing from overrides; check `shared.injured` in the packet).
- `README.md` override example gains a `weeks_out` line.
- `ROADMAP.md`: an entry under "where the edge is today".

Estimated size: steps 1-2 about 60 lines of source plus tests; step 4 about 120; steps 3, 5, 6 about 100
together. Two or three sessions.

## Open questions for Dustin

Each has a recommendation so the work can start under it; the answer changes the code in the place named.

1. **IR eligibility in your three leagues.** ESPN's default lets `IR` and `OUT` designations into the IR slot; a
   league can be set to IR only. The snapshot cannot tell (see finding 5). Recommendation: assume both, one
   constant `IR_ELIGIBLE` in `injuries.py`, and run the step 0 probe once to see whether `eligibleSlots` carries
   a real signal. If it does, the constant goes away.
2. **Market lag: feature or trap.** Recommendation: discount the give side and label the row (option two above).
   The alternative is that the scan proposes nothing until FantasyCalc catches up.
3. **`mu_mult` semantics.** Recommendation: leave it this-week only and add `ros_mult`, rather than reorder the
   override block and let half of it leak into the season. Overrides written so far keep meaning what they meant.
4. **Timelines are not persisted; Claude re-states `weeks_out` daily.** Recommendation: accept, and lean on
   Sleeper's `notes`. The alternative (a ledger on the `projlog` branch) puts state on Claude's side of the line.
5. **The drop margin (3 season points or 25% of hold value, whichever is larger) and the playoff weighting (flat
   `playoff_pct` per playoff week).** Recommendation: ship these, watch two weeks of cards, tune. The worked
   examples are the calibration set.
6. **Should a `drop` verdict require your explicit ruling in `reads.json`, like trade rows?** Recommendation:
   yes, because it is the one irreversible move the card can suggest and its single largest input (`weeks_out`)
   is Claude's research.
7. **The `proj_season` question.** If the step 0 probe shows ESPN's number is full-season, do you want that fixed
   in this PR (it changes every ROS number, so trade and waiver output shifts for everyone) or in a separate one
   first? Recommendation: separate, first, because this plan's tests assert ROS numbers.

## Not in scope

- Any ESPN write. The row tells Dustin what to tap.
- A general sell-high model. `usage.signals` keeps its TD-dependence flag; the trade verdict here is only "the
  scan found a taker".
- Waiver-priority strategy (roadmap item 7); the drop path assumes the pickup itself is already justified by
  `rank_free_agents`.
- Handcuff logic. When my RB1 is hurt his backup's own projection already rises at the source, so the backup
  surfaces through the normal waiver ranking.

## Deviations from the plan as built

- **A one-game `hold` is not a row.** A bench player out this week and worth keeping produced "hold him" rows that
  were just the injury report; `report._injury_items` skips `hold` when `weeks_out < 2`. He still appears in
  `shared.injured` and on the across-leagues Out line, and `ir` / `drop` / `trade` / `activate` show at any length.
- **The market discount is `max(avail_ros, 0.25)` on the give side only**, applied in both `scan` and `evaluate`
  (an offer that takes a hurt player off my hands should not read as a lowball either). The scan still keeps one
  package per rival `get`, so a healthy player who fits the same ask outranks the hurt one; the sell only surfaces
  when the hurt player is the piece that fits, which is the honest answer.
- **`ros_mult` instead of reordering** the override block, as recommended; `mu_mult` is unchanged.
- **The `proj_season` question is untouched** (open question 7) and `scripts/probe_injuries.py` is the live pull that
  settles it and the IR-eligibility signal; `PlayerRow` now keeps `injured` and `ir_eligible_raw` so the next
  snapshot carries the evidence.
- Step 7's README screenshots were not regenerated here (`scripts/screenshots.sh` needs a browser); the demo league
  does carry an IR stash and an Out player so `ff briefing --demo` shows the row.
