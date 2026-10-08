"""Should the trade-offer backstop poll ESPN right now? (.github/workflows/trade-poll.yml, first step)

The workflow's cron is a plain hourly `20 * * * *`: GitHub rejects month/day lists mixed with ranges and delivers a
quiet repo's schedule roughly every 3 hours anyway, so the real gate lives here, in Denver time. A scheduled run
polls when it is the season (Sep-Jan) and not the small hours in Denver (QUIET_HOURS, 1-5 AM; the 6 AM briefing
lists every pending offer, so an offer sent at 2 AM waits for it and nothing else). Every weekday polls: ESPN takes
trade proposals seven days a week, and Monday evening after the night game is as busy as Sunday's. Before
2026-10-08 the gate was `date -u` arithmetic that skipped Monday and UTC hours 0-11, so every Denver evening from
6 PM (MDT) on, prime trade time, waited for the morning briefing (TODO C3).

A manual run (`workflow_dispatch`) always polls. The `--new-since` window the poll uses stays 6h, wider than the
3h cadence, and the offer-id cache makes overlap free, so this gate only decides when to spend a run.

    python3 scripts/trade_poll_gate.py --event schedule            # prints run=true|false, appends to $GITHUB_OUTPUT
    python3 scripts/trade_poll_gate.py --event schedule --now 2026-10-12T02:00:00Z   # a what-if

Stdlib only: the runner has python3 and no `uv sync` yet when this runs.
"""
import argparse
import os
import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

DENVER = ZoneInfo("America/Denver")
SEASON_MONTHS = {9, 10, 11, 12, 1}   # Sep-Jan, by the Denver calendar
QUIET_HOURS = range(1, 6)            # Denver local hours with no poll: 01:00-05:59; the briefing runs at 6


def decide(now: datetime, event: str = "schedule") -> tuple[bool, str]:
    """(poll?, why) for a workflow event at `now` (aware; naive is read as UTC)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    local = now.astimezone(DENVER)
    stamp = local.strftime("%a %Y-%m-%d %H:%M %Z")
    if event != "schedule":
        return True, f"{event}: manual runs always poll ({stamp})"
    if local.month not in SEASON_MONTHS:
        return False, f"off season: month {local.month} ({stamp})"
    if local.hour in QUIET_HOURS:
        return False, f"quiet hours in Denver: {local.hour:02d}:xx ({stamp})"
    return True, f"in season, Denver {local.hour:02d}:xx ({stamp})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", "schedule"), help="GitHub event name (schedule, workflow_dispatch)")
    ap.add_argument("--now", help="ISO-8601 instant to decide for (default: now)")
    args = ap.parse_args(argv)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)
    run, why = decide(now, args.event)
    line = f"run={'true' if run else 'false'}"
    print(f"{line}  {why}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
