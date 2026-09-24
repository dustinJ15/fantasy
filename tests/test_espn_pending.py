"""Parse ESPN's raw mPendingTransactions shape (captured 2026-09-16) into give/get from my point of view."""
from ff.sources.espn import pending_trades

RAW = {"pendingTransactions": [
    {"bidAmount": 0, "executionType": "EXECUTE", "expirationDate": 1789696354383, "id": "b1a22a82", "isPending": True,
     "items": [
         {"fromLineupSlotId": 20, "fromTeamId": 4, "playerId": 4241985, "toLineupSlotId": -1, "toTeamId": 16, "type": "TRADE"},
         {"fromLineupSlotId": 6, "fromTeamId": 4, "playerId": 3040151, "toLineupSlotId": -1, "toTeamId": 16, "type": "TRADE"},
         {"fromLineupSlotId": 6, "fromTeamId": 16, "playerId": 4361307, "toLineupSlotId": -1, "toTeamId": 4, "type": "TRADE"}],
     "proposedDate": 1789523554358, "scoringPeriodId": 2, "status": "PENDING", "teamActions": {"4": "ACCEPTED"}, "teamId": 4, "type": "TRADE_PROPOSAL"},
    # a proposal between two other teams: ignored
    {"id": "other", "items": [{"fromTeamId": 1, "toTeamId": 2, "playerId": 1, "type": "TRADE"}], "teamId": 1, "type": "TRADE_PROPOSAL", "status": "PENDING"},
    # a pending waiver claim: ignored
    {"id": "w", "items": [{"fromTeamId": -1, "toTeamId": 16, "playerId": 5, "type": "ADD"}], "teamId": 16, "type": "WAIVER", "status": "PENDING"},
]}


class FakeReq:
    def league_get(self, params=None, headers=None):
        assert params == {"view": "mPendingTransactions"}
        return RAW


class FakeLeague:
    espn_request = FakeReq()


def test_incoming_from_my_side():
    out = pending_trades(FakeLeague(), 16)
    assert len(out) == 1
    t = out[0]
    assert t["direction"] == "incoming" and t["rival_team_id"] == 4 and t["proposer_team_id"] == 4
    assert t["get"] == [4241985, 3040151] and t["give"] == [4361307]
    assert t["proposed_ts"] == 1789523554358 and t["expires_ts"] == 1789696354383 and t["id"] == "b1a22a82"


def test_outgoing_from_proposer_side():
    t = pending_trades(FakeLeague(), 4)[0]
    assert t["direction"] == "outgoing" and t["rival_team_id"] == 16
    assert t["give"] == [4241985, 3040151] and t["get"] == [4361307]


def test_empty_and_unknown_team():
    class Empty:
        class espn_request:
            @staticmethod
            def league_get(params=None, headers=None):
                return {"status": {}}
    assert pending_trades(Empty(), 16) == []
    assert pending_trades(FakeLeague(), None) == []


def test_position_limits_come_from_default_position_ids_and_skip_unlimited():
    from ff.sources.espn import position_limits
    raw = {"positionLimits": {"0": 0, "1": 4, "2": 6, "3": 6, "4": 3, "5": 3, "6": -1, "16": 3, "17": -1}}
    assert position_limits(raw) == {"QB": 4, "RB": 6, "WR": 6, "TE": 3, "K": 3, "D/ST": 3}
    assert position_limits({}) == {}
