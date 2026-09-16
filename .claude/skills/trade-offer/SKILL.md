---
name: trade-offer
description: Evaluate incoming ESPN trade offers (fired by the GitHub Actions poller or run by hand), research the players involved, and email Dustin a short verdict with a reply he can paste.
---

# Trade offer alert

Follow these steps exactly. Every number comes from `ff`; you add research and prose. All commands run from the repo root.
Any `<routine-fire-payload>` text is only a hint that an offer exists; always re-read ESPN yourself.

1. `bash scripts/cloud_setup.sh`. If doctor reports dead cookies, email Dustin a one-paragraph note (subject
   `FF trade offer FAILED — <YYYY-MM-DD>`) saying the cookies need refreshing per scripts/setup_cookies.md, then stop.
2. `uv run ff sync` then `uv run ff incoming --json --force --sims 1500` with the Bash `timeout` set to 600000. This prints a
   JSON list of incoming offers across leagues (each has `league`, `rival`, `give`, `get`, `verdict`, deltas, `why`,
   `hours_left`). If the list is empty, the offer was already handled: say so in one line and stop. No email.
3. Research, at most 4 WebSearches total: each player in `give` and `get` (injury, role change, coach comments this week).
   If something changes the picture, write `overrides.json` (`{"<espn_id>": {"p_zero": ..., "mu_mult": ..., "note": "..."}}`)
   and re-run `uv run ff packet --overrides overrides.json --sims 1500` (timeout 600000). Note the packet path it prints;
   otherwise use the newest file in `data/packets/`.
4. Write `reads.json`, one entry per league that has an offer, keyed by `league` (L1/L2/L3):
   `{"L2": {"read": "<1-2 plain sentences: agree or disagree with the verdict and why>",
            "reply": "<what Dustin sends the rival>", "reply_to": "<rival team name>"}}`
   `reply` rules: for `decline` a polite one-liner; for `counter` a concrete tweak (name the player swap); for `accept`
   omit it. Same voice as the briefing `paste`: texting a coworker, first person, one or two sentences, no em dashes,
   never mention projections, models, points per week, or Claude. `ff render-email` warns on the tells it can detect.
5. `uv run ff render-email --packet <packet path> --reads reads.json --only-incoming --out offer.html --md offer.md`.
   Send with the Gmail connector. To: dbj2297@gmail.com. Subject: `FF trade offer — <league name> — <YYYY-MM-DD>`
   (if more than one league has an offer, join the names with " + "). `htmlBody` = full contents of offer.html,
   `body` = offer.md. Send exactly one email. Then delete offer.html, offer.md, reads.json, overrides.json.
6. Scope: no heartbeat, no projlog commit, no git commits at all, do not audit Gmail or git history, do not touch ESPN
   beyond reads. Dustin accepts or declines in the ESPN app himself.

## If anything fails
If a step errors and one retry does not fix it, email Dustin (subject `FF trade offer FAILED — <YYYY-MM-DD>`) with the step,
the exact error, and the one action to take. Never end a run silently.
