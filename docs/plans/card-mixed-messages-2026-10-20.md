# Plan: the Oct 20 card's mixed messages

Status: B12 (§1), B14 (§2) and B15 (§3) implemented 2026-10-20; the rest plan only.
Written: 2026-10-20 against `main` at 705ac88 (391 tests passing).
TODO ids: B12, B14, B15, B16, B17, B18, B19.
Still open: B16, B17, B18, B19, in that order.

For the agent working one of those items. The packet behind the email is not in the repo (`data/packets/` is
untracked), so every finding below is read off the email itself and traced to the function that wrote the line; each
fix names the fixture a test needs to reproduce it.

## What Dustin read this morning

Week 7, Tuesday. Three leagues, the same kicker on IR in two of them (Grupe), two QBs on bye in one, the whole wire
on waivers (Tuesday), and a D/ST on bye. Those are routine; the card made them read like a mess:

- **Mile High Mf.** Five rows for one problem. "Waiver: claim Bo Nix, drop Mike Washington Jr." then "Stream: swap
  in Chris Boswell at K (+5.2 this week)" then "Cover K: Grupe is 100% to sit and your only K: claim Boswell; drop
  TreVeyon Henderson (market 440, 6.4/wk)" then "Drop: drop Blake Grupe (K); add Aaron Rodgers (best body on the
  wire, depth only)" then "Drop: drop AJ Dillon; add DeMario Douglas (depth only)". Four adds, four drops, a kicker
  claimed twice, a real RB cut for a kicker while the kicker on IR is dropped for a "depth only" QB, and that QB is
  the one the waiver table ranks first (START NOW +18.4, trending +63k) while the row claims the second one and
  falls back to the third. The lineup row then moves one bye QB out and the other bye QB in ("Lawrence: QB →
  bench · Herbert: bench → QB", both 0.0), the detail lineup starts Grupe at K, and the header says "win 25%" on a
  lineup with two empty slots the same card fills by Wednesday. Claude amended three rows to say "use Grupe's spot,
  Henderson stays, skip Rodgers, QB is Nix once the claim lands".
- **FCLS.** "Cover D/ST: Jaguars on bye and your only D/ST: claim Jets D/ST; drop Khalil Shakir (9.2/wk, on bye
  this week)" and right under it "Drop: drop AJ Dillon; add Seth McGowan (handcuff for Jonathan Taylor)". The spot
  Dillon frees goes to a handcuff; the D/ST the card says I need costs a WR3. The detail lineup starts the Jaguars
  on bye. The trade detail leads with "Give McMillan → get Warren from TBD: me +1.1 ppw · title odds me -0.8 / them
  +4.9 · he'd likely take it" (TBD is the title favorite) and lists a two-for-two with this week's opponent, and the
  checklist has no trade row, so nothing says why neither is a thing to do.
- **Denver.** "IR: move Rashee Rice to IR, then add Seth McGowan (handcuff)", "Stream: swap in Boswell (+5.4 this
  week)", "Cover K: Grupe is 100% to sit...: claim Boswell; drop Juwan Johnson (10.3/wk)" (Johnson is in the flex
  today), "Drop: drop Grupe; add Jaleel McLaughlin (handcuff)". Two spots spent on handcuffs, a flex starter cut for
  a kicker, the kicker row three times. The lineup benches Caleb Williams (Thu, 18.7) for Kyler Murray (Sun, 19.5).
- **Summary lines.** Mike Evans is in **Watch** (Doubtful) and in **Out** (~1 wk) at once. "back around week 12.;".
  The roster table says Evans 17.84 this week next to "100% chance to sit" and Monangai 10.7 next to `espn:OUT`.
  "their set lineup" on a Tuesday, when it is last week's lineup nobody has touched.

The rows are each correct on their own terms. The mess is that five builders spend the same roster spots in the
wrong order and nothing checks the card as a whole.

## Root causes, by how many rows each explains

### 1. The model names the add before the ledger exists, so a freed spot goes to depth before need (B12)

`injuries.decide` ends with `fill_spot` on every `ir` and `drop` row: the model picks "who takes the spot" with no
idea what the card needs today. `report.todos` then treats that as spent: `_ledger` reserves every `ir` player,
`todos` reserves every Drop-row player with an add, and seeds `added` with the model's picks before `_waiver_items`
runs. The Cover and Waiver rows, built after, can only cut a healthy body. Separately `ledger.bench()` skips K and
D/ST, so a kicker on IR with a drop cost of zero is never the ledger's drop for anyone.

That one mechanism is every "use that spot instead" amend this morning (Henderson, Shakir, Johnson) and the Rodgers
inversion: Rodgers went to the Grupe row as "depth only" (`fill_spot` falls through to `by_score`, and he is the
trending body), so `_waiver_items` found him in `added` and claimed Nix. It is also the four-QB card: a `depth` add
at a one-starter position when I already hold two.

**Fix.** The ledger decides who takes a freed spot, in the order the card prints:

1. A Drop-verdict player is a free drop: `drop_order` puts him first at cost 0 whatever his position (he is already
   a drop; the K/D/ST exclusion is for healthy specialists). `Spots.take` hands him to the first row that needs a
   spot, and `_injury_items` folds that Drop row away exactly as it folds the one an activation takes (`folded`), so
   the row reads "claim Chris Boswell (K); drop Blake Grupe" with "on IR, out ~4 wks, worth ~0 the rest of the way"
   in the detail. A Drop row prints on its own only when nobody took him.
2. An IR move frees a bench spot: `_injury_items` credits `spots.open += 1` for an `ir` row without an occupant,
   the row stays "move Rashee Rice to IR", and the next pickup's suffix reads "(into the spot the IR move frees)".
3. Depth comes last. The model's `add` on an `ir`/`drop` row is a suggestion for a spot nobody above wanted:
   `todos` prints "then add X" (or the existing Open-spot row) only for spots still open after the waiver, stream
   and cover rows. `fill_spot` moves out of `decide` into report time with the `added` set, so it never names a
   body a row above already adds and never names a QB/K/D/ST as depth when the roster already holds two.

`todos` order becomes: offers → IR/activate (crediting spots) → waiver → cover+stream (one row, B14) → remaining
Drop rows and depth adds → lineup → sent → trades → holds.

**Test** (`tests/test_card.py`): a league with a K on IR carrying a `drop` verdict and an `add`, a healthy RB4 on
the bench, Boswell on the wire, no open spot. Today: cover row drops the RB4, Drop row adds the model's body. After:
one row "claim Boswell; drop Grupe", the RB4 unnamed, the model's body unnamed. A second case: an `ir` row plus a
START NOW waiver → the waiver row takes the IR spot and names no drop. A third: the START NOW row names the top
`delta_week` body whatever the injury rows suggest.

### 2. Three rows for one kicker, and the stream's number is the wrong one (B14)

`_stream_items` takes the top streamer with `delta_over_starter >= 1.5` and prints it as "+5.2 this week".
`delta_over_starter` is the rest-of-season gap (Boswell's 8.4/wk over Grupe's 3.2/wk); the this-week gap is
`delta_week`, which is Boswell's whole μ because Grupe is 0 this week. The row reads neither `added` nor the cover
row, and `_cover_items` runs after it and does not see the stream. A stream at K/D/ST is a swap, so its drop is the
specialist it replaces, but the ledger never names a specialist.

**Fix.** One row per position. `_cover_items` runs first (it is the need) and marks the position; `_stream_items`
skips a name in `added` and a position already covered. The stream row names the body it replaces as the drop
("swap in Chris Boswell for Blake Grupe at K"; the swap is the drop, and the ledger counts it) and prints
`delta_week` as "this week". When the current K is out, on IR or on bye, the stream row is the cover row.

**Test**: K on IR, Boswell on the wire → exactly one row names Boswell and it names Grupe as the drop; a healthy K
with a +2 streamer → one Stream row, no Cover row; a Stream row's number equals the waiver's `delta_week`.

Implemented (B14): `_cover_items` runs before `_stream_items` in `todos`; `_stream_items(lg, spots, added)` gates
on `delta_week >= 1.5`, skips a body in `added` or a position a row above brought one in at, names the specialist
it replaces (the starter at the slot, else any body I hold at the position a row above has not spent) and books him
through `Spots.swap`, so a Drop verdict on him folds into the row; with nobody to swap out (locked, or the slot is
empty) the add takes a spot from the ledger like a pickup. Tests under "B14" in `tests/test_card.py`.

### 3. The lineup seats players who score zero, and prints the zero swap (B15)

`lineup.optimize` keeps `p.mu > 0` in `avail` (Grupe: μ 8.38, `ev` 0), and the per-slot fallback "try anyone
eligible" seats a bye player instead of leaving the slot empty, so the EMPTY line CLAUDE.md promises never prints.
`_lineup_changes` then emits "Lawrence: QB → bench · Herbert: bench → QB" for two zeros. The header's "win 25%" is
the lineup with those zeros in it, not the lineup the card builds.

**Fix.** A player on bye or with `p_zero >= 0.99` never starts: `avail` requires `ev > 0 and not bye`, the fallback
is `None`, and `to_dict` already prints the EMPTY marker. `_lineup_changes` never swaps two zero-EV bodies; at an
empty slot it names what the card is doing about it: "QB: nobody plays this week (Herbert, Lawrence on bye); Bo Nix
once the claim lands Wed 1:00 AM". That extends `_pickup_move` to a claim at a slot with no healthy body (the Oct 10
rule kept claims off the lineup row because the lineup above still stood; at an empty slot nothing stands). The
header prints the P(win) with the card's adds in: `packet` re-runs `optimize` with the waiver and cover bodies added
(`lineup_after`) and `action_card` reads "win 25% today, ~45% once Nix and Boswell are in" when they differ by more
than a point of P(win).

**Test** (`tests/test_lineup.py`, `tests/test_card.py`): two bye QBs → QB slot EMPTY, no QB swap on the row, the
claim named; a K with `p_zero` 1.0 → K slot EMPTY; `lineup_after` beats `lineup_win` when a claim fills an empty
slot.

Implemented (B15): `lineup.startable` (`ev > 0`, not on bye, `p_zero < NEVER_STARTS_AT`) gates `avail`; a slot
short of startable bodies gets `None` as a seat and `Lineup.holes` counts the seats nobody filled, which `to_dict`
prints as one `EMPTY_SLOT` marker each. `rank_free_agents(lineup_slots=)` scores an empty seat as zero, so the wire
body at it reads START NOW for his whole EV. `report._empty_slot_lines` writes the slot's line from the bodies I hold
for it (`sit_word`) and the add rows above (`add` on every waiver, cover and stream row); a zero sitting in a slot
that stays empty is not moved to the bench. `_cover_items` reads an empty K/D/ST/QB seat as the need. `packet
._lineup_after` re-runs `optimize` with the first waiver-table body per empty seat and `report.win_note` /
`win_after_note` print "win 25% today, ~45% once Nix and Boswell are in" in both renderers when it moves a point.
Tests under "B15" in `tests/test_lineup.py`, `tests/test_waivers.py`, `tests/test_card.py`,
`tests/test_packet_synthetic.py`.

### 4. Trade candidates with no row and no reason (B16)

`_trade_items` prints only `sendable` packages (`them >= -0.25`, `p_accept >= SENDABLE`, my gain >= 1.0).
`_detail_trades` prints `lg["trades"][:3]` in scan order with no `sendable` flag; the "not a row" word only shows
when `accept_word` is missing. `sendable` never reads the title-odds delta, so "me +1.1 ppw" leads a package that
costs me 0.8 title points and hands the favorite 4.9. Nothing warns that a rival is this week's opponent.

**Fix.** The scan sets `why_not` next to `sendable` ("costs him 0.6/wk", "coin flip at best", "under +1.0/wk for
me", "lowers my title odds"); `_detail_trades` prints "row" or "not a row: <why_not>" and sorts sendable first.
`sendable` requires `my_title_delta >= 0` when the packet has one. A rival who is this week's opponent gets a
`TRADE_WARN_PREFIXES` line ("he is your opponent this week; accepted today it executes before kickoff").

**Test** (`tests/test_trades.py`, `tests/test_card.py`): a package with `their_delta_ppw` -0.6 reads "not a row:
costs him 0.6/wk" in the detail; a package with `my_title_delta` -0.8 is not sendable; the opponent warning prints.

### 5. Words that contradict the state (B17, one XS PR)

- `_cover_items` `risk` and `why_parts` say "100% to sit" for a player on IR or Out: say "on IR" / "out" when the
  designation is the reason (`p_zero >= 0.99`), keep the percentage for a researched Questionable.
- `watchlist` and `injured_list` both carry Mike Evans: a player in `shared.injured` leaves the Watch line.
- `injured_line` / `watch_line` join a note ending in "." with "; ": strip the trailing period.
- `_detail_roster` "wk μ" is the conditional projection: print the EV (`mu × (1 − p_zero)`, 0 on a bye) in that
  column and keep μ in the flags for an Out/Doubtful player, so 17.84 never sits next to "100% to sit".
- `packet` calls the rival's lineup "set" on a Tuesday because `is_complete` is true of last week's leftovers:
  "set" only on `LINEUP_SET_DAYS`; the rest of the week it is "their lineup as it stands" with the optimizer's
  number, as today.
- The Dillon Drop row and the Handcuffs line disagree: the Drop row's detail says "handcuff for Hubbard, but worth
  ~0 even then" when he is in `lg["handcuffs"]`.

### 6. Noise-level lineup swaps (B18, after the rest)

"Caleb Williams: QB → bench, set by Thu · Kyler Murray: bench → QB" for +0.8 points. `optimize` is exact on EV and
has no floor for a swap between two healthy starters, so a sub-point edge is a click, a Thursday deadline and a
lost option. A `MIN_SWAP_GAIN` (1.0) in `optimize`: when the recommended and current seat a different healthy
player at a slot and the EV gap is under the floor, keep the current one; the why line says "+0.8 at QB is noise,
leave Caleb in". Bye, Out and empty-slot replacements are never held. Same shape as `MIN_WIN_GAIN`. Lower priority
than the rest: it is one click, not a wrong click.

## A check on the card as a whole

None of the above would have been caught by a row test, because every row was right about its own numbers. Add
`report.card_lint(lg, rows)` run by `ff render-email` (warnings next to `read_lint`'s) and a test over the demo
league and the fixtures above:

1. A body is added by at most one row.
2. No row cuts a healthy body while a Drop-verdict player is still on the roster.
3. No recommended starter has `ev` 0 while a bench or wire body eligible for the slot has `ev > 0`.
4. The Stream and Cover rows never name the same position.
5. Every trade candidate in the detail says whether it is a row.

And one line in `briefing/SKILL.md`: when two rows add the same body, `skip` one; a note under the other is not a
ruling (the Stream row went unruled this morning while the Cover row's note said it covered both).

## Order

B12 first (it is three of the five amends and the Rodgers inversion), B14 (one kicker row) and B15 (empties and the
claim on the lineup row) next because they share fixtures, then B16, B17, the lint, B18. Each is one PR per the
TODO.md rules; B12 is M, B15 is M, the rest S or XS.
