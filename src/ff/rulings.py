"""Memory for Claude's `skip` rulings on trade rows, so a package Dustin passed on does not come back every morning.

The scan re-derives the same offers daily from the same rosters; the only state it had was ESPN's pending list.
`ff render-email` records each skipped trade row here; `packet.build` drops candidates skipped in the last
`SKIP_DAYS`. The file lives under data/projlog, which the routine already pushes to the `projlog` branch and
`scripts/cloud_setup.sh` restores on the next clone. A rival roster change that makes the package different (a new
`get` set) is a new row and is not skipped.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .config import DATA_DIR

SKIPS_PATH = DATA_DIR / "projlog" / "skipped_trades.json"
PUSHES_PATH = DATA_DIR / "projlog" / "pushed_trades.json"
SKIP_DAYS = 14


def skip_key(league: str, get: list[str]) -> str:
    return f"{league}|" + "+".join(sorted(get))


def _load(path: Path) -> dict[str, dict]:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def load_skips(path: Path = SKIPS_PATH) -> dict[str, dict]:
    return _load(path)


def load_pushes(path: Path = PUSHES_PATH) -> dict[str, dict]:
    return _load(path)


def record_skips(packet: dict, reads: dict, path: Path = SKIPS_PATH, today: date | None = None) -> list[str]:
    """Write every `skip` ruling on a trade row into the file; returns the keys added."""
    from .report import apply_reads, todos  # local import: report imports nothing from here, keep it that way
    today = today or date.today()
    skips = load_skips(path)
    added = []
    for lg in packet.get("leagues") or []:
        r = (reads or {}).get(lg["name"]) or {}
        for row in apply_reads(todos(lg), r):
            if row["kind"] != "trade" or row.get("ruling") != "skip":
                continue
            key = skip_key(lg["name"], row.get("get") or [])
            skips[key] = {"date": today.isoformat(), "league": lg["name"], "rival": row.get("rival"),
                          "give": row.get("give") or [], "get": row.get("get") or [], "note": row.get("ruling_note")}
            added.append(key)
    if added:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(skips, indent=1))
    return added


def drop_recently_skipped(cands: list[dict], skips: dict[str, dict], league: str, today: date | None = None,
                          days: int = SKIP_DAYS) -> list[dict]:
    today = today or date.today()
    out = []
    for c in cands:
        s = skips.get(skip_key(league, c.get("get") or []))
        if s:
            try:
                when = date.fromisoformat(s.get("date", ""))
            except ValueError:
                when = today
            if today - when <= timedelta(days=days):
                continue
        out.append(c)
    return out


# ---------- pushes: "this one is really good, keep asking until he sends it or says no" ----------

def record_pushes(packet: dict, reads: dict, path: Path = PUSHES_PATH, today: date | None = None) -> list[str]:
    """Open, close or keep every push. A trade row is pushed when the math flags it (`must_try`) or Claude rules
    `push` on it. A push closes when the package shows up among Dustin's own pending offers (sent), or when he
    rules `skip` on it (which the skip memory also records). Returns "<key>: opened|sent|skipped" lines."""
    from .report import apply_reads, todos
    today = today or date.today()
    pushes = _load(path)
    events = []
    for lg in packet.get("leagues") or []:
        r = (reads or {}).get(lg["name"]) or {}
        sent_keys = {skip_key(lg["name"], t.get("get") or []) for t in lg.get("outgoing_trades") or []}
        for key in sent_keys:
            if pushes.get(key, {}).get("status") == "open":
                pushes[key]["status"], pushes[key]["closed"] = "sent", today.isoformat()
                events.append(f"{key}: sent")
        for row in apply_reads(todos(lg), r):
            if row["kind"] != "trade":
                continue
            key = skip_key(lg["name"], row.get("get") or [])
            cur = pushes.get(key)
            if row.get("ruling") == "skip":
                if cur and cur.get("status") == "open":
                    cur["status"], cur["closed"], cur["skip_note"] = "skipped", today.isoformat(), row.get("ruling_note")
                    events.append(f"{key}: skipped")
                continue
            if row.get("ruling") == "push" or row.get("push"):  # `push` on the row: the math flagged it, or it is remembered
                if cur and cur.get("status") in ("sent", "skipped") and cur.get("closed") == today.isoformat():
                    continue  # closed this morning (sent, or skipped with a reason): the same row does not reopen it
                if cur and cur.get("status") == "open":
                    cur["last"] = today.isoformat()
                    if row.get("ruling") == "push" and row.get("ruling_note"):
                        cur["note"], cur["source"] = row["ruling_note"], "claude"
                    continue
                pushes[key] = {"status": "open", "since": today.isoformat(), "last": today.isoformat(), "league": lg["name"],
                               "rival": row.get("rival"), "give": row.get("give") or [], "get": row.get("get") or [],
                               "source": "claude" if row.get("ruling") == "push" else "math",
                               "note": row.get("ruling_note") if row.get("ruling") == "push" else None}
                events.append(f"{key}: opened")
    if events:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(pushes, indent=1))
    return events


def mark_pushed(cands: list[dict], pushes: dict[str, dict], league: str, today: date | None = None) -> list[dict]:
    """Attach the open push (since, days asked, note) to the scan candidates that match one. A push the scan no
    longer produces (rosters changed) simply stops showing; nothing here invents a trade."""
    today = today or date.today()
    for c in cands:
        p = pushes.get(skip_key(league, c.get("get") or []))
        if p and p.get("status") == "open":
            try:
                since = date.fromisoformat(p.get("since", ""))
            except ValueError:
                since = today
            c["pushed"] = {"since": since.isoformat(), "days": (today - since).days + 1, "note": p.get("note"), "source": p.get("source")}
    return cands


def record_rulings(packet: dict, reads: dict, skips_path: Path = SKIPS_PATH, pushes_path: Path = PUSHES_PATH,
                   today: date | None = None) -> list[str]:
    """Everything `ff render-email` remembers from one morning's reads."""
    return [f"skip {k}" for k in record_skips(packet, reads, skips_path, today)] + \
           [f"push {e}" for e in record_pushes(packet, reads, pushes_path, today)]


# ---------- outcomes: what ESPN did with the offers I actually sent ----------
# The first real acceptance data this repo has. Every offer of mine that shows in `outgoing_trades` is opened here the
# morning it is seen and closed the morning it is gone: accepted when the players I asked for are on my roster,
# expired when its expiry passed, declined otherwise. The scan reads it for a per-rival prior and a recency factor.

OUTCOMES_PATH = DATA_DIR / "projlog" / "offer_outcomes.json"
RECENT_DAYS = 7
CLOSED = ("accepted", "declined", "expired")


def load_outcomes(path: Path = OUTCOMES_PATH) -> dict[str, dict]:
    return _load(path)


def record_outcomes(packet: dict, path: Path = OUTCOMES_PATH, today: date | None = None) -> list[str]:
    """Open an entry for every offer of mine pending on ESPN; close the ones that are not pending any more.
    A league whose pending list could not be read closes nothing (an empty list there means nothing)."""
    today = today or date.today()
    outs = load_outcomes(path)
    events = []
    for lg in packet.get("leagues") or []:
        league = lg["name"]
        pending = {str(t["id"]): t for t in lg.get("outgoing_trades") or [] if t.get("id") is not None}
        for oid, t in pending.items():
            key = f"{league}|{oid}"
            if key not in outs:
                outs[key] = {"status": "open", "league": league, "rival": t.get("rival"), "rival_team_id": t.get("rival_team_id"),
                             "give": list(t.get("give") or []), "get": list(t.get("get") or []),
                             "opened": today.isoformat(), "expires": t.get("expires_iso")}
                events.append(f"{key}: opened")
        if lg.get("pending_trades_error"):
            continue
        roster_names = {p["name"] for p in lg.get("roster") or []}
        for key, o in outs.items():
            if o.get("league") != league or o.get("status") != "open" or key.split("|", 1)[1] in pending:
                continue
            got = [n for n in o.get("get") or [] if n in roster_names]
            gave = [n for n in o.get("give") or [] if n in roster_names]
            if got and not gave:
                status = "accepted"
            elif (o.get("expires") or "")[:10] and o["expires"][:10] < today.isoformat():
                status = "expired"
            else:
                status = "declined"
            o["status"], o["closed"] = status, today.isoformat()
            events.append(f"{key}: {status}")
    if events:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(outs, indent=1))
    return events


def history(outs: dict[str, dict], league: str, today: date | None = None) -> dict[int, dict]:
    """Per rival team id, what his answers so far say: `recent_decline` (a no or an expiry in the last RECENT_DAYS)
    and `prior`, his acceptance rate with a half-count of smoothing, only once he has answered twice."""
    today = today or date.today()
    tally: dict[int, dict] = {}
    for o in outs.values():
        if o.get("league") != league or o.get("status") not in CLOSED or o.get("rival_team_id") is None:
            continue
        rid = int(o["rival_team_id"])
        t = tally.setdefault(rid, {"n": 0, "accepted": 0, "recent_decline": False})
        t["n"] += 1
        t["accepted"] += o["status"] == "accepted"
        try:
            closed = date.fromisoformat(o.get("closed", ""))
        except ValueError:
            closed = today
        if o["status"] != "accepted" and today - closed <= timedelta(days=RECENT_DAYS):
            t["recent_decline"] = True
    return {rid: {"n": t["n"], "recent_decline": t["recent_decline"],
                  "prior": round((t["accepted"] + 0.5) / (t["n"] + 1), 3) if t["n"] >= 2 else None} for rid, t in tally.items()}
