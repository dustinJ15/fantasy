"""Blend projection sources into a per-player weekly distribution.

X ~ (1 - p_zero) * N(mu, sigma^2) + p_zero * delta(0)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import ceil

import numpy as np

# Position-level projection-to-actual error (weekly points, PPR-ish). Rough priors from
# published accuracy studies; scaled by the FantasyPros rank-sd where available.
BASE_SIGMA = {"QB": 7.0, "RB": 6.5, "WR": 6.5, "TE": 5.0, "K": 4.0, "D/ST": 5.5}
# Coefficient of variation floor so that low projections still have spread.
CV_FLOOR = {"QB": 0.30, "RB": 0.45, "WR": 0.50, "TE": 0.55, "K": 0.45, "D/ST": 0.60}

# Injury designation -> probability of a zero (inactive). LLM may override via packet.
P_ZERO = {
    None: 0.02, "ACTIVE": 0.02, "NORMAL": 0.02, "PROBABLE": 0.08, "QUESTIONABLE": 0.30,
    "DOUBTFUL": 0.80, "OUT": 1.0, "INJURY_RESERVE": 1.0, "IR": 1.0, "PUP": 1.0, "SUSPENSION": 1.0,
    "SUS": 1.0, "NA": 1.0, "DNR": 1.0, "COV": 1.0,
}

# Designations that mean more than this week. NFL injured reserve and reserve/PUP are a four-game minimum, so 4 is a
# floor rather than an estimate; a suspension's length is public, so Claude sets it in overrides. Single-week
# designations fall out of `p_zero` on their own (Questionable is 0.3 of a game, Doubtful 0.8, Out 1.0).
MULTI_WEEK = {"INJURY_RESERVE": 4, "IR": 4, "PUP": 4, "NA": 1, "DNR": 1, "COV": 1, "SUSPENSION": 1, "SUS": 1}
# Sleeper's roster status (not its injury designation) is the freshest "he is on NFL IR" signal.
SLEEPER_ROSTER_MULTI_WEEK = {"Injured Reserve": 4, "Physically Unable to Perform": 4, "Non Football Injury": 4}
ACTIVE_STATUSES = (None, "", "ACTIVE", "NORMAL")

FLEX_LABELS = {"RB/WR/TE", "RB/WR", "WR/TE", "OP"}


@dataclass
class PlayerProj:
    espn_id: int
    name: str
    pos: str
    team: str
    eligible: list[str]
    fantasy_team_id: int | None
    slot: str
    mu: float
    sigma: float
    p_zero: float
    mu_ros: float
    bye: bool = False
    sources: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    locked: bool = False          # game started/finished: ESPN won't let this player change slots
    actual: float | None = None   # points scored so far this week (None if not started)
    sigma_ros: float | None = None  # pre-lock sigma, kept so rest-of-season copies aren't deterministic
    # Injury horizon. `mu_ros` is what the roster spot yields per remaining week; `mu_ros_active` is what he scores in
    # the games he plays. They differ by `avail_ros`, the share of remaining weeks he is expected to be available.
    weeks_out: float = 0.0        # expected games missed from this week on (0.3 for a Questionable, 4+ for IR)
    avail_ros: float = 1.0        # (weeks_remaining - weeks_out) / weeks_remaining, floored at 0
    mu_ros_active: float | None = None  # per-game expectation when he plays; defaults to mu_ros
    return_week: int | None = None      # first matchup week he is back, None if not out or not back this season

    def __post_init__(self):
        if self.mu_ros_active is None:
            self.mu_ros_active = self.mu_ros

    def ros(self, p_zero: float = 0.05) -> PlayerProj:
        """Rest-of-season view: per-game expectation, no lock, no bye, normal variance."""
        return PlayerProj(**{**self.__dict__, "mu": self.mu_ros, "p_zero": p_zero, "bye": False,
                             "locked": False, "actual": None, "sigma": self.sigma_ros or self.sigma})

    @property
    def ev(self) -> float:
        return (1 - self.p_zero) * self.mu

    @property
    def var(self) -> float:
        # variance of the mixture
        m, s2, q = self.mu, self.sigma**2, 1 - self.p_zero
        return q * (s2 + m * m) - (q * m) ** 2

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ev"] = round(self.ev, 2)
        d["sd"] = round(self.var**0.5, 2)
        return d


def _sigma(pos: str, mu: float, fp_sd: float | None) -> float:
    base = BASE_SIGMA.get(pos, 6.0)
    cv = CV_FLOOR.get(pos, 0.5)
    s = max(base * 0.6, cv * mu)
    if fp_sd is not None and np.isfinite(fp_sd):
        # rank-sd of ~1 is tight consensus; ~6+ is real disagreement. Scale 0.85x..1.4x
        s *= float(np.clip(0.8 + 0.1 * fp_sd, 0.85, 1.4))
    return float(s)


VEGAS_K = {"QB": 0.35, "RB": 0.3, "WR": 0.35, "TE": 0.3, "K": 0.4, "D/ST": 0.0}
LEAGUE_AVG_IMPLIED = 23.0


def blend(row: dict, fp: dict | None, sleeper: dict | None, weeks_remaining: int, overrides: dict | None = None,
          sleeper_pts: float | None = None, implied_total: float | None = None, week: int | None = None) -> PlayerProj:
    """
    row: PlayerRow dict from sources.espn. fp: matched fp_latest_weekly row. sleeper: injury_table row.
    sleeper_pts: Sleeper/Rotowire stat projection in this league's scoring. implied_total: Vegas implied team total.
    week: the current matchup week, used only to date `return_week`.

    Overrides (Claude's parameters, never decisions): `p_zero` and `mu_mult` are this week only; `weeks_out` (a number,
    or "season") and `ros_mult` are the rest of the season. Code owns the arithmetic between them.

    Blend rule (per FFA's 12-season finding that equal-weight averaging beats accuracy-weighting):
    equal-weight mean of the stat-based sources available (ESPN/Clay, Sleeper/Rotowire). FantasyPros rank-to-points
    (r2p_pts) is a rank lookup, not a stat projection, so it is a fallback only. Vegas implied total is applied as a
    small multiplicative adjuster, never averaged in (every expert already looks at the line).
    """
    pos = row["pos"]
    espn_pts = float(row.get("proj_week") or 0)
    fp_pts = float(fp["r2p_pts"]) if fp and fp.get("r2p_pts") is not None else None
    fp_sd = float(fp["sd"]) if fp and fp.get("sd") is not None else None

    stat_srcs = [x for x in (espn_pts, sleeper_pts) if x is not None and x > 0]
    if stat_srcs:
        mu = sum(stat_srcs) / len(stat_srcs)
        if fp_pts and len(stat_srcs) == 1:
            mu = 0.7 * mu + 0.3 * fp_pts   # one stat source: let consensus rank temper it
    elif fp_pts:
        mu = fp_pts
    else:
        mu = 0.0
    if implied_total and mu and VEGAS_K.get(pos, 0):
        mu *= 1 + VEGAS_K[pos] * (implied_total / LEAGUE_AVG_IMPLIED - 1)

    status = (row.get("injury_status") or "").upper() or None
    sl_status = ((sleeper or {}).get("status") or "").upper() or None
    # Sleeper tends to be fresher on designations; take the more severe of the two.
    p0 = max(P_ZERO.get(status, 0.05), P_ZERO.get(sl_status, 0.02))
    flags = []
    if row.get("bye"):
        mu, p0 = 0.0, 1.0
        flags.append("bye")
    if status and status not in ("ACTIVE", "NORMAL"):
        flags.append(f"espn:{status}")
    if sl_status and sl_status not in ("ACTIVE",):
        flags.append(f"sleeper:{sl_status}" + (f" ({sleeper.get('body_part')})" if sleeper and sleeper.get("body_part") else ""))
    if fp and fp.get("start_sit_grade"):
        flags.append(f"fp:{fp['start_sit_grade']}")

    # Rest-of-season per-game expectation: ESPN season projection spread over remaining games,
    # shrunk toward this week's blended number. This is the healthy, when-he-plays number.
    season_left = float(row.get("proj_season") or 0)
    ros_pg = season_left / max(weeks_remaining, 1) if season_left else mu
    mu_ros_active = 0.5 * ros_pg + 0.5 * mu if mu else ros_pg

    ov = (overrides or {}).get(str(row["espn_id"]), {})
    sl_roster = (sleeper or {}).get("roster_status") or ""
    designated = (status not in ACTIVE_STATUSES or sl_status not in ACTIVE_STATUSES or sl_roster in SLEEPER_ROSTER_MULTI_WEEK
                  or "p_zero" in ov)
    inj_p0 = float(ov["p_zero"]) if "p_zero" in ov else p0  # sit risk from the injury alone, before the bye
    if "p_zero" in ov:
        p0 = float(ov["p_zero"]); flags.append("llm:p_zero")
    if "mu_mult" in ov:
        mu *= float(ov["mu_mult"]); flags.append("llm:mu")   # this week only, by design (see docs/plans)
    if "ros_mult" in ov:
        mu_ros_active *= float(ov["ros_mult"]); flags.append("llm:ros")

    # Games missed from this week on. Default from the designations; Claude's `weeks_out` wins.
    W = max(weeks_remaining, 1)
    if "weeks_out" in ov:
        weeks_out = float(W if str(ov["weeks_out"]).lower() == "season" else ov["weeks_out"]); flags.append("llm:weeks_out")
    elif designated:
        weeks_out = max(inj_p0, MULTI_WEEK.get(status, 0), MULTI_WEEK.get(sl_status, 0), SLEEPER_ROSTER_MULTI_WEEK.get(sl_roster, 0))
    else:
        weeks_out = 0.0
    weeks_out = min(max(weeks_out, 0.0), float(W))
    avail_ros = (W - weeks_out) / W
    mu_ros = mu_ros_active * avail_ros
    return_week = week + ceil(weeks_out) if (week is not None and 1 <= weeks_out < W) else None

    return PlayerProj(
        espn_id=row["espn_id"], name=row["name"], pos=pos, team=row["team"], eligible=list(row["eligible"]),
        fantasy_team_id=row.get("fantasy_team_id"), slot=row.get("slot", ""),
        mu=round(mu, 2), sigma=round(_sigma(pos, mu, fp_sd), 2), p_zero=round(p0, 3), mu_ros=round(mu_ros, 2),
        bye=bool(row.get("bye")),
        weeks_out=round(weeks_out, 2), avail_ros=round(avail_ros, 3), mu_ros_active=round(mu_ros_active, 2), return_week=return_week,
        sources={"fp_pts": fp_pts, "espn_pts": espn_pts, "sleeper_pts": sleeper_pts, "implied_total": implied_total,
                 "ecr": fp.get("ecr") if fp else None, "fp_sd": fp_sd,
                 "grade": fp.get("start_sit_grade") if fp else None, "espn_status": status, "sleeper_status": sl_status,
                 "sleeper_notes": (sleeper or {}).get("notes"), "sleeper_roster_status": sl_roster or None,
                 "body_part": (sleeper or {}).get("body_part"), "percent_owned": row.get("percent_owned"),
                 "override_note": ov.get("note"), "weeks_out_source": "override" if "weeks_out" in ov else "default"},
        flags=flags,
    )
