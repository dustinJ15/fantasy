# Ralph loop — working the backlog one fresh session at a time

Handoff written 2026-10-20 for the agent that manages the loop. The loop is the TODO.md protocol ("Working an item in
a fresh session") run repeatedly: a fresh worker session per item, one PR per item, merge on green, next item. The
manager does no engineering; it starts workers, checks the PR, merges, and stops when the queue or the budget is done.

## Why fresh sessions, and what that costs

Every session loads CLAUDE.md (205 lines until Docs-1, half of it the failure table; 89 now) before it reads a word of the item. A
worker that then tours the repo spends more on reading than on the fix. The loop is cheap only if each worker reads
exactly what its item names and nothing else, and if CLAUDE.md gets shorter. That is why the first iteration was the
docs item (Docs-1, done 2026-10-20), whatever the tier order said: it pays back on every later iteration.

## The manager's loop

Prompt for every worker, verbatim, one line:

    Read CLAUDE.md and TODO.md, take item <id>, follow "Working an item in a fresh session" in TODO.md, open the PR, and stop.

1. Pick the item: the first unchecked box in TODO.md top to bottom (Tier A, B, C, then D, E).
   Items that say "after X" wait for X. Do not pick two items that touch the same file at once; the ledger items
   B12, B14, B15 all edit `report.py`, so they run in series.
2. Start one worker with the prompt above (`create_session` in the cloud env, or `claude -p` locally). Give it the
   branch name and nothing else. Do not paste the plan or the file contents into the prompt: the worker reads them.
3. When the worker's PR is up: wait for `ci` (ruff, pytest, the demo briefing). Green and the PR body says what was
   wrong, what changed, how it was verified → merge (merge commit, the repo's convention). Red → one more worker on
   the same branch with "CI is red on PR #N: read the failing job, fix it, push, stop". Red twice on the same item →
   stop the loop on that item and tell Dustin which item and what fails.
4. After each merge: the worker deleted the item from TODO.md in the same PR (the protocol says so); if it did not,
   the next worker will pick it again, so check before step 1.
5. Stop when every box in Tiers A, B, C and Docs is gone, or on a budget you set up front (N iterations). Tier D and E
   items are larger and want Dustin's go per item; leave them unless told.

Main is what the 5:59 AM Denver routine clones, so a broken main is a missing briefing. Never merge red. If a merge
lands within an hour of 5:59 AM Denver in season, re-check CI on main itself after the merge.

A manager with no session budget of its own: a scheduled task (`create_trigger`, `create_new_session_on_fire`) with the
same one-line prompt and "take the top unchecked item" in place of `<id>`, every 4 hours, does the same loop with no
manager tokens at all; the only thing it cannot do is merge, so Dustin merges green PRs from his phone.

## Rules the worker already has, restated because they are the budget

- Read the item, the plan section it cites, and the functions it names, by line range (`sed -n`, `grep -n`); never a
  whole 1,100-line file. `report.py`, `packet.py`, `email_html.py` and `model/trades.py` are the big ones.
- Reproduce first: the failing test the plan names, or `uv run ff briefing --demo --short`. No reproduction, no fix:
  write one line under the item in TODO.md saying what did not reproduce, open no PR, stop.
- One item, one PR, the test that would have caught it. Nothing else in the diff. A second finding is a new TODO line.
- Run the one test file while iterating and the full suite once before the push (`uv run pytest -q`, ~2 min).
- The commit message is the write-up. The PR body is three lines (wrong, changed, verified). No narration in chat.
- If the fix closes a failure mode Dustin could see in an email, one row in the CLAUDE.md failure table, in the
  table's format (symptom, cause, fix), and nowhere else.
- Never: ESPN writes, the `projlog` branch, committing generated files or `data/`, skipping a test to go green.

## Docs-1, done 2026-10-20

The first iteration was the docs item: `docs/README.md` indexes every tracked markdown file, CLAUDE.md is under 90
lines (`tests/test_docs.py` holds it there), the fixed rows of the failure table are in `docs/failures.md`, Operations
in `docs/operations.md`, the accuracy table in `docs/accuracy.md`, every plan carries the same status header and keeps
its open work in TODO.md. The house style for anything an agent reads: function and constant names, never line numbers;
a symptom-cause-fix row for anything that failed; the file's audience in its first sentence; dates as YYYY-MM-DD; no
duplicate prose, link to the one place instead. `README.md` is Dustin's and the public's; leave its voice alone.

## What is in the queue today (2026-10-20, main at eff5f16)

- Tier B: B12, B14, B15, B16, B17, B18, B19 from `docs/plans/card-mixed-messages-2026-10-20.md`, in that order;
  B12, B14, B15 in series (same file).
- Tier C: C5 (the email send path).
- Tier D: D1, D2 (waiting on data), D8. Dustin's call per item.
