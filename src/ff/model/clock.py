"""Where in the week are we? Locks players whose game has started so the optimizer only moves what ESPN still allows,
and banks actual points for the matchup math.

ESPN's `current_week` stays on the old week until Tuesday, so Monday-morning briefings would otherwise recommend swapping
players who played Sunday. A player is locked when the kickoff (from the ESPN scoreboard lines) has passed, the game state is
in/post, or they already have points."""
from __future__ import annotations

from datetime import UTC, datetime

from .projections import PlayerProj


def _kickoff(line: dict | None) -> datetime | None:
    k = (line or {}).get("kickoff")
    if not k:
        return None
    try:
        return datetime.fromisoformat(k.replace("Z", "+00:00"))
    except ValueError:
        return None


def game_phase(line: dict | None, actual: float, now: datetime) -> str:
    """'pre' | 'in' | 'post' for one player's NFL game this week."""
    st = (line or {}).get("state")
    if st in ("in", "post"):
        return st
    ko = _kickoff(line)
    if ko is not None and now >= ko:
        # started per the clock; cached state may be stale. ~3.5h after kickoff call it done.
        return "post" if (now - ko).total_seconds() > 3.5 * 3600 else "in"
    if actual and actual != 0:
        return "post"
    return "pre"


def apply_clock(players: list[PlayerProj], rows: list[dict], lines: dict, now: datetime | None = None, free_agents: bool = False) -> None:
    """Mutates projections in place. Rostered locked players: mu = points banked (post) or banked + half projection (in),
    variance shrunk; they can't move slots. Locked free agents: this-week value is unobtainable, so mu = 0 (ROS untouched)."""
    now = now or datetime.now(UTC)
    actual_by_id = {r["espn_id"]: float(r.get("actual_week") or 0.0) for r in rows}
    for p in players:
        if p.bye:
            continue
        ph = game_phase(lines.get(p.team), actual_by_id.get(p.espn_id, 0.0), now)
        if ph == "pre":
            continue
        p.locked = True
        p.actual = actual_by_id.get(p.espn_id, 0.0)
        p.sigma_ros = p.sigma
        if free_agents:
            p.mu, p.sigma, p.p_zero = 0.0, 0.0, 0.0
        elif ph == "post":
            p.mu, p.sigma, p.p_zero = p.actual, 0.0, 0.0
        else:
            p.mu, p.sigma, p.p_zero = p.actual + 0.5 * p.mu * (1 - p.p_zero), p.sigma * 0.6, 0.0
        p.flags.append(f"clock:{ph}")


def week_state(mine: list[PlayerProj], theirs: list[PlayerProj], non_starter: set[str]) -> dict:
    """Phase of the fantasy matchup plus what is still to play on each side."""
    def side(ps):
        st = [p for p in ps if p.slot not in non_starter]
        left = [p.name for p in st if not p.locked]
        banked = round(sum(p.actual or 0.0 for p in st if p.locked), 1)
        return st, left, banked
    my_st, my_left, my_pts = side(mine)
    op_st, op_left, op_pts = side(theirs)
    n_locked = sum(1 for p in my_st + op_st if p.locked)
    if not my_st and not op_st:
        phase = "pre"
    elif n_locked == 0:
        phase = "pre"
    elif my_left or op_left:
        phase = "in_progress"
    else:
        phase = "final"
    return {"phase": phase, "my_points": my_pts, "opp_points": op_pts, "my_left": my_left, "opp_left": op_left}
