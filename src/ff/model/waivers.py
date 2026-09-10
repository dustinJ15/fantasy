"""Free-agent ranking, FAAB max-bid, streamers, handcuffs."""
from __future__ import annotations

from .projections import PlayerProj
from .vbd import own_starter_value


def _odd(x: int) -> int:
    x = max(int(round(x)), 0)
    return x if x % 2 == 1 or x == 0 else x + 1


def faab_bid(delta_over_starter: float, weeks_remaining: int, budget_remaining: int, is_streamer: bool,
             league_max_remaining: int | None = None) -> int:
    """
    Rule-of-thumb sizing (4for4 / FantasyPros consensus):
    - streamers (K/DST/1-week plays): $1-2
    - bench flyers (no lineup improvement): <=3% of budget
    - real upgrades: scale with points gained per week * weeks left, cap ~35% unless league-winner
    - league-winner (>=8 pts/wk over your starter): 50-80%
    Odd numbers beat round-number clustering.
    """
    if budget_remaining <= 0:
        return 0
    if is_streamer:
        return min(budget_remaining, 1 if delta_over_starter < 3 else 3)
    if delta_over_starter <= 0:
        return _odd(min(budget_remaining * 0.03, budget_remaining))
    season_value = delta_over_starter * max(weeks_remaining, 1)
    frac = min(0.02 + season_value / 120.0, 0.35)
    if delta_over_starter >= 8:
        frac = 0.6 if weeks_remaining >= 8 else 0.45
    bid = _odd(budget_remaining * frac)
    if league_max_remaining is not None and delta_over_starter >= 8:
        bid = max(bid, min(budget_remaining, league_max_remaining + 1))
    return min(bid, budget_remaining)


def rank_free_agents(fas: list[PlayerProj], my_lineup: dict[str, list[PlayerProj]], my_bench: list[PlayerProj],
                     repl: dict[str, float], weeks_remaining: int, budget_remaining: int, trending: dict[str, int],
                     league_max_remaining: int | None = None, top: int = 15) -> list[dict]:
    worst_bench = min((p.mu_ros for p in my_bench), default=0.0)
    out = []
    for p in fas:
        if p.bye and weeks_remaining <= 1:
            continue
        if p.mu_ros < 0.4 * repl.get(p.pos, 0.0):
            continue  # not a real fantasy asset, however much he's trending
        d_start, slot = own_starter_value(p, my_lineup)
        d_bench = p.mu_ros - worst_bench
        vorp = p.mu_ros - repl.get(p.pos, 0.0)
        streamer = p.pos in ("K", "D/ST")
        # Bench-only value counts only if the player is close to startable; backups at one-starter
        # positions (QB/K/DST) are near-worthless.
        near = d_start > -4 or vorp > 2
        bench_val = 0.5 * max(d_bench, 0) if (near and p.pos not in ("QB", "K", "D/ST")) else 0.0
        trend = min(trending.get(str(p.espn_id), 0) / 20000, 3)
        score = max(d_start, 0) * 3 + bench_val + max(vorp, 0) + trend
        if streamer:
            score = d_start  # only worth listing if clearly better than my current K/DST this week
            if score < 1.0:
                continue
        if score <= 0.2:
            continue
        bid = faab_bid(d_start if not streamer else p.mu, weeks_remaining, budget_remaining, streamer, league_max_remaining) if budget_remaining > 0 else 0
        why = []
        if d_start > 0: why.append(f"+{d_start:.1f}/wk over your {slot}")
        elif d_bench > 0: why.append(f"+{d_bench:.1f}/wk over worst bench")
        if vorp > 0: why.append(f"VORP {vorp:.1f}")
        if trending.get(str(p.espn_id)): why.append(f"trending +{trending[str(p.espn_id)]:,} adds/24h")
        why += p.flags
        out.append({"espn_id": p.espn_id, "name": p.name, "pos": p.pos, "team": p.team, "mu_week": p.mu, "mu_ros": p.mu_ros,
                    "delta_over_starter": d_start, "slot": slot, "vorp": round(vorp, 2), "bid": bid, "score": round(score, 2),
                    "streamer": streamer, "why": why, "percent_owned": p.sources.get("percent_owned")})
    out.sort(key=lambda x: -x["score"])
    skill = [o for o in out if not o["streamer"]][:top]
    streamers = [o for o in out if o["streamer"]][:3]
    return skill + streamers


def handcuffs(my_starters_rb: list[PlayerProj], pool: list[PlayerProj]) -> list[dict]:
    """Backups on the same NFL team as my RB starters, with a crude value estimate."""
    out = []
    for s in my_starters_rb:
        mates = [p for p in pool if p.pos == "RB" and p.team == s.team and p.espn_id != s.espn_id]
        mates.sort(key=lambda p: -p.mu_ros)
        if mates:
            b = mates[0]
            p_miss = 0.25  # ~1 in 4 chance a starting RB misses meaningful time over a half-season
            value = p_miss * max(s.mu_ros * 0.8 - b.mu_ros, 0)
            out.append({"starter": s.name, "handcuff": b.name, "owner_team_id": b.fantasy_team_id, "est_value": round(value, 2)})
    return out
