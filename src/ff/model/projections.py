"""Blend projection sources into a per-player weekly distribution.

X ~ (1 - p_zero) * N(mu, sigma^2) + p_zero * delta(0)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

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


def blend(row: dict, fp: dict | None, sleeper: dict | None, weeks_remaining: int, overrides: dict | None = None) -> PlayerProj:
    """row: PlayerRow dict from sources.espn. fp: matched fp_latest_weekly row. sleeper: injury_table row."""
    pos = row["pos"]
    espn_pts = float(row.get("proj_week") or 0)
    fp_pts = float(fp["r2p_pts"]) if fp and fp.get("r2p_pts") is not None else None
    fp_sd = float(fp["sd"]) if fp and fp.get("sd") is not None else None

    srcs = [x for x in (fp_pts, espn_pts) if x is not None and x > 0]
    if fp_pts and espn_pts:
        mu = 0.6 * fp_pts + 0.4 * espn_pts     # consensus of 130+ experts beats one house model
    elif srcs:
        mu = srcs[0]
    else:
        mu = 0.0

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
    # shrunk toward this week's blended number.
    season_left = float(row.get("proj_season") or 0)
    ros_pg = season_left / max(weeks_remaining, 1) if season_left else mu
    mu_ros = 0.5 * ros_pg + 0.5 * mu if mu else ros_pg

    ov = (overrides or {}).get(str(row["espn_id"]), {})
    if "p_zero" in ov:
        p0 = float(ov["p_zero"]); flags.append("llm:p_zero")
    if "mu_mult" in ov:
        mu *= float(ov["mu_mult"]); flags.append("llm:mu")

    return PlayerProj(
        espn_id=row["espn_id"], name=row["name"], pos=pos, team=row["team"], eligible=list(row["eligible"]),
        fantasy_team_id=row.get("fantasy_team_id"), slot=row.get("slot", ""),
        mu=round(mu, 2), sigma=round(_sigma(pos, mu, fp_sd), 2), p_zero=round(p0, 3), mu_ros=round(mu_ros, 2),
        bye=bool(row.get("bye")),
        sources={"fp_pts": fp_pts, "espn_pts": espn_pts, "ecr": fp.get("ecr") if fp else None, "fp_sd": fp_sd,
                 "grade": fp.get("start_sit_grade") if fp else None, "espn_status": status, "sleeper_status": sl_status,
                 "sleeper_notes": (sleeper or {}).get("notes"), "percent_owned": row.get("percent_owned")},
        flags=flags,
    )
