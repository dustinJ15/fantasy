---
name: briefing
description: Run the morning fantasy football briefing — sync data, build the decision packet, research the injury watchlist, apply overrides, render the briefing, and email it to Dustin.
---

# Morning briefing

Follow these steps exactly. Do not invent numbers; every figure comes from `ff` output. All commands run from the repo root.

1. `bash scripts/cloud_setup.sh` (installs uv/deps if missing, writes .env from env vars, runs `ff doctor`).
   If doctor reports dead ESPN cookies, stop and email Dustin a one-paragraph note saying the cookies need refreshing
   (see scripts/setup_cookies.md) instead of a briefing.
2. `uv run ff sync` then `uv run ff packet --sims 2000`. The packet step takes 3-5 minutes: run it with the Bash tool's
   `timeout` set to 600000 (ms) so it is not cut off. Note the packet path it prints and read that JSON.
3. Research (WebSearch), in this order, spending at most ~10 searches total:
   - every entry in `shared.injury_watchlist` (latest practice report / beat-writer status),
   - every entry in `shared.injured` (players out for a week or more, or on IR): how many more games he misses, from a
     team statement or beat writer. Skip the search when its `notes` (Sleeper) already says ("out for the season",
     "placed on IR, eligible to return week 9"). The packet's `weeks_out` is a designation default (IR = 4) until you
     write a real number,
   - each starter in any league's `lineup_win.slots` whose flags include QUESTIONABLE/DOUBTFUL/OUT or `sleeper:`,
   - the top 3 waiver targets per league (is the role change real?),
   - every player named in any league's `incoming_trades` (an offer someone sent Dustin; the packet already has a verdict).
   Note the day: Tue/Wed = waivers matter most; Fri/Sat/Sun = final designations and weather; Thu = TNF players;
   Mon = only Monday-night players can still move (each league's `week_state` in the packet says the phase, the score so
   far, and who is left to play); do not research or suggest lineup changes for players marked `locked`.
4. Write `overrides.json` at repo root containing only players where news moves the picture:
   `{"<espn_id>": {"p_zero": <0-1>, "mu_mult": <0.5-1.5>, "weeks_out": <games or "season">, "ros_mult": <0.5-1.5>, "note": "<source + one-line reason>"}}`
   `p_zero` and `mu_mult` are this week only. `weeks_out` and `ros_mult` are the rest of the season and drive the
   hold / IR / drop / trade row for a hurt player; write `weeks_out` for every `shared.injured` entry you researched.
   p_zero guide: full practice + no tag 0.03; Q + limited Fri 0.25; Q + DNP Fri 0.5; Doubtful 0.85; Out/IR 1.0.
   weeks_out guide: IR 4 unless the report says longer; `"season"` for an ACL, Achilles or season-ending surgery;
   suspension = games announced; count from this week (an Out this week with a return next week is 1).
   ros_mult only for a changed role or a diminished return (hamstring at 85%), not for this week's snap count.
   If nothing changed, write `{}`.
5. `uv run ff briefing --overrides overrides.json --sims 2000 --out briefing.md` (also 3-5 minutes; timeout 600000).
   Read briefing.md and note the packet path printed on the last line (`packet data/packets/<date>.json`).
6. Write `reads.json` at repo root — your judgment, as parameters. One entry per league keyed by its `name` from
   leagues.toml (L1/L2/L3); omit a league if you have nothing to add:
   `{"L1": {"read": "<1-2 plain sentences of what your research adds that the math could not know>",
            "items": {"<row id>": {"verdict": "do|skip|amend", "note": "<one short reason, required unless do>"}},
            "paste": "<exact message Dustin can paste to the rival, only if a trade is worth sending>", "paste_to": "<rival team name>",
            "reply": "<what Dustin sends back on an incoming offer: a polite no for decline, a concrete tweak for counter; omit for accept>", "reply_to": "<rival team name>"}}`
   Only include `reply` when that league has an entry in `incoming_trades`.
   **Rule on rows in `items`, do not argue with them in `read`.** briefing.md prints each row's id in backticks at the
   end of the line (`[trade:jayden-daniels]`, `[waiver:devaughn-vele]`, `[lineup]`, `[cover:k]`); copy it exactly.
   - `skip` strikes the row out in the email and prints your note as the reason. Use it when the row is wrong.
   - `amend` keeps the row and attaches your correction (e.g. "add him, but that flex slot is locked, he starts next week").
   - `do` is confirmation, and is the only verdict that needs no note.
   The card is the model's math and your read is judgment; they are allowed to disagree, but the email has to end with
   one answer per row, not a card saying do it and a paragraph underneath saying don't. Every `trade` row needs a
   verdict — the card lists up to three and Dustin cannot tell which one you meant otherwise. So does every
   `injury:` row whose label is `Hurt (drop)` or `Hurt (trade)`: a drop is final, and its biggest input is your
   `weeks_out`. `ff render-email` warns about a typo'd id, a missing reason and an unruled trade or drop; fix
   reads.json and re-run before sending.
   Leave `read` for what is genuinely new: the news, the practice report, the thing the model has no column for.
   If it only repeats a row's verdict, drop it.
   Do NOT edit briefing.md or the HTML by hand. If research changes a player's availability (ruled out, a role change),
   that belongs in overrides.json (re-run step 5); the override `note` shows up next to the player in the email.
   Dustin reads this on a phone: keep each read short.
   Voice (`read`, `paste`, `reply` and each `note`): write like a guy texting a coworker about football, not like an assistant.
   - The `paste` message goes to a real person in Dustin's league. One or two casual sentences, first person, lowercase is fine,
     say what you want and why it helps *them*, end with a question. Example: "hey, any interest in Rice + Montgomery for Henry?
     you're thin at WR and I could use the RB. no worries if not". Never mention projections, models, points per week, or Claude.
     Set `paste_to` to the rival named in the trade row you gave a `do`, so the message renders under that row.
   - Avoid the known AI tells: no em dashes (use a comma or a period), no "not X, but Y" reframes, no lists of three, no
     "label: explanation" openers, no "worth noting"/"that said"/"ultimately", no hedging stacks. Vary sentence length. Contractions.
     If a sentence sounds like a press release or a LinkedIn post, rewrite it. `ff render-email` prints a warning for
     the patterns it can detect; fix reads.json and re-run before sending.
7. `uv run ff render-email --packet <packet path from step 5> --reads reads.json --out briefing.html --md briefing.md`
   (seconds, no sims). Then send with the Gmail connector. To: the address in the `BRIEFING_TO` environment variable (`printenv BRIEFING_TO`, or the `BRIEFING_TO=` line in `.env`). Subject: `FF briefing — Week <N> — <YYYY-MM-DD>`.
   Pass the full contents of briefing.html as `htmlBody` and briefing.md as `body` (plain-text fallback). briefing.html
   is the action cards only (well under 20 KB, one tag per line); the full detail tables are in briefing.md. There is no attachment
   or FILE: syntax. Read briefing.html in order, from the first line to the last, and paste every line verbatim, including
   the closing `</body></html>`. Before sending, run `wc -c briefing.html` and compare it to the length of what you
   assembled; if they differ, re-read the file and fix the body rather than sending a truncated email.
   Send exactly one email.
   If Gmail is unavailable, fall back to `uv run ff email briefing.md --html briefing.html` (needs GMAIL_USER/GMAIL_APP_PASSWORD),
   and if that also fails, print the full briefing.md so it's in the run log.
8. After a successful send, run `uv run ff heartbeat` (dead-man's switch; no-op if HEALTHCHECK_URL is unset).
9. Record projections for accuracy tracking: `uv run ff log-projections`, then commit and push ONLY that directory to the
   `projlog` branch (never main) with exactly this sequence (the clone may be on a detached HEAD; this handles it):
   `git fetch origin projlog && git checkout -B projlog FETCH_HEAD || git checkout -B projlog ; git add -f data/projlog && git -c user.name=ff-routine -c user.email=routine@ff.local commit -m "projlog: week <N> <date>" ; git push origin projlog`
   If there is nothing to commit, or the push fails, say so in one line and move on. This is the single exception to the
   no-commit rule. Never commit anything else; delete generated files (briefing.html, reads.json) rather than committing them.
10. Scope: do not audit Gmail history, git history, or other routines. Earlier emails with the same subject are expected
    (tests, re-runs); commits already on origin are not your concern. Send at most one push notification, and only for a
    same-day action item (e.g. a starter ruled out) or a failure.
11. Do not touch ESPN beyond reads.

## If anything fails
If any step errors and cannot be recovered with one retry (dead cookies, a source down, a crash in `ff`), STOP the normal
flow and instead email Dustin (same Gmail path) with subject `FF briefing FAILED — <YYYY-MM-DD>` containing:
which step failed, the exact error text, what you tried, and the one action Dustin should take (e.g. refresh cookies per
scripts/setup_cookies.md, or "no action, source was down"). If a partial briefing exists (some leagues succeeded), include it
below the failure report. Then run `uv run ff heartbeat --fail`. Never end a run silently.
