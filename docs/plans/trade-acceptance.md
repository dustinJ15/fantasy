# Plan: trades a rival would actually accept

Status: implemented 2026-10-07 in three PRs (#10 stop the bleeding, #11 the model, #12 learning), 188 tests passing;
see **Deviations** at the end for what moved during the build. Written the same morning against `main` at 24ae9a8
(164 tests passing). The container
had no ESPN cookies, so the two rows from this morning's email were reconstructed from the projlog branch
(`pushed_trades.json`, `skipped_trades.json`, the week 5 projection log) and live FantasyCalc values pulled today.
Anything that needs a live ESPN pull is marked **needs live pull**.

## The answer in six lines

1. The scanner is a lineup-delta search with a market guard bolted on. It never asks the one question that decides
   a trade: *would this manager say yes?* It should be an acceptance model first and a lineup search second.
2. Package value is summed linearly on a convex scale, so two WR2s "equal" the WR3 overall. Nobody who owns Ja'Marr
   Chase has ever agreed with that sum. Strip throw-ins, tax the side sending more bodies the way every published
   chart does (10% on a 2-for-1), and refuse to ask for the best player in the deal without a visible overpay.
3. The rival's roster after the trade is never depth-checked, his hurt and IR bodies count as lineup cover at an
   availability-weighted average, and his free-agent fallback is ignored. That is how a one-QB team got asked for its
   QB "because they're set at QB".
4. The consolidation bonus rewards the wrong side: it adds +0.5 when *I* get the best player in a 2-for-1 and labels it
   "consolidates value for them". That is the exact shape of every laughed-at offer, and it is the shape that the
   `must_try` push then nags about every morning.
5. Rank candidates by `p_accept × my_gain`, not by a rival's lineup delta computed with my projections. Show the card
   what the rival is left with (so the paste prose cannot say "you're set at QB" to a man with one QB), cap the card at
   two offers, and never print a "reach".
6. Log every offer Dustin sends and what ESPN did with it. Nineteen skips in fourteen days is the only acceptance data
   this repo has today; the outcome log is the calibration set for the model above.

## What the two screenshots show, by the numbers

**Row 2, L3: Montgomery for Dak Prescott, "+1.6 for you, +0.3 for them".** FantasyCalc redraft (10-team 1QB PPR,
2026-10-07): Montgomery 1687 (RB24), Prescott 1606 (QB7). The market check sees a dead-even swap. The lineup check saw
+0.3 for Hawk Tua, which is only possible if the math found a second QB on his roster: `depth()` is applied to my
roster only (`trades.py:238`), and `_lineup()` on `ros()` copies values an IR or Out QB at `mu_ros_active × avail_ros`
as if he played every week (a QB out until week 9 on a 55% availability reads as a 12-point weekly starter). So the
scan priced "Dak leaves" as a 5-point hit covered by a body that cannot play, Montgomery filled his flex, net +0.3.
Then `needs()` called that same body "surplus" or at least "no hole", and the paste text, written from
`rival_needs`, told him he was set at QB. **Needs live pull** to confirm which QB that was; the fix is the same either
way (section 3.3).

**Row 4, L2: McMillan + Parker Washington for Ja'Marr Chase, "+3.1 for you, +1.3 for them", pushed as DO IT.**
Chase 8118 (WR3 overall), McMillan 3946 (WR12), Washington 2968 (WR19). Every guard passes:

| guard | rule | this package |
|---|---|---|
| market prefilter | `rv <= 1.2 × gv` | 8118 / 6914 = 1.17 |
| throw-in | piece < 25% of what they give | Washington = 37% |
| lowball floor | `ratio >= 0.8` | 1.17 |
| consolidation | +0.5 when `rv >= max(give)` | 8118 ≥ 3946, so +0.5 and "consolidates value for them" |
| `must_try` | sendable and `d_me >= 2.0` | 3.1, so it is pushed every morning until skipped |

FantasyCalc's own curve explains why no human sees 1.17 as fair: overall rank 8 is 8118, rank 20 is 5483, rank 30 is
3611, rank 50 is 2536. The scale is convex because the market is convex: a starter you cannot replace is worth more
than the sum of two you can. Summing it linearly throws that information away.

**The pattern is structural, not two bad mornings.** `skipped_trades.json` on the projlog branch holds 19 skips since
2026-09-23. Seventeen are 2-for-1 asks for a top-30 player (Josh Allen twice, Nacua, St. Brown, McCaffrey, Henry,
Gibbs, Chase Brown twice, JSN, Jeanty, Nico Collins, DeVonta Smith, Zay Flowers, Purdy, Lawrence, Javonte). Four of the
five packages the math pushed as `must_try` are the same shape. The generator produces them because
`their_assets[:5]` for the 2-for-1 loop is literally their five best players, and every guard is tuned to let a 1.2x
star ask through.

## What wins leagues, and what people bite on

Redraft trades are positive-sum in exactly four ways, and an offer only gets accepted when the rival can see one of
them from his side:

1. **Slot arbitrage.** A player who starts for them and sits for me (or the reverse). The lineup delta already measures
   this, but only from my projections. The rival measures it with ESPN's projections and his own rankings.
2. **Positional scarcity between two rosters.** My third RB is worth more to a team starting a waiver RB than he is to
   me. `needs()` finds "holes" only below replacement, which in a 1-QB league almost never fires, so the scan rarely
   targets the slot they are actually weak at.
3. **Time.** Byes, injuries with a return date, and the playoff schedule. A contender can afford to buy a hurt star
   at an injury discount; a team at 15% playoff odds cannot. The sim already knows every team's odds; the scan uses
   the record only to append "rival is losing (motivated)".
4. **Price disagreement.** The real edge: players the market prices above my projection are my chips, players it prices
   below are my targets. The scan uses the market only as a guard and never as a source of candidates.

What makes a manager say yes, from the research in `docs/research/trade-acceptance.md` (sources cited there; the
numbers are analysts' published rules, nobody has measured acceptance rates by offer shape) and from every rival in
these three leagues so far:

- **The base rate is tiny.** The one analyst who reports his own number says about one offer in thirty is accepted.
  So an offer generator's job is to spend credibility carefully, not to find +0.75 ppw.
- **The best player in the deal.** "Nine times out of ten the owner getting the best player wins the trade"; "don't
  take a 2-for-1 unless you're getting the 1". The side receiving the single best player is assumed to win. A 2-for-1
  where I get the best player needs an overpay the rival can see at a glance, and even then it is a hard sell on a
  full roster (he has to cut a body). A 2-for-1 where *he* gets the best player and I take two starters is the version
  people accept.
- **The consolidation tax has published numbers.** PFF's redraft chart: the side giving more players pays 5–10% over
  the stud's value. CBS's Heath Cummings: 10% on a 2-for-1, 25% on a 3-for-1. Draft Sharks and KeepTradeCut both
  strip throw-ins first, then tax. A 1-for-1 is read as fair inside about 5%.
- **What the rival actually sees is ESPN's trade grade.** ESPN grades each incoming player against the average of
  the players at that position already on *his* roster, from ESPN's projections, ownership and start percentage. A
  player below his positional average grades badly whatever my `mu_ros` says. The snapshot already carries ESPN's
  `proj_season`, `pos_rank` and `percent_owned` for every rostered player, so the scan can score an offer the way
  his app will.
- **His weakest starting slot.** He accepts when the incoming piece starts for him this week. A piece that rides his
  bench is "depth", and depth is what people decline.
- **What he is left with.** He will not trade his only QB, TE, K or D/ST starter unless the replacement is on the
  wire and obvious. He will not take two players onto a full bench. He will not trade a player he is starting today for
  one he would bench.
- **Fairness on a chart he can check.** ESPN's trade analyzer, FantasyCalc, FantasyPros: he will run the offer through
  one of them, and he will read a 1.17 against him as a lowball because the chart is convex and his own player is
  the one on the steep part of the curve.
- **Endowment.** He values his own players above the chart (the lab number is willingness-to-accept at roughly twice
  willingness-to-pay, and the effect is documented in real NFL draft-pick trades). Every acceptance heuristic in
  print says offer slightly more than fair, then let him counter down; the anchoring advice is to open at 75–90% of
  what I would walk away at, with a sweetener ready.
- **QBs in a 1-QB league.** Cheap on every chart (Dak is QB7 at 1606, the price of an RB24) because the wire has
  five of them, which is exactly why a manager with one QB will not sell his: the chart says he gets nothing back
  and the wire says he starts a backup. Ask for a QB only from a roster with two startable ones.
- **Who trades.** Active traders accept trades; bottom-third teams sell studs for depth; contenders buy depth, not
  consolidation; a team that just lost a star or has a bye crunch is the one that takes a 2-for-1.
- **Repeated game.** These are coworkers. Three lowballs in a week and the fourth offer is not read.

## Design

### 3.1 Package value: strip throw-ins, then tax the side sending more bodies (`model/trades.py`)

Replace the `rv <= 1.2 × gv` prefilter and the `ratio` on the row with a fairness test the rival can reproduce on
any chart he opens:

```python
CONSOLIDATION_TAX = {1: 0.0, 2: 0.10, 3: 0.25}   # PFF redraft chart, Cummings/CBS: the side giving more players pays this
FAIR_BAND = 0.05                                 # a 1-for-1 reads as even inside 5%

def fair_from_his_side(give, get, values) -> float:
    """What he receives over what he gives, on the market chart, after the pieces he would neither start nor price are
    stripped and the consolidation tax is applied to whichever side sends more bodies. 1.0 is even; below 0.95 he
    reads it as a lowball; a star ask needs more than 1.0 (3.2)."""
    recv = market_value(strip_throw_ins(give), values, discount_injured=True)
    gives = market_value(get, values)
    tax = CONSOLIDATION_TAX.get(len(give), 0.25) if len(give) > len(get) else 0.0
    return recv / (gives * (1 + tax)) if gives else None
```

`evaluate()` applies the same function from my side for incoming offers. `MARKET_FLOOR` (0.8) stays as the floor on
what I give. Chase, re-run: 6914 / (8118 × 1.10) = 0.77, a lowball by the chart he will check. Dak, re-run: 1687 /
1606 = 1.05, even, which is the point: the market check was never going to catch that one, 3.3 does.

The alternative is a convex package value (best piece at full value, the rest at ~0.6), which lands in the same
place for Chase (8118 against 3946 + 0.6 × 2968 = 5727, ratio 0.71). The tax is preferred because it is a published
convention a rival can be pointed at; open question 2 keeps the other.

### 3.2 The best-player rule and the star guard

In `scan()`, after the swap:

- `best_side`: which roster owns the single highest-value piece in the deal. When it is theirs and the package is not a
  1-for-1 inside the fair band, the candidate is a **star ask** and needs `fair_from_his_side >= 1.0` after the tax
  (he gets at least what he gives on his own chart) plus a positional-need match (3.4). Without both it is dropped,
  not scored.
- **Top-of-market guard:** never ask for a player in the top 12 overall or top 3 at his position (FantasyCalc
  `overall_rank`, `pos_rank`) unless the best piece I give is also top 24 overall, and then only at
  `fair_from_his_side >= 1.10` (the endowment premium on a star, on top of the tax). The row explains the one
  exception it allows ("you give the better player, he consolidates").
- **QB rule (1-QB leagues):** ask for a QB only from a roster with two QBs who could start (healthy, `mu_ros_active`
  above the position's replacement level), and never send a top-24 piece for one.
- **Delete the consolidation bonus** (`consol`). What it computes is "I get the best player", and it adds half a point of
  score to the shape every rival rejects. If a 2-for-1 bonus is wanted, the right one is +0.5 when the single player
  *he* receives is the best in the deal (I de-consolidate into two starters), and 0 otherwise.

### 3.3 What each side is left with: per-week value with the wire as the fallback body

Replace `lineup_strength()` / `_lineup()` on `ros()` copies with a per-week sum. For each remaining matchup week `t`:

- a player contributes `mu_ros_active` if `t >= return_week` (or he is not out) and `t` is not his bye, else 0;
- the lineup is the EV-greedy assignment for that week (a new `fast_lineup_mu()`: sort eligible by EV, fill fixed
  slots then flex; the exact `optimize()` stays for the final top 10 so nothing the card prints is greedy);
- the empty slot a trade opens is filled by the best free agent at that position from the snapshot's `free_agents`
  (one per position, precomputed; for the rival as well as for me, because he can pick up the same QB I can);
- weeks are weighted by `injuries.week_weights()` (1.0 in the regular season, the team's playoff odds after), so a
  week-15 return is worth what it is worth to that team.

`d_me` and `d_them` become the weighted per-week sum divided by the weight total, so they stay in points per week and
nothing downstream changes units. This one change fixes the IR-body-as-cover bug, prices byes, prices injury returns,
and makes "he only has one QB" show up as the cost of the best QB on the wire. Depth is then checked on **both**
rosters (`depth(new_theirs)`), and a trade that leaves him without a healthy starter at a `NO_FLEX_COVER` position
and nobody startable on the wire is dropped.

Cost: the scan is ~325 packages per rival. At 9 rivals and 9 weeks that is ~53k greedy lineups per side, each a sort
over ~15 players. Well under the 3-5 minutes the packet already takes; the sim dominates.

### 3.4 The acceptance scorecard (`model/acceptance.py`, new)

A transparent score, not a classifier. `p_accept(package) -> (p, reasons)` starts at a base and multiplies by a
factor per term, each with a one-line reason the row can print. Terms, with starting values to calibrate in 3.7:

| term | signal | factor |
|---|---|---|
| chart fairness, his side | `fair_from_his_side` (3.1) | < 0.9: 0.2; 0.9–0.95: 0.6; 0.95–1.15: 1.0; > 1.15: 1.1 |
| best player | he receives the best piece | 1.3; I receive it: 0.5 |
| his app's grade | incoming piece vs the average ESPN `proj_season` of his players at that position (what ESPN's trade grade does) | below his average: 0.5; above: 1.2 |
| name value | incoming piece's `percent_owned` and ESPN `pos_rank` against the outgoing one's | clearly lower on both: 0.7 |
| starts for him | incoming piece starts in his per-week lineup most weeks | 1.3; rides his bench: 0.5 |
| asks for his starter | a `get` piece starts for him today (`starts_today`) | 0.7 per piece |
| leaves him thin | no healthy backup at QB/TE after, or wire fallback below replacement | 0.5; cannot field a lineup: 0 |
| roster squeeze | 2-for-1 onto a full roster (he must cut) | 0.7 |
| need match | the position he gets is his weakest starting slot by *ESPN's* projection | 1.3 |
| contention | his sim playoff odds < 20% and I ask for a player who helps now | 0.8 (sellers go quiet); contender with a hole: 1.2 |
| activity | ESPN `transactionCounter.trades` and `acquisitions` (add to the snapshot) | 0 trades and < 3 acquisitions: 0.7; ≥ 1 trade: 1.2 |
| recency | an offer to this rival was declined or expired in the last 7 days (3.6) | 0.6 |

Clamp to [0, 0.95]. The point is not the decimals; it is that every laughed-at shape above gets a factor near 0.2–0.3
and the shapes people take get 0.6+. The rival's ESPN projections are already in the snapshot (`proj_week`,
`proj_season`, `pos_rank`), so "his weakest slot by his numbers" needs no new source.

### 3.5 Generation and ranking

Generate from need, not from brute force:

1. For each rival, his two weakest starting slots by ESPN projection, and his surplus (startable bodies beyond the
   slots at a position, per-week lineup, healthy).
2. My chips: players the market prices above my projection rank (sell-high), my bench players who would start for him,
   and any surplus at a position where he is weak.
3. Package shapes, in order of acceptance: 1-for-1 need-for-surplus; 1-for-2 where he gets the best player and I get
   two starters; 2-for-2 lateral at two positions; 2-for-1 star ask only under 3.2.
4. Score every survivor: `ev = p_accept × my_gain` where `my_gain` is the weighted per-week delta (3.3), with
   `my_title_delta` as the tiebreak for the top 10 (the sim is already re-run for three).
5. Row rules: `sendable` requires `p_accept >= 0.35` and `my_gain >= 1.0`; `must_try` requires `p_accept >= 0.5` and
   `my_gain >= 2.0`. The card shows at most two trade rows per league and no "reach" row (today `todos()` prints one
   even when nothing is sendable; that line goes).

Every row carries `rival_after`: the position asked for, who starts there for him after the trade (a name, or
"the wire: Mac Jones, 13.9"), and whether the best player in the deal is his or mine. `report.todos()` prints it in the
row text ("he'd be starting Mac Jones at QB after") so a paste cannot contradict it, and `report.read_lint()` warns when
a `paste` names a position the row says he is thin at as "set".

### 3.6 Memory: outcomes, not just skips

`rulings.py` already records skips and pushes. Add `data/projlog/offer_outcomes.json`: every outgoing pending offer
ESPN reports (`pending_trades`, direction outgoing) is recorded when first seen, and closed when it leaves the pending
list, with the status from `mTransactions2` where readable (accepted / declined / expired / cancelled;
**needs live pull** to confirm the history view exposes the terminal status). The scan reads it for the recency
factor and for a per-rival prior (a rival who declined three offers has a lower base). This is the first real
acceptance data the repo will have; it rides the projlog branch like the rest.

Skip memory stays keyed by `<league>|<get>` but the generator fix is what stops the sibling packages; a skipped `get`
set still blocks for 14 days.

### 3.7 Calibration and a regression bench

`tests/test_trades_bench.py`: a table of named scenarios, each a pair of rosters plus FantasyCalc values and the
expected verdict, built from the real rows the card got wrong:

- the one-QB rival asked for his QB (expect: not generated; if forced through `evaluate`, `p_accept < 0.2`);
- McMillan + Washington for Chase (expect: dropped by the star guard; fair_from_his_side 0.77);
- two mid pieces for a top-10 player with a cut required (expect: `p_accept < 0.3`);
- my bench WR who starts for him, for his bench RB who starts for me (expect: `p_accept >= 0.6`, sendable);
- a 1-for-2 where he gets my best piece and I get two of his starters (expect: generated, sendable);
- a hurt star at a discount to a contender (expect: generated for me only when my playoff odds > 60%).

The 19 skips are a second set: `scripts/replay_skips.py` rebuilds each skipped package from the projection log and
reports how many the new scan still generates. Target: fewer than three. The starting factor values in 3.4 are tuned
against these two sets, then left alone until the outcome log (3.6) has twenty closed offers.

### 3.8 The card and the skills

- `report.todos()`: two trade rows max, no reach row, `rival_after` in the text, acceptance in words from fixed buckets
  ("he'd likely take it" ≥ 0.6, "coin flip" 0.35–0.6, never printed below that because it is not a row).
- `email_html`: the same, and the push badge only when `must_try` under the new rule.
- `.claude/skills/briefing/SKILL.md` step 6: the `paste` has to be written from the row's `rival_after` line, and a
  trade row Claude rules `do` with a paste must name what he is left with when the row says he is thin. One more rule
  for the voice: ask for one thing, offer a reason that is true from his side, and never claim a fact about his
  roster the row did not print.
- `evaluate()` (incoming offers) gets the same throw-in-stripped, taxed valuation and per-week math so `counter` suggestions are the
  tweak that makes the chart fair from both sides (3.9).

### 3.9 Counters and the second ask

The research is consistent on anchoring: open at 75–90% of what I would walk away at, with a sweetener ready, and a
counter should move one piece. The row carries `fallback`: the smallest change that keeps `p_accept` above 0.5 if he
says no (swap the second piece for the next one down, or add a bench body he would start). `evaluate()` for incoming
offers produces the same thing in reverse: the one swap that turns a `counter` into an `accept` for me while keeping
his side's fair_from_his_side ≥ 1.0. Claude's `reply` is written from that, not invented.

## Phasing

**PR 1, stop the bleeding (one session).** 3.1 the taxed package value; 3.2 star guard and delete the consolidation
bonus; `depth()` on the rival's roster; `must_try` requires the new sendable rule; no reach row. Tests: the four
scenarios in 3.7 that need no per-week machinery. Expected effect: the 2-for-1 star asks disappear from the card
tomorrow.

**PR 2, the model (two sessions).** 3.3 per-week valuation with the wire fallback and `fast_lineup_mu()`; 3.4 the
scorecard; 3.5 need-driven generation and `p_accept × gain` ranking; `rival_after` on the row; 3.8 card and skill
changes; `transactionCounter` in the snapshot. Tests: the full 3.7 bench and the skip replay.

**PR 3, learning (one session, then it runs itself).** 3.6 outcome log; per-rival prior; 3.9 fallbacks and counters;
`ff trades --explain` printing the scorecard per row so a bad morning can be diagnosed from the email.

## Open questions

1. **Which QB did the math find on Hawk Tua's roster?** Needs one live `ff trades --league L3` with a probe that
   prints his QB rows (`weeks_out`, `avail_ros`, `slot`). If it is an IR stash, 3.3 is the fix. If his roster
   genuinely has one QB, the scan could not have produced +0.3 and the row came from somewhere else, which would be a
   different bug. Recommendation: run the probe before PR 1 so the regression test encodes the real mechanism.
2. **Tax or convex weight?** Both refuse the Chase package. The tax (10% / 25%) is a published convention; the convex
   weight (rest at 0.6) tracks FantasyCalc's own curve more closely at the top. Recommendation: the tax now, because
   the row can say "he'd want 10% over on a 2-for-1 and this is 23% under", and revisit after twenty logged outcomes.
3. **Does ESPN's history view expose a terminal trade status?** `mTransactions2` keeps showing PENDING after a decline
   (noted in `espn.pending_trades`). If no status is readable, the outcome log records expired-or-declined as one
   class and accepted as the other (a roster change proves acceptance). Still enough to calibrate.
4. **Should the sim's title odds replace points per week as `my_gain`?** They are the honest objective (an underdog
   should buy variance and a favorite should buy floor, and only the sim sees that; the research cites Skinner's
   result that an underdog must accept a lower mean for a higher variance), but at 1500 sims the delta is noise of
   the same size as the threshold (the `MUST_TRY_PPW` comment says so). Recommendation: keep ppw for the gate and
   the ranking, title odds for the tiebreak and the row text, until the sim is cheap enough to run at 10k for the
   top three. The variance sign can come in cheaply as a term on `my_gain`: a consolidation (fewer, bigger starters)
   gets +10% when my playoff odds are under 40% and -10% when they are over 70%.

## Deviations from the brief

- **PR 1 and PR 2 (2026-10-07).** The fair band is 10%, not 5%: the charts call 5% even, but a stale price on one piece and
  the endowment effect make 10% what a real person tolerates, and the hard drop sits at 0.8. The "leaves him thin" factor
  applies to QB only: a backup TE is streamed, and K/DST never move. The acceptance base is 0.5 with the factors in
  `acceptance.score`; a 2-for-1 where I get the best player can reach "coin flip" only with a visible overpay, his
  weakest slot filled, and his app grading the piece up, which is the shape the research says lands.
- **The skip replay (3.7) cannot run offline.** The projection log holds my players only; rival rosters are not stored
  anywhere, so the 19 skipped packages cannot be rebuilt. The regression bench encodes the two rows from the email with
  their real FantasyCalc values instead, and the outcome log (PR 3) is the calibration set going forward.
- **Need-driven generation (3.5) is a ranking, not a generator.** The brute-force package loop stays (it is cheap and
  complete) and now includes 1-for-2 and 2-for-2 shapes; his weakest slot, his surplus and my sell-high chips enter as
  scorecard factors rather than as the only seeds, so nothing the old loop could find is lost. The one thing this plan deliberately does not do is build a learned model: there are 19 labelled examples,
all negative, and the scorecard above is legible on a phone, which a classifier is not.
