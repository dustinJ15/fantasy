"""Read-only probe for the three things docs/plans/injured-player-decision.md could not verify without ESPN cookies.

    uv run python scripts/probe_injuries.py [--league L1]

For every rostered player on my teams with a designation (and two healthy ones for comparison) it prints what ESPN
says: injuryStatus, the `injured` flag, whether the IR slot is in eligibleSlots, the lineup slot, this week's and the
season's projection, points banked so far and the sum of the remaining weekly projections. Read it to answer:
  1. is "IR" in eligibleSlots only for hurt players (a real eligibility signal) or for everyone?
  2. what does ESPN do to proj_season when a player goes on IR?
  3. is proj_season a full-season figure (banked + remaining) or the remaining total? `mu_ros` divides it by weeks
     remaining as if it were the latter.
"""
from __future__ import annotations

import sys

from ff.config import leagues
from ff.sources import espn


def main(only: str | None = None) -> None:
    for ref in leagues(only):
        lg = espn.connect(ref)
        me = espn.my_team(lg, ref.team_id)
        week = lg.current_week
        last = len(lg.settings.matchup_periods)
        print(f"\n== {ref.name}: {lg.settings.name}, week {week}, my team {me.team_name if me else '?'}")
        print(f"{'player':24} {'status':16} inj IRel slot  wk_proj season  banked remain_proj")
        healthy_shown = 0
        for p in (me.roster if me else []):
            hurt = p.injuryStatus not in (None, "ACTIVE", "NORMAL")
            if not hurt and healthy_shown >= 2:
                continue
            healthy_shown += 0 if hurt else 1
            banked = sum(float((p.stats.get(w) or {}).get("points", 0) or 0) for w in range(1, week))
            remain = sum(float((p.stats.get(w) or {}).get("projected_points", 0) or 0) for w in range(week, last + 1))
            print(f"{p.name:24} {str(p.injuryStatus):16} {int(bool(getattr(p, 'injured', False)))}   {int('IR' in p.eligibleSlots)}    "
                  f"{p.lineupSlot:5} {float((p.stats.get(week) or {}).get('projected_points', 0) or 0):7.1f} "
                  f"{p.projected_total_points:7.1f} {banked:7.1f} {remain:11.1f}")


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--league") + 1] if "--league" in sys.argv else None)
