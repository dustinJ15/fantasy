"""ESPN league reads via espn-api. Read-only by design."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from espn_api.football import League
from espn_api.football.constant import POSITION_MAP
from espn_api.requests.espn_requests import ESPNAccessDenied, ESPNInvalidLeague

from ..config import LeagueRef, LeagueSettings, env

COOKIE_HELP = (
    "ESPN cookies missing or expired. See scripts/setup_cookies.md, then put ESPN_S2 and SWID in .env."
)

# Slots that hold starters. Everything else (BE, IR, '' ) is not a lineup slot.
NON_STARTER = {"BE", "IR", ""}


class CookieError(RuntimeError):
    pass


def connect(ref: LeagueRef) -> League:
    e = env()
    try:
        return League(league_id=ref.espn_id, year=e.season, espn_s2=e.espn_s2, swid=e.swid)
    except ESPNAccessDenied as exc:
        raise CookieError(f"{ref.name}: {COOKIE_HELP} ({exc})") from exc
    except ESPNInvalidLeague as exc:
        raise SystemExit(f"{ref.name}: invalid league id {ref.espn_id} ({exc})") from exc


def my_team(league: League, team_id: int | None = None):
    """The team from leagues.toml team_id, else the team owned by the SWID in .env."""
    if team_id is not None:
        for t in league.teams:
            if t.team_id == team_id:
                return t
    swid = (env().swid or "").strip().upper()
    for t in league.teams:
        for o in t.owners:
            oid = str(o.get("id", "")).upper() if isinstance(o, dict) else str(o).upper()
            if swid and oid == swid:
                return t
    return None


def settings(ref: LeagueRef, league: League) -> LeagueSettings:
    s = league.settings
    raw = league.espn_request.league_get(params={"view": "mSettings"})["settings"]
    slot_counts = {POSITION_MAP.get(int(k), str(k)): v for k, v in raw["rosterSettings"]["lineupSlotCounts"].items() if v}
    lineup = {k: v for k, v in slot_counts.items() if k not in NON_STARTER}
    scoring = {item["abbr"]: float(item["points"]) for item in s.scoring_format}
    ppr = scoring.get("REC", 0.0)
    total = s.reg_season_count + (len(s.matchup_periods) - s.reg_season_count)
    playoff_weeks = [mp for mp in range(s.reg_season_count + 1, len(s.matchup_periods) + 1)]
    return LeagueSettings(
        name=s.name,
        team_count=s.team_count,
        scoring=scoring,
        lineup_slots=lineup,
        bench_slots=slot_counts.get("BE", 0),
        ir_slots=slot_counts.get("IR", 0),
        reg_season_weeks=s.reg_season_count,
        playoff_team_count=s.playoff_team_count,
        playoff_weeks=playoff_weeks,
        matchup_periods={int(k): v for k, v in s.matchup_periods.items()},
        faab=bool(s.faab),
        faab_budget=int(s.acquisition_budget or 0),
        trade_deadline_ms=int(s.trade_deadline or 0),
        ppr=ppr,
    )


@dataclass
class PlayerRow:
    espn_id: int
    name: str
    pos: str
    team: str
    eligible: list[str]
    slot: str
    fantasy_team_id: int | None
    injury_status: str | None
    proj_week: float
    actual_week: float
    proj_season: float
    percent_owned: float
    pos_rank: int | None
    bye: bool


def _week_stat(p, week: int, key: str) -> float:
    st = p.stats.get(week) or {}
    return float(st.get(key, 0) or 0)


def roster_rows(league: League, week: int) -> list[PlayerRow]:
    rows: list[PlayerRow] = []
    for t in league.teams:
        for p in t.roster:
            rows.append(PlayerRow(
                espn_id=p.playerId, name=p.name, pos=p.position, team=p.proTeam,
                eligible=[s for s in p.eligibleSlots if s not in NON_STARTER],
                slot=p.lineupSlot, fantasy_team_id=t.team_id,
                injury_status=p.injuryStatus,
                proj_week=_week_stat(p, week, "projected_points"),
                actual_week=_week_stat(p, week, "points"),
                proj_season=p.projected_total_points,
                percent_owned=p.percent_owned, pos_rank=p.posRank,
                bye=(str(week) not in p.schedule) if p.schedule else False,
            ))
    return rows


def free_agent_rows(league: League, week: int, size: int = 300) -> list[PlayerRow]:
    rows = []
    for p in league.free_agents(week=week, size=size):
        rows.append(PlayerRow(
            espn_id=p.playerId, name=p.name, pos=p.position, team=p.proTeam,
            eligible=[s for s in p.eligibleSlots if s not in NON_STARTER],
            slot="FA", fantasy_team_id=None, injury_status=p.injuryStatus,
            proj_week=_week_stat(p, week, "projected_points"),
            actual_week=_week_stat(p, week, "points"),
            proj_season=p.projected_total_points,
            percent_owned=p.percent_owned, pos_rank=p.posRank,
            bye=(str(week) not in p.schedule) if p.schedule else False,
        ))
    return rows


def snapshot(ref: LeagueRef, league: League, week: int) -> dict[str, Any]:
    """Everything the model needs from one league, JSON-serializable."""
    me = my_team(league, ref.team_id)
    teams = []
    for t in league.teams:
        teams.append({
            "team_id": t.team_id, "name": t.team_name, "abbrev": t.team_abbrev,
            "owners": [o.get("displayName") if isinstance(o, dict) else str(o) for o in t.owners],
            "wins": t.wins, "losses": t.losses, "ties": t.ties,
            "points_for": t.points_for, "points_against": t.points_against,
            "faab_spent": t.acquisition_budget_spent, "waiver_rank": t.waiver_rank,
            "streak": f"{t.streak_type}{t.streak_length}", "seed": t.standing,
            "espn_playoff_pct": t.playoff_pct,
            "schedule": [getattr(o, "team_id", None) for o in t.schedule],
            "scores": t.scores, "outcomes": t.outcomes,
            "is_me": bool(me and t.team_id == me.team_id),
        })
    matchups = []
    for m in league.scoreboard(week):
        matchups.append({"home": m.home_team.team_id, "away": getattr(m.away_team, "team_id", None),
                         "home_proj": getattr(m, "home_projected", None), "away_proj": getattr(m, "away_projected", None),
                         "home_score": getattr(m, "home_score", None), "away_score": getattr(m, "away_score", None)})
    # FAAB history: all bids incl. losing ones
    bids = []
    try:
        for tx in league.transactions(types={"WAIVER", "WAIVER_ERROR"}):
            bids.append({"team_id": tx.team.team_id, "status": tx.status, "bid": tx.bid_amount,
                         "week": tx.scoring_period,
                         "items": [{"type": i.type, "player_id": i.playerId, "player": str(i.player)} for i in tx.items]})
    except Exception:
        pass
    return {
        "ref": asdict(ref), "week": week, "settings": asdict(settings(ref, league)),
        "my_team_id": me.team_id if me else None,
        "teams": teams, "matchups": matchups,
        "roster": [asdict(r) for r in roster_rows(league, week)],
        "free_agents": [asdict(r) for r in free_agent_rows(league, week)],
        "faab_bids": bids,
    }
