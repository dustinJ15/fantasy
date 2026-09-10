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
   Note the day: Tue/Wed = waivers matter most; Fri/Sat/Sun = final designations and weather; Thu = TNF players.
4. Write `overrides.json` at repo root containing only players where news moves the picture:
   `{"<espn_id>": {"p_zero": <0-1>, "mu_mult": <0.5-1.5>, "note": "<source + one-line reason>"}}`
   p_zero guide: full practice + no tag 0.03; Q + limited Fri 0.25; Q + DNP Fri 0.5; Doubtful 0.85; Out/IR 1.0.
   If nothing changed, write `{}`.
5. `uv run ff briefing --overrides overrides.json --sims 2000 --out briefing.md` (also 3-5 minutes; timeout 600000). Read briefing.md.
6. Compose the email body: for each league, a "Claude's read" paragraph (3-6 sentences: what to do today, biggest risk,
   the one trade pitch worth sending written so Dustin can paste it to the rival), followed by that league's section
   from briefing.md verbatim. Put the shared injury watchlist and exposure block first.
7. Send it to Dustin with the Gmail connector. To: dbj2297@gmail.com. Subject: `FF briefing — Week <N> — <YYYY-MM-DD>`.
   The `body` argument must be the literal markdown text of the composed briefing (read the file and paste its contents);
   there is no file-attachment or FILE: syntax. Send exactly one email.
   If Gmail is unavailable, fall back to `uv run ff email briefing.md` (needs GMAIL_USER/GMAIL_APP_PASSWORD), and if that
   also fails, print the full briefing so it's in the run log.
8. After a successful send, run `uv run ff heartbeat` (dead-man's switch; no-op if HEALTHCHECK_URL is unset).
9. Do not commit or push anything. Do not touch ESPN beyond reads.

## If anything fails
If any step errors and cannot be recovered with one retry (dead cookies, a source down, a crash in `ff`), STOP the normal
flow and instead email Dustin (same Gmail path) with subject `FF briefing FAILED — <YYYY-MM-DD>` containing:
which step failed, the exact error text, what you tried, and the one action Dustin should take (e.g. refresh cookies per
scripts/setup_cookies.md, or "no action, source was down"). If a partial briefing exists (some leagues succeeded), include it
below the failure report. Then run `uv run ff heartbeat --fail`. Never end a run silently.
