"""Blend projection sources into a per-player weekly distribution.

X ~ (1 - p_zero) * N(mu, sigma^2) + p_zero * delta(0)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import ceil

import numpy as np

# Position-level projection-to-actual error (weekly points, PPR-ish). Rough priors from
# published accuracy studies; scaled by the FantasyPros rank-sd where available.
# `sigma = max(SIGMA_FLOOR_FRAC * BASE_SIGMA[pos], CV_FLOOR[pos] * mu)` (see `_sigma`); `ff accuracy --fit`
# (`projlog.sigma_fit`) fits both numbers per position to the projlog residuals in exactly this form and prints them next
# to these, but writes nothing: a position is fitted only at `projlog.FIT_MIN_N` scored forecasts, and as of 2026-10-20
# (weeks 1-6 scored: QB 31, RB 70, WR 67, TE 31, K 16, D/ST 16) none is, so every value here is still the prior.
BASE_SIGMA = {"QB": 7.0, "RB": 6.5, "WR": 6.5, "TE": 5.0, "K": 4.0, "D/ST": 5.5}
# Coefficient of variation floor so that low projections still have spread.
CV_FLOOR = {"QB": 0.30, "RB": 0.45, "WR": 0.50, "TE": 0.55, "K": 0.45, "D/ST": 0.60}
# The absolute floor is this fraction of BASE_SIGMA (the fitter reports BASE_SIGMA, never the floor itself).
SIGMA_FLOOR_FRAC = 0.6

# Injury designation -> probability of a zero (inactive). LLM may override via packet.
P_ZERO = {
    None: 0.02, "ACTIVE": 0.02, "NORMAL": 0.02, "PROBABLE": 0.08, "QUESTIONABLE": 0.30, "DAY_TO_DAY": 0.15,
    "DOUBTFUL": 0.80, "OUT": 1.0, "INJURY_RESERVE": 1.0, "IR": 1.0, "PUP": 1.0, "SUSPENSION": 1.0,
    "SUS": 1.0, "NA": 1.0, "DNR": 1.0, "COV": 1.0,
}
# A Questionable tag early in the week is last week's, carried until Wednesday's first practice report. Benching a
# starter on Tuesday for a 30% that is really a 15% churns the lineup; the Friday number is the 30%. Keyed by
# weekday (Monday = 0); days not listed use P_ZERO. Claude's `p_zero` override still wins.
QUESTIONABLE_BY_WEEKDAY = {0: 0.15, 1: 0.15, 2: 0.15, 3: 0.20}

# Designations that mean more than this week. NFL injured reserve and reserve/PUP are a four-game minimum, so 4 is a
# floor rather than an estimate; a suspension's length is public, so Claude sets it in overrides. Single-week
# designations fall out of `p_zero` on their own (Questionable is 0.3 of a game, Doubtful 0.8, Out 1.0).
MULTI_WEEK = {"INJURY_RESERVE": 4, "IR": 4, "PUP": 4, "NA": 1, "DNR": 1, "COV": 1, "SUSPENSION": 1, "SUS": 1}
# Sleeper's roster status (not its injury designation) is the freshest "he is on NFL IR" signal.
SLEEPER_ROSTER_MULTI_WEEK = {"Injured Reserve": 4, "Physically Unable to Perform": 4, "Non Football Injury": 4}
ACTIVE_STATUSES = (None, "", "ACTIVE", "NORMAL")

FLEX_LABELS = {"RB/WR/TE", "RB/WR", "WR/TE", "OP"}

# ESPN's `proj_season` is a full-season total, so its per-game reading is over the NFL's 17 games, never over the
# weeks left in the fantasy season (that read 18.9 a game for a 14.5-a-game receiver in week 5 and grew every week).
NFL_GAMES = 17
# The preseason season total is a prior on a player's level that his own games replace: full weight before his first
# game, gone after this many. A body ESPN gave no preseason total (`proj_season` 0: a kicker, a D/ST, the backup who
# became a starter) takes this week's matchup-neutral number as the prior instead (`level_prior`, D13): without one his
# level was his last game or two (19.5 a game after one 25-point game, 11.2 for the same games with a prior), which put
# a one-game kicker and a fill-in QB at the top of the claim ranking. The 2026 replay (weeks 1-5, the wire bodies within
# three points of a starter): this week's number as the prior reads the no-prior body at +0.5 to +0.9 a game over what he
# scored after, 3.3 mean absolute, against +0.6 to +1.0 and 3.35-3.5 with no prior; the position's replacement level as
# the prior read worse than no prior on every row set and needs a second pricing pass. That sample held the bodies whose
# total ESPN zeroed on the pull day because they are on IR or Out today (D19, 2026-10-21, `backtest.TOTAL_ZEROED_STATUSES`);
# with them apart the same wire body reads +0.1 to +0.6 (3.5-3.7) against -0.3 to +0.3 (3.4-3.6) with no prior, and the
# rostered no-total body +0.3 to -0.8 either way; the prior stays, re-read with D18. The claim tables read the same way (D20, 2026-10-21): every claim-worthy row
# on a no-total body is a fill-in QB (Wentz, Lock, Mariota) who went dark when his starter came back, a loss no prior
# sees; the dark first claims ESPN had zeroed (Hollins, Thornton, Ferguson: hurt after the row) are the pull-day leak. The prior itself was re-read on
# everyone (D17, 2026-10-21, `ff backtest --prior`, docs/accuracy.md "The rest-of-season prior"): the in-range wire body
# *with* a total reads 1.3 to 1.8 a game under what he scores after (his total is a backup's), and the larger of the total
# and this week's number is the one prior that fixes him, but it reads every rostered body +1.2 to +1.3 over (this week's
# number carries ESPN's weekly optimism, which the fading total damps) and a faster fade is worse on every sample; so it
# stays, re-read on the full season (D18).
PRIOR_FADE_GAMES = 6

# What his opportunity says he should have scored, against what he did (D1). `model/usage.py` prices a season's
# targets, carries, air yards and pass attempts at league-average PPR values (`xfp_lite`); its ratio to his actual PPR
# points is unitless, so it scales ESPN's league-scoring points per game without a scoring table. The weight and the
# clip are fitted (D10 step 1, 2026-10-21, `opfit.py`, `ff fit-opportunity`): 23,096 player-weeks of 2016-2025, the
# rest-of-season points per game against `ppg * (1 - w + w * ratio)`, leave-one-season-out; the fold weights sit within
# 0.03 of these. The 0.5 prior of 2026-10-20 (RB, WR, TE; QB read 1.0 with no attempt term) scored 4.18 pooled rmse,
# these 4.16; the plan has the table and what the fit could not see (`docs/plans/fitted-projection.md`). K and D/ST
# read 1.0: nflverse has no kicks. The clip is a guard on a bad row (a nflverse game count that disagrees with ESPN's),
# not a fitted number: inside the data no clip at all scored the same, so it sits outside the ratios the data holds.
OPPORTUNITY_WEIGHT = {"QB": 0.57, "RB": 0.64, "WR": 0.58, "TE": 0.67}   # was 0.5 (RB, WR, TE), QB 0; fitted 2026-10-21
OPPORTUNITY_RATIO_CLIP = (0.3, 2.0)   # was (0.7, 1.4); fitted 2026-10-21
OPPORTUNITY_MIN_GAMES = 2


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
    pending_trade: str | None = None  # "in" / "out": moved by an accepted trade ESPN has not processed yet (packet.apply_accepted_trades)
    actual: float | None = None   # points scored so far this week (None if not started)
    mu_pre: float | None = None   # the projection before the clock banked his points: what the accuracy log scores
    sigma_ros: float | None = None  # pre-lock sigma, kept so rest-of-season copies aren't deterministic
    # Injury horizon. `mu_ros` is what the roster spot yields per remaining week; `mu_ros_active` is what he scores in
    # the games he plays. They differ by `avail_ros`, the share of remaining weeks he is expected to be available.
    weeks_out: float = 0.0        # expected games missed from this week on (0.3 for a Questionable, 4+ for IR)
    avail_ros: float = 1.0        # (weeks_remaining - weeks_out) / weeks_remaining, floored at 0
    mu_ros_active: float | None = None  # per-game expectation when he plays; defaults to mu_ros
    return_week: int | None = None      # first matchup week he is back, None if not out or not back this season
    bye_weeks: list[int] = field(default_factory=list)  # NFL bye weeks for his team (one, normally); [] when unknown

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


def sigma_shape(mu, base: float, cv: float):
    """The positional sigma before the FantasyPros rank-sd fudge: `max(SIGMA_FLOOR_FRAC * base, cv * mu)`.

    Works on a float or a numpy array of `mu`; the fitter in `projlog` minimises the Gaussian log-likelihood of this
    same shape, so a fitted pair drops straight into BASE_SIGMA / CV_FLOOR."""
    return np.maximum(SIGMA_FLOOR_FRAC * base, cv * np.asarray(mu, dtype=float))


def _sigma(pos: str, mu: float, fp_sd: float | None) -> float:
    base = BASE_SIGMA.get(pos, 6.0)
    cv = CV_FLOOR.get(pos, 0.5)
    s = float(sigma_shape(mu, base, cv))
    if fp_sd is not None and np.isfinite(fp_sd):
        # rank-sd of ~1 is tight consensus; ~6+ is real disagreement. Scale 0.85x..1.4x
        s *= float(np.clip(0.8 + 0.1 * fp_sd, 0.85, 1.4))
    return float(s)


# This week's implied team total (`sources/vegas.py`): `mu *= 1 + k * (implied / LEAGUE_AVG_IMPLIED - 1)`. Set by hand
# (2026-09); QB, RB, WR and TE fitted (D10 step 3, `opfit.fit_vegas`, `ff fit-opportunity`, 2026-10-21): 28,417
# player-weeks of 2016-2025, his points that week against his opportunity-moved level so far times the adopted opponent
# multiplier, his team's implied total off nflverse's closing line, leave-one-season-out. Only QB beat the hand number
# out of sample (fit 0.413, folds 0.40-0.44); RB (fit 0.38), WR (0.27) and TE (0.33) tie their priors and keep them.
# The term is worth 1.0% of the weekly error at QB, 0.5% at RB, 0.2-0.3% at WR and TE. K and D/ST stay hand-set
# (nflverse has no kicks). The plan has the table, why the base is the level and not raw ppg, and why the centre stays
# at 23 (`docs/plans/fitted-projection.md`).
VEGAS_K = {"QB": 0.41, "RB": 0.3, "WR": 0.35, "TE": 0.3, "K": 0.4, "D/ST": 0.0}   # QB was 0.35; fitted 2026-10-21
LEAGUE_AVG_IMPLIED = 23.0

# This week's opponent (D10 step 2, ROADMAP item 5's open piece). `model/usage.py` `opponent_factors` reads each
# defense's PPR points allowed a game to a position over the season through last week, over what those offenses scored
# at the position in their other games (one pass of schedule adjustment): 1.2 is a defense giving up a fifth more than
# the offenses it faced score elsewhere. The multiplier on this week's number is `1 + k * (factor - 1)`, held to
# 1 ± OPPONENT_MULT_CAP, and a defense under OPPONENT_MIN_GAMES games reads 1.0. `k` is fitted (`opfit.fit_opponent`,
# `ff fit-opportunity`, 2026-10-21): 26,670 player-weeks of 2016-2025, his points that week against `ppg` so far,
# leave-one-season-out, against no factor at all (k = 0); the fold `k`s sit within 0.03 of these. The factor is worth
# 0.3-0.4% of the weekly error at QB, RB and TE and nothing to speak of at WR (a young WR factor, under six games, fits
# k = 0); the cap binds on 2-5% of rows and earns its place; the plan has the table and what the fit could not see
# (`docs/plans/fitted-projection.md`). K and D/ST read 1.0 (nflverse has no kicks).
OPPONENT_K = {"QB": 0.20, "RB": 0.25, "WR": 0.09, "TE": 0.19}   # was 0 (no factor); fitted 2026-10-21
OPPONENT_MULT_CAP = 0.10   # ROADMAP item 5's ±10%; the fit says the cap helps (2026-10-21)
OPPONENT_MIN_GAMES = 3

# Wind at kickoff (`sources/weather.py`, Open-Meteo 10 m wind in mph) discounts this week's number for the players
# the ball has to fly for. The public play-by-play studies (FiveThirtyEight's and 4for4's wind pieces, the Fantasy
# Points weather reviews) agree on the shape and roughly on the size: passing yards, completion rate and field-goal
# rate are flat up to the mid-teens and fall from there; at 20+ mph a QB's fantasy output lands about 10-15% under
# projection, and kickers lose more because the long attempts stop being tried. The ramp is linear from
# WIND_MPH_START to WIND_MPH_CAP and flat after it; the cap penalty is the small end of those figures, since every
# projection source already glances at the forecast by Sunday morning and the cost of a wrong number is a benching.
# Domes and retractable roofs are exempt (`dome` in the forecast), a missing or unavailable forecast is calm, and
# the rest-of-season numbers never see it: wind is a matchup, not a level.
WIND_MPH_START = 15.0
WIND_MPH_CAP = 25.0
WIND_PENALTY_AT_CAP = {"QB": 0.10, "WR": 0.10, "TE": 0.10, "K": 0.15}   # RB and D/ST: no penalty


def wind_mult(pos: str, weather: dict | None) -> float:
    """This week's multiplier for the kickoff forecast: 1.0 for a dome, a missing forecast, a calm day or a position the
    wind does not touch; 1 - penalty at WIND_MPH_CAP and above, linear in between."""
    if not weather or weather.get("dome") or weather.get("unavailable"):
        return 1.0
    wind = _num(weather.get("wind_mph"))
    pen = WIND_PENALTY_AT_CAP.get(pos, 0.0)
    if wind is None or wind <= WIND_MPH_START or not pen:
        return 1.0
    frac = min((wind - WIND_MPH_START) / (WIND_MPH_CAP - WIND_MPH_START), 1.0)
    return 1.0 - pen * frac


def opponent_mult(pos: str, opponent: dict | None) -> float:
    """This week's multiplier for the defense he faces (`usage.opponent_factor_index` row: `factor`, `games`): 1.0 for a
    position the factor does not price (K, D/ST), a missing opponent or one under OPPONENT_MIN_GAMES games; otherwise
    `1 + k * (factor - 1)` with OPPONENT_K's `k`, held to 1 ± OPPONENT_MULT_CAP."""
    k = OPPONENT_K.get(pos, 0.0)
    if not k or not opponent:
        return 1.0
    f, games = _num(opponent.get("factor")), int(opponent.get("games") or 0)
    if f is None or f <= 0 or games < OPPONENT_MIN_GAMES:
        return 1.0
    return float(np.clip(1.0 + k * (f - 1.0), 1.0 - OPPONENT_MULT_CAP, 1.0 + OPPONENT_MULT_CAP))


def season_pg(ytd_pg: float | None, games: int, prior_pg: float | None, fade: int = PRIOR_FADE_GAMES) -> float | None:
    """A player's healthy per-game level from the season so far: his own points per game played, with ESPN's
    preseason total (per game) as a prior that fades out over his first `fade` (PRIOR_FADE_GAMES) games. None without
    either."""
    if ytd_pg is None or games <= 0:
        return prior_pg
    if not prior_pg:
        return ytd_pg
    w_prior = max(0.0, 1.0 - games / fade)
    return w_prior * prior_pg + (1 - w_prior) * ytd_pg


def opportunity_mult(pos: str, usage: dict | None) -> float:
    """The multiplier on a player's season-to-date points per game that moves it toward what his opportunity says
    (`usage.signals`: `xfp_pg` over `ppg`, both nflverse PPR, over `games`): 1.0 for a position the proxy does not
    price (K, D/ST), a sample under OPPORTUNITY_MIN_GAMES games or a missing number; otherwise `1 - w + w * ratio`
    with the fitted `w` of OPPORTUNITY_WEIGHT and the ratio clipped to OPPORTUNITY_RATIO_CLIP, so a receiver scoring
    20% over his targets reads about 11% under his average."""
    w = OPPORTUNITY_WEIGHT.get(pos, 0.0)
    if not w or not usage:
        return 1.0
    ppg, xfp, games = _num(usage.get("ppg")), _num(usage.get("xfp_pg")), int(usage.get("games") or 0)
    if not ppg or ppg <= 0 or xfp is None or xfp <= 0 or games < OPPORTUNITY_MIN_GAMES:
        return 1.0
    lo, hi = OPPORTUNITY_RATIO_CLIP
    ratio = min(max(xfp / ppg, lo), hi)
    return 1.0 - w + w * ratio


def per_game(season: float | None, weekly: float, plays_this_week: bool) -> float:
    """Rest-of-season per-game expectation: the season level shrunk halfway toward this week's projection when he is
    expected to play it (this week's number carries the freshest read on his role), the season level alone when
    he is not (a player listed Out projects ~0 this week, which says nothing about his healthy level)."""
    if season is None:
        return weekly
    if plays_this_week and weekly:
        return 0.5 * season + 0.5 * weekly
    return season


def _num(x) -> float | None:
    """A number from a source column, or None: the FantasyPros mirror writes NA for a missing value and a column with
    one NA in it arrives as text, so a missing consensus must read as missing, not crash the packet."""
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def blend(row: dict, fp: dict | None, sleeper: dict | None, weeks_remaining: int, overrides: dict | None = None,
          sleeper_pts: float | None = None, implied_total: float | None = None, week: int | None = None,
          weekday: int | None = None, weather: dict | None = None, usage: dict | None = None,
          opponent: dict | None = None) -> PlayerProj:
    """
    row: PlayerRow dict from sources.espn. fp: matched fp_latest_weekly row. sleeper: injury_table row.
    sleeper_pts: Sleeper/Rotowire stat projection in this league's scoring. implied_total: Vegas implied team total.
    week: the current matchup week, used only to date `return_week`. weekday: today (Monday = 0), which scales a
    Questionable early in the week; None means the Friday number. weather: the kickoff forecast for his game
    (`sources.weather.forecast`), None when unknown; only its wind moves a number (`wind_mult`), this week only.
    usage: his season-to-date opportunity (`model/usage.py` `signals`), None when nflverse has nothing on him; it
    moves the rest-of-season level only (`opportunity_mult`), never this week and never the rival's `espn_pg`.
    opponent: the defense he faces this week, its points-allowed factor at his position through last week
    (`usage.opponent_factor_index`), None when unknown; it moves this week's number only (`opponent_mult`), beside the
    implied total, never the rest-of-season level and never the rival's `espn_pg`.

    Overrides (Claude's parameters, never decisions): `p_zero` and `mu_mult` are this week only; `weeks_out` (a number,
    or "season") and `ros_mult` are the rest of the season. Code owns the arithmetic between them.

    Blend rule (per FFA's 12-season finding that equal-weight averaging beats accuracy-weighting):
    equal-weight mean of the stat-based sources available (ESPN/Clay, Sleeper/Rotowire). FantasyPros rank-to-points
    (r2p_pts) is a rank lookup, not a stat projection, so it is a fallback only. Vegas implied total is applied as a
    small multiplicative adjuster, never averaged in (every expert already looks at the line).
    """
    pos = row["pos"]
    espn_pts = float(row.get("proj_week") or 0)
    fp_pts = _num(fp.get("r2p_pts")) if fp else None
    fp_sd = _num(fp.get("sd")) if fp else None

    stat_srcs = [x for x in (espn_pts, sleeper_pts) if x is not None and x > 0]
    if stat_srcs:
        mu = sum(stat_srcs) / len(stat_srcs)
        if fp_pts and len(stat_srcs) == 1:
            mu = 0.7 * mu + 0.3 * fp_pts   # one stat source: let consensus rank temper it
    elif fp_pts:
        mu = fp_pts
    else:
        mu = 0.0
    mu_neutral = mu   # the blend before this week's matchup (Vegas, the opponent) is applied: the rest of the season's input
    if implied_total and mu and VEGAS_K.get(pos, 0):
        mu *= 1 + VEGAS_K[pos] * (implied_total / LEAGUE_AVG_IMPLIED - 1)
    def_mult = opponent_mult(pos, opponent)
    mu *= def_mult
    wx_mult = wind_mult(pos, weather)
    mu *= wx_mult

    status = (row.get("injury_status") or "").upper() or None
    sl_status = ((sleeper or {}).get("status") or "").upper() or None
    # Sleeper tends to be fresher on designations; take the more severe of the two.
    p_q = QUESTIONABLE_BY_WEEKDAY.get(weekday, P_ZERO["QUESTIONABLE"]) if weekday is not None else P_ZERO["QUESTIONABLE"]
    p_zero = {**P_ZERO, "QUESTIONABLE": p_q}
    p0 = max(p_zero.get(status, 0.05), p_zero.get(sl_status, 0.02))
    ov = (overrides or {}).get(str(row["espn_id"]), {})
    inj_p0 = float(ov["p_zero"]) if "p_zero" in ov else p0  # sit risk from the injury alone, before the bye
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
    wind_mph = _num((weather or {}).get("wind_mph"))
    if wx_mult < 1.0:
        flags.append(f"wind:{wind_mph:.0f}mph x{wx_mult:.2f}")
    if abs(def_mult - 1.0) >= 0.03:
        flags.append(f"def:x{def_mult:.2f}")

    sl_roster = (sleeper or {}).get("roster_status") or ""
    designated = (status not in ACTIVE_STATUSES or sl_status not in ACTIVE_STATUSES or sl_roster in SLEEPER_ROSTER_MULTI_WEEK
                  or "p_zero" in ov)

    # Rest-of-season per-game expectation (the healthy, when-he-plays number): his season so far per game played,
    # moved toward what his opportunity says he should have scored (`opportunity_mult`), ESPN's full-season total per
    # NFL game as the fading prior, shrunk toward this week's matchup-neutral blend when he is expected to play this
    # week. `weeks_remaining` is not in the denominator: ESPN's total is a season figure, not what is left of it.
    # `espn_pg` is the same arithmetic on ESPN's own numbers, opportunity left out: what a rival's app shows him.
    games = int(row.get("games_played") or 0)
    ytd_pg = float(row.get("actual_season") or 0) / games if games > 0 else None
    prior_pg = float(row.get("proj_season") or 0) / NFL_GAMES or None
    # the prior `season_pg` fades: ESPN's preseason total per game, else this week's matchup-neutral number (D13), else
    # nothing (a body with no total projected at zero this week: his own games alone, as before)
    level_prior = prior_pg or (mu_neutral if mu_neutral > 0 else None)
    espn_prior = prior_pg or (espn_pts if espn_pts > 0 else None)
    plays = inj_p0 < 0.5 and not row.get("bye")
    opp_mult = opportunity_mult(pos, usage) if ytd_pg is not None else 1.0
    level = season_pg(ytd_pg * opp_mult if ytd_pg is not None else None, games, level_prior)
    espn_level = season_pg(ytd_pg, games, espn_prior)
    mu_ros_active = per_game(level, mu_neutral, plays)
    espn_pg = per_game(espn_level, espn_pts, plays) if espn_level is not None else None
    if abs(opp_mult - 1.0) >= 0.05:
        flags.append(f"opp:x{opp_mult:.2f}")
    if "p_zero" in ov and not row.get("bye"):
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
        bye_weeks=sorted({int(w) for w in (row.get("bye_weeks") or [])} | ({week} if row.get("bye") and week else set())),
        sources={"fp_pts": fp_pts, "espn_pts": espn_pts, "sleeper_pts": sleeper_pts, "implied_total": implied_total,
                 # kickoff wind and the this-week multiplier it earned (1.0 for a dome, calm air or no forecast)
                 "wind_mph": wind_mph, "weather_mult": round(wx_mult, 3),
                 # the defense he faces this week: its schedule-adjusted points-allowed factor at his position through
                 # last week (None when unknown) and the this-week multiplier it earned (1.0 when it has no say)
                 "def_factor": _num((opponent or {}).get("factor")), "def_mult": round(def_mult, 3),
                 # ESPN's own rest-of-season number per game: what a rival's app shows him, injury docking included
                 "espn_pg": round(espn_pg, 2) if espn_pg is not None else None,
                 "ytd_pg": round(ytd_pg, 2) if ytd_pg is not None else None, "games_played": games,
                 # this week's blend before the matchup (the opponent, the wind): the rest of the season's input
                 "mu_neutral": round(mu_neutral, 2),
                 # ESPN's preseason total per NFL game; None when ESPN gave him no total. `prior_src` says what
                 # `season_pg` faded: that total (`season`), this week's number in its place (`week`, D13), or nothing
                 "prior_pg": round(prior_pg, 2) if prior_pg else None,
                 "prior_src": "season" if prior_pg else ("week" if level_prior else None),
                 # the opportunity read on his season so far: xFP-lite over actual, weighted (1.0 when it has no say)
                 "opp_mult": round(opp_mult, 3),
                 "actual_prev": row.get("actual_prev_week"),   # ESPN's final for last week: the accuracy log's truth
                 "pos_rank": row.get("pos_rank"),
                 "ecr": fp.get("ecr") if fp else None, "fp_sd": fp_sd,
                 "grade": fp.get("start_sit_grade") if fp else None, "espn_status": status, "sleeper_status": sl_status,
                 "sleeper_notes": (sleeper or {}).get("notes"), "sleeper_roster_status": sl_roster or None,
                 "body_part": (sleeper or {}).get("body_part"), "percent_owned": row.get("percent_owned"),
                 "waiver_status": row.get("waiver_status"),
                 "override_note": ov.get("note"), "weeks_out_source": "override" if "weeks_out" in ov else "default"},
        flags=flags,
    )
