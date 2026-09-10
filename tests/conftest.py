import pytest
from ff.model.projections import PlayerProj


def P(i, name, pos, mu, sigma=5.0, p0=0.02, team="X", elig=None, tid=1, ros=None):
    elig = elig or ([pos, "RB/WR/TE"] if pos in ("RB", "WR", "TE") else [pos])
    return PlayerProj(espn_id=i, name=name, pos=pos, team=team, eligible=elig, fantasy_team_id=tid, slot="",
                      mu=mu, sigma=sigma, p_zero=p0, mu_ros=ros if ros is not None else mu)


@pytest.fixture
def slots():
    return {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "K": 1, "D/ST": 1}


@pytest.fixture
def roster():
    return [
        P(1, "QB1", "QB", 20, 6), P(2, "RB1", "RB", 16, 6), P(3, "RB2", "RB", 12, 5), P(4, "RB3", "RB", 9, 4),
        P(5, "WR1", "WR", 15, 6), P(6, "WR2", "WR", 11, 5), P(7, "WR3", "WR", 10, 9),  # WR3 high variance
        P(8, "TE1", "TE", 8, 4), P(9, "K1", "K", 8, 3), P(10, "DST1", "D/ST", 7, 4),
    ]
