# TODO — the backlog, one PR per item

Findings from the 2026-10-08 line-by-line review, ordered by how much each one changes the numbers Dustin acts on.
ROADMAP.md says where the model should go; this file says what to do next and how to know it is done. Pick the
top unchecked item in the highest tier, make one PR, delete it, add a row to the CLAUDE.md failure table if the fix
closes a failure mode. Line numbers are as of commit 82c3480.

Sizes: XS under an hour, S a morning, M a day or two, L a week with a plan in `docs/plans/`.

## Working an item in a fresh session

Dustin's prompt is one line: "Read CLAUDE.md and TODO.md, take the top unchecked item (or item <id>), fix it, and open a PR."
The session then:

1. Reads CLAUDE.md (the boundary rule, the layout, the failure table) and this file. Reads the files the item names
   before touching anything; the line numbers drift, the function names do not.
2. Reproduces the finding first: a failing test, or the probe the item describes (`uv run ff briefing --demo`, a
   fixture from `tests/`, the projlog branch via `git fetch origin projlog`). An item that cannot be reproduced is
   reported back, not fixed on faith.
3. Fixes that one item and nothing else. Scope creep is the thing this list exists to prevent; a second finding on
   the way is a new line here, not a second change in the PR.
4. Adds the test that would have caught it, runs `uv run pytest` and `uv run ruff check`, and `uv run ff briefing
   --demo --short` to see the card still renders.
5. Deletes the finished item from this file (a ticked box is not a record: anything learned goes to the CLAUDE.md
   failure table when the fix closes a failure mode Dustin could see in an email, or to the relevant `docs/plans/`
   file otherwise). The commit history is the log of what was done.
6. Opens a PR titled after the item id and its first clause; the body says what was wrong, what changed, how it was
   verified. Code reaches the cloud routine only after merge to main.

Rules that hold for every item: read-only against ESPN; code owns numbers, Claude owns prose; never commit
`briefing.md`, `overrides.json`, `reads.json`, `data/`, `leagues.toml` or `ops.local.md`; a test that only asserts
"no exception" does not count as the test.

## Tier A — bugs that distort every number today

(none open)

## Tier B — checklist and ledger bugs

(none open)

## Tier C — operations

- [ ] **C5 (S). The email body is assembled by the LLM.** `briefing/SKILL.md:99-103` has the model paste the
  HTML into the Gmail tool and check `wc -c`. `ff email` already exists (`src/ff/mail.py`); give the cloud env
  `GMAIL_USER`/`GMAIL_APP_PASSWORD` and make the skill call it, with the paste as the fallback.

## Tier D — where real edge would come from (after Tier A)

- [ ] **D1 (M-L). In-season rest-of-season projection.** Season-to-date points per game, target and carry share
  from `model/usage.py` (computed, rendered nowhere, moves no number), and the weekly blend, with the
  preseason total as a prior that fades by week 6. This is ROADMAP item 1 and the only private edge; plan in
  `docs/plans/`.
- [ ] **D2 (S, waiting on data). Adopt the fitted variance** per position. The fitter exists since 2026-10-08
  (`ff accuracy --fit`, `projlog.sigma_fit`): it fits `BASE_SIGMA` and `CV_FLOOR` in `model/projections.py` to the blend
  residuals in the optimizer's own shape and refuses a position under `projlog.FIT_MIN_N` (150) scored forecasts. As
  of 2026-10-08 (weeks 1-4 scored) the samples are QB 18, RB 49, WR 46, TE 21, K 10, D/ST 10, so every constant is
  still the prior. A scored week adds about 12 RB, 12 WR, 4-5 QB and TE, 2-3 K and D/ST: RB and WR cross 150 around
  week 13-14 of 2026, QB and TE late in 2027, K and D/ST not before 2029 (pool them across positions or lower the bar
  with a reason). When a row says `fit`: copy the printed pair into `model/projections.py` with the sample size and
  date in the comment and the old value kept, and only then revisit `MIN_WIN_GAIN` in `model/lineup.py` (1.5pp): the
  early fits read wider than the priors (RB 10.8 vs 6.5, WR 12.2 vs 6.5), so the floor comes down only if a real fit
  says sigma is smaller, and in proportion. Code owns the numbers: take what the fitter prints or leave the prior.
- [ ] **D8 (L). Backtest harness** (ROADMAP 8): replay 2025 for lineup P(win) calibration and trade hit rate.

## Tier E — tests that would catch model errors

(none open)

## Docs

- [ ] **R1 (S). Bring README.md up to date.** Last touched 2026-09-23 (commit `1f7d98f`), before the 2026-10-08
  backlog run that landed 30 commits. Stale or missing as of 2026-10-08: "How it's built" says `uv run pytest` runs
  40 tests (it is 317); "What the math does" and the Commands table describe waivers as FAAB bids while all three
  leagues use priority (`claim` / `add` rows, and since D3 the priority a claim spends), and say nothing about the wind penalty (D5), the
  opponent's set lineup on Sat–Mon (A4), the P(win) floor on the lineup row (A5), market-, handcuff- and bye-aware
  drops (B6, B6b), or the title-odds delta being common-random-numbers (A3); the Architecture diagram does not show
  `src/ff/ledger.py` (B12), `src/ff/rulings.py` and the four memories that ride the `projlog` branch
  (`skipped_trades`, `pushed_trades`, `offer_outcomes`, `ir_moves`), `scripts/projlog_push.sh`, or the alert paths
  (Gmail doorbell, GitHub poller gate, the Sunday 9:45 routine). Rewrite those sections from CLAUDE.md's Layout and
  Operations paragraphs (which are current), keep "The one rule" and "Honest limits" as they are unless a limit was
  closed, and regenerate `examples/` with `scripts/screenshots.sh` so the email screenshot shows the current card.
  Done when: every file, command and number the README names exists in the tree (a test in `tests/` that greps the
  README for backticked `src/ff/*.py` and `scripts/*` paths and asserts each exists is cheap and keeps it honest),
  and the test count it quotes is read from, or no longer stated as, a fixed number.
