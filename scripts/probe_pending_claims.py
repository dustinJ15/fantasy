"""Read-only probe for B20: what ESPN's `mPendingTransactions` view says about the waiver claims I have in.

    uv run python scripts/probe_pending_claims.py [--league L1]

`espn.waiver_run_ts` only ever read the `processDate` off these records; before `espn.pending_claims` parses them
this prints every WAIVER record raw (mine marked), so the field names (the add, the drop, the bid, the status, the
scoring period) come off a captured record and are not guessed. Run it on a Tuesday or Wednesday morning with a
claim placed in the app. Nothing here writes.
"""
from __future__ import annotations

import json
import sys

from ff.config import leagues
from ff.sources import espn


def main(only: str | None = None) -> None:
    for ref in leagues(only):
        lg = espn.connect(ref)
        me = espn.my_team(lg, ref.team_id)
        my_id = me.team_id if me else None
        raw = lg.espn_request.league_get(params={"view": "mPendingTransactions"})
        txs = raw.get("pendingTransactions") or []
        kinds = sorted({str(tx.get("type")) for tx in txs})
        print(f"\n== {ref.name}: {lg.settings.name}, week {lg.current_week}, my team id {my_id}; "
              f"{len(txs)} pending records, types {kinds or ['none']}")
        for tx in txs:
            if tx.get("type") != "WAIVER":
                continue
            mine = tx.get("teamId") == my_id
            who = "(MINE)" if mine else f"(team {tx.get('teamId')})"
            print(f"\n-- WAIVER {tx.get('id')} {who}")
            print(json.dumps(tx, indent=1, sort_keys=True, default=str))
            for item in tx.get("items") or []:
                pid = item.get("playerId")
                name = next((p.name for t in lg.teams for p in t.roster if p.playerId == pid), None)
                print(f"   item {item.get('type')}: playerId {pid}" + (f" = {name} (rostered)" if name else " (not on a roster: the wire)"))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--league") + 1] if "--league" in sys.argv else None)
