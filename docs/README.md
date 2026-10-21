# The documents, and who each one is for

For any agent or person opening this repo cold: one line per markdown file, who it is for, what it holds, and when to
read it. An agent reads CLAUDE.md every session and everything else only when the task names it. House style for the
files an agent reads: function and constant names, never line numbers; a symptom-cause-fix row for anything that
failed; the audience in the first sentence; dates as YYYY-MM-DD; no duplicate prose, link to the one place instead.
`tests/test_docs.py` checks that every tracked `.md` is listed here.

| file | for | holds | read when |
|---|---|---|---|
| `CLAUDE.md` | the agent, every session | the boundary rule, the morning routine, commands, the layout by module, data gotchas, the four operations lines, the failure rows still open or that are checks | every session, first |
| `TODO.md` | the agent working an item | the only queue: tiered items with evidence and a done-when, and the fresh-session protocol | taking an item |
| `docs/ralph-loop.md` | the agent managing the loop (and the worker it starts) | the one-line prompt, the manager's loop, the rules that are the budget, what is in the queue | running the backlog as a loop |
| `docs/failures.md` | an agent working an item, or anyone who sees an old symptom return | the fixed rows of the failure table (symptom, cause, fix with date and TODO id) by area | a symptom matches, or before re-fixing something |
| `docs/operations.md` | a fresh session responding to a morning email; Dustin | the routines and their crons, the trade alert paths (doorbell, poller), the MLB pregame one-shots, the memories on the `projlog` branch, the rulings | a run failed, an alert did not fire, a memory went missing |
| `docs/accuracy.md` | an agent or Dustin weighing a source, or a lineup or sigma constant | the `ff accuracy` table by source and position, the `ff backtest` tables (P(win) calibration, the optimizer against the set lineups, executed trades, the scanner replay's trade and claim tables) and how to read them | re-weighting a source, D2, or changing `MIN_WIN_GAIN`, `BASE_SIGMA`, `CV_FLOOR`, `MUST_TRY_PPW`, `SEND_MIN_PPW` or `CLAIM_WORTHY_PPW` |
| `ROADMAP.md` | Dustin, and anyone deciding what to build next | the direction: where the edge is, projection sourcing, honest weaknesses, improvements in order (finished ones marked with their TODO id) | choosing the next large item |
| `README.md` | Dustin and the public | what the tool is, the screenshots, setup, the commands table, how it is built, honest limits | first contact with the repo |
| `docs/plans/injured-player-decision.md` | an agent touching `model/injuries.py` | the hold / IR / drop / trade rule's design, worked examples, the questions as decided (implemented 2026-09-23) | changing the injury rule or its constants |
| `docs/plans/trade-acceptance.md` | an agent touching `model/trades.py` or `model/acceptance.py` | the acceptance model's design, the scorecard, outcomes memory, the questions as decided (implemented 2026-10-07) | changing how packages are built, taxed or ranked |
| `docs/plans/in-season-projection.md` | an agent touching the rest-of-season level (`season_pg`, `opportunity_mult`) or `model/usage.py` | the in-season projection's design: the season-to-date level, the fading prior, the opportunity read and its worked example, the questions as decided (implemented 2026-10-20) | changing how a player's rest-of-season per-game number is built |
| `docs/plans/backtest.md` | an agent running or extending the backtest, or reading its tables before changing a lineup or sigma constant | the replay file (what ESPN's archive keeps and lost), the two scorers (P(win) calibration and the optimizer, the trade hits), the synthetic check, the leakage rules, what the first live run found (2026-10-20: a completed season has no lineups) and the scanner replay (done, D12) | D13; changing `MIN_WIN_GAIN`, `BASE_SIGMA` or `CV_FLOOR` |
| `docs/plans/scanner-replay.md` | an agent extending the scanner replay (D12, done), or reading its tables before changing a trade or claim constant | what the trade scan and the claim ranking need from a replayed week and where each input comes from (the player universe, the chart off), the replay file version 2, the two scorers (`scan_hits`, `claim_hits`) and their tables, the synthetic check, the leakage rules, the five steps and the probe (`scripts/probe_replay_pool.py`) | D13; changing `MUST_TRY_PPW`, `SEND_MIN_PPW` or `CLAIM_WORTHY_PPW` |
| `docs/plans/card-mixed-messages-2026-10-20.md` | the agent taking B12-B19 | the Oct 20 card's rows, root causes by function, the fixture each fix needs (plan only) | taking one of those items |
| `docs/research/trade-acceptance.md` | an agent reading the trade plan | cited web research on what gets a redraft offer accepted; sources, not measurements | questioning a scorecard factor |
| `.claude/skills/briefing/SKILL.md` | the agent at run time (the `/briefing` skill) | the morning routine step by step, the research prompt, the override guide, the send | the briefing and Sunday routines; editing the prompt (`tests/test_skill_prompts.py` holds it to the code's constants) |
| `.claude/skills/trade-offer/SKILL.md` | the agent at run time (the `/trade-offer` skill) | evaluating an incoming offer, the ruling on the `offer:` row, the reply to paste | a doorbell or poller fire; editing the prompt |
| `.claude/skills/mlb-pregame/SKILL.md` | the one-shot session `scripts/mlb_pregame.py` inlines it into | the pregame push for an MLB game; may name no file, the fired session has no checkout | editing the push |
| `scripts/setup_cookies.md` | a human setting the tool up | league ids, the ESPN cookies, `.env`, `leagues.toml` | first setup, or when `ff doctor` says the cookies are dead |
| `scripts/gmail_trade_doorbell.md` | a human setting the doorbell up | the Apps Script install, Script Properties, the trigger, the test fire | installing or re-checking the doorbell |
| `examples/briefing.md` | the public, via README | a rendered demo briefing (synthetic league); regenerated by `scripts/screenshots.sh` | never by hand; it is output |
| `docs/README.md` | anyone opening the repo cold | this index | finding which document to read |
