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
3. Research, one or two WebSearches per player in `give` and `get` (up to ~8 per offer): injury and the return timeline,
   role change (last week's snap share and route share, a depth chart move, a QB change), coach comments this week.
   If something changes the picture, write `overrides.json` with the same keys the briefing uses:
   `{"<espn_id>": {"p_zero": <0-1>, "mu_mult": <0.5-1.5>, "weeks_out": <games or "season">, "ros_mult": <0.5-1.5>, "note": "<source + one-line reason>"}}`
   `p_zero` and `mu_mult` are this week only (sit risk, and what he scores when he plays). An offer is priced on the rest
   of the season, so a hurt player on either side needs `weeks_out`: the games he still misses counted from this week,
   `"season"` for an ACL, Achilles or season-ending surgery; without it the math has an IR player back in four games
   and an Out player back next week. Write `ros_mult` when he comes back diminished or his role changed, never for
   this week's snap count. The `note` is shown next to the player. Then re-run
   `uv run ff packet --overrides overrides.json --sims 1500` (timeout 600000) and note the packet path it prints;
   otherwise use the newest file in `data/packets/`. Wind is already in the numbers; do not search for it.
4. Write `reads.json`, one entry per league that has an offer, keyed by `league` (L1/L2/L3):
   `{"L2": {"read": "<1-2 plain sentences of what the research adds that the math could not know>",
            "items": {"<row id>": {"verdict": "do|skip|amend", "note": "<one short reason, required unless do>"}},
            "reply": "<what Dustin sends the rival>", "reply_to": "<rival team name>"}}`
   **Rule on the offer row in `items`, do not argue with the verdict in `read`.** Each offer in the step 2 JSON carries
   its row id as `row_id` (`offer:garrett-wilson`); copy it exactly. `do` confirms the verdict and
   needs no note. `amend` keeps the verdict and attaches your caveat ("accept, but only if his ankle is a full go
   Friday"). `skip` strikes the verdict and the note says what Dustin does instead ("decline, he is in a boot"). A
   number the research changes (he is out for the year) belongs in overrides.json in step 3, where the verdict is
   re-derived; `skip` is for judgment the math has no column for. The email has to end with one answer per offer, not a
   badge saying accept and a paragraph underneath saying don't. `ff render-email` warns about a typo'd id or a
   missing note; fix reads.json and re-run before sending.
   `reply` rules follow the ruled answer (the verdict after your ruling): for `decline` a polite one-liner; for `counter` a concrete tweak (name the player swap); for `accept`
   omit it. A `counter` verdict carries `counter` (`give`, `get`): the one swap the math found fair both ways. Write the
   reply from that swap; do not invent a different one, and if `counter` is null say the price is off and leave the
   door open rather than naming players. Same voice as the briefing `paste`: texting a coworker, first person, one or two sentences, no em dashes,
   never mention projections, models, points per week, or Claude. `ff render-email` warns on the tells it can detect.
5. `uv run ff render-email --packet <packet path> --reads reads.json --only-incoming --out offer.html --md offer.md`.
   Send with the Gmail connector. To: the address in the `BRIEFING_TO` environment variable (`printenv BRIEFING_TO`, or the `BRIEFING_TO=` line in `.env`). Subject: `FF trade offer — <league name> — <YYYY-MM-DD>`
   (if more than one league has an offer, join the names with " + "). `htmlBody` = full contents of offer.html,
   `body` = offer.md. offer.html is small and has one tag per line: read it in order and paste every line verbatim,
   including the closing `</body></html>`. Before sending, run `wc -c offer.html` and compare it to the length of what
   you assembled; if they differ, re-read the file and fix the body rather than sending a truncated email.
   Send exactly one email. Then delete offer.html, offer.md, reads.json, overrides.json.
6. Scope: no heartbeat, no projlog commit, no git commits at all, do not audit Gmail or git history, do not touch ESPN
   beyond reads. Dustin accepts or declines in the ESPN app himself.

## If anything fails
If a step errors and one retry does not fix it, email Dustin (subject `FF trade offer FAILED — <YYYY-MM-DD>`) with the step,
the exact error, and the one action to take. Never end a run silently.
