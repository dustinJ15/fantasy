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
   - each starter in any league's `lineup_win.slots` whose flags include QUESTIONABLE/DOUBTFUL/OUT or `sleeper:`,
   - the top 3 waiver targets per league (is the role change real?).
   Note the day: Tue/Wed = waivers matter most; Fri/Sat/Sun = final designations and weather; Thu = TNF players;
   Mon = only Monday-night players can still move (each league's `week_state` in the packet says the phase, the score so
   far, and who is left to play); do not research or suggest lineup changes for players marked `locked`.
4. Write `overrides.json` at repo root containing only players where news moves the picture:
   `{"<espn_id>": {"p_zero": <0-1>, "mu_mult": <0.5-1.5>, "note": "<source + one-line reason>"}}`
   p_zero guide: full practice + no tag 0.03; Q + limited Fri 0.25; Q + DNP Fri 0.5; Doubtful 0.85; Out/IR 1.0.
   If nothing changed, write `{}`.
5. `uv run ff briefing --overrides overrides.json --sims 2000 --out briefing.md` (also 3-5 minutes; timeout 600000).
   Read briefing.md and note the packet path printed on the last line (`packet data/packets/<date>.json`).
6. Write `reads.json` at repo root — your judgment, as parameters. One entry per league keyed by its `name` from
   leagues.toml (L1/L2/L3); omit a league if you have nothing to add:
   `{"L1": {"read": "<1-2 plain sentences: confirm or adjust the checklist based on your research>",
            "paste": "<exact message Dustin can paste to the rival, only if a trade is worth sending>", "paste_to": "<rival team name>"}}`
   Do NOT edit briefing.md or the HTML by hand. If research changes a checklist item (a player ruled out, a role change),
   that belongs in overrides.json (re-run step 5); the override `note` shows up next to the player in the email.
   Dustin reads this on a phone: keep each read short.
   Voice (both `read` and `paste`): write like a guy texting a coworker about football, not like an assistant.
   - The `paste` message goes to a real person in Dustin's league. One or two casual sentences, first person, lowercase is fine,
     say what you want and why it helps *them*, end with a question. Example: "hey, any interest in Rice + Montgomery for Henry?
     you're thin at WR and I could use the RB. no worries if not". Never mention projections, models, points per week, or Claude.
   - Avoid the known AI tells: no em dashes (use a comma or a period), no "not X, but Y" reframes, no lists of three, no
     "label: explanation" openers, no "worth noting"/"that said"/"ultimately", no hedging stacks. Vary sentence length. Contractions.
     If a sentence sounds like a press release or a LinkedIn post, rewrite it. `ff render-email` prints a warning for
     the patterns it can detect; fix reads.json and re-run before sending.
7. `uv run ff render-email --packet <packet path from step 5> --reads reads.json --out briefing.html --md briefing.md`
   (seconds, no sims). Then send with the Gmail connector. To: dbj2297@gmail.com. Subject: `FF briefing — Week <N> — <YYYY-MM-DD>`.
   Pass the full contents of briefing.html as `htmlBody` and briefing.md as `body` (plain-text fallback). Read
   briefing.html with the Read tool in halves if needed, then paste it verbatim; there is no attachment or FILE: syntax.
   Send exactly one email.
   If Gmail is unavailable, fall back to `uv run ff email briefing.md --html briefing.html` (needs GMAIL_USER/GMAIL_APP_PASSWORD),
   and if that also fails, print the full briefing.md so it's in the run log.
8. After a successful send, run `uv run ff heartbeat` (dead-man's switch; no-op if HEALTHCHECK_URL is unset).
9. Record projections for accuracy tracking: `uv run ff log-projections`, then commit and push ONLY that directory with
   exactly this sequence (the clone may be on a detached HEAD; this handles it):
   `git add data/projlog && git -c user.name=ff-routine -c user.email=routine@ff.local commit -m "projlog: week <N> <date>" ; git fetch origin main && git rebase FETCH_HEAD && git push origin HEAD:main`
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
