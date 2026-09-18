"""The action card: what reaches the phone, and how Claude's per-row rulings fold into it."""
import pytest

from ff import report


def player(name, pos="WR", mu=10.0, ros=10.0, p0=0.02, slot="BE", locked=False, bye=False):
    return {"name": name, "pos": pos, "team": "GB", "mu": mu, "mu_ros": ros, "p_zero": p0, "slot": slot,
            "locked": locked, "bye": bye, "sources": {}, "flags": []}


def league(**kw):
    lg = {
        "name": "L1", "league_name": "Test League", "week": 3, "my_team_id": 1, "my_record": "1-1",
        "settings": {"lineup_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "K": 1, "D/ST": 1}},
        "roster": [player("Starter WR", slot="WR"), player("Bench WR", ros=3.0)],
        "lineup_win": {"slots": {"WR": ["Starter WR"]}, "p_win": 0.7, "mu": 100.0, "sd": 20.0, "bench": []},
        "lineup_diff": [], "waivers": [], "trades": [], "incoming_trades": [], "outgoing_trades": [],
        "week_state": {"phase": "pre", "my_left": [], "opp_left": []},
    }
    lg.update(kw)
    return lg


def trade(get, give, rival="Rival", mine=1.5, theirs=0.5, sendable=True, why=()):
    return {"rival": rival, "rival_team_id": 2, "give": list(give), "get": list(get), "my_delta_ppw": mine,
            "their_delta_ppw": theirs, "sendable": sendable, "why": list(why), "market_give": 100, "market_get": 90}


def ids(lg, reads=None):
    return [x["id"] for x in report.apply_reads(report.todos(lg), reads)]


def by_id(lg, reads=None):
    return {x["id"]: x for x in report.apply_reads(report.todos(lg), reads)}


# ---------- the in-progress line ----------

def test_phase_line_counts_starters_without_naming_them():
    lg = league(week_state={"phase": "in_progress", "espn_my_score": 35.2, "espn_opp_score": 5.3,
                            "my_left": [f"P{i}" for i in range(8)], "opp_left": [f"Q{i}" for i in range(8)]})
    line = report.phase_line(lg)
    assert "8 starters left" in line and "35.2 – 5.3" in line
    assert "P0" not in line  # a roster dump on Friday morning is not information


def test_phase_line_names_the_last_few():
    lg = league(week_state={"phase": "in_progress", "espn_my_score": 90, "espn_opp_score": 88,
                            "my_left": ["Kittle", "Herbert"], "opp_left": []})
    assert "(Kittle, Herbert)" in report.phase_line(lg)


def test_phase_line_silent_before_kickoff():
    assert report.phase_line(league()) is None


# ---------- what the why line is allowed to say ----------

def test_why_skips_a_default_questionable_and_keeps_a_researched_one():
    lg = league(roster=[player("Default Q", slot="WR", p0=0.30), player("Researched", slot="WR", p0=0.55)],
                lineup_win={"slots": {"WR": ["Default Q", "Researched"]}, "p_win": 0.7, "bench": []})
    why = " ".join(report.why_parts(lg))
    assert "Researched 55% to sit" in why
    assert "Default Q" not in why


def test_why_only_mentions_game_script_when_it_moved_a_slot():
    lg = league()
    assert not any("play it safe" in w for w in report.why_parts(lg))
    lg["lineup_diff"] = [{"name": "Starter WR", "in": "win", "ev": 9.0, "sd": 6.0}]
    assert any("play it safe" in w for w in report.why_parts(lg))


# ---------- rows and rulings ----------

def test_open_offers_show_up_as_a_row():
    lg = league(outgoing_trades=[{"give": ["Drake Maye"], "get": ["Jameson Williams"], "rival": "Them",
                                  "hours_left": 22.0}])
    row = by_id(lg)["sent:jameson-williams"]
    assert "Jameson Williams" in row["text"] and "22h left" in row["text"]


def test_skip_ruling_marks_the_row_and_carries_the_reason():
    lg = league(trades=[trade(["Kai"], ["Maye"])])
    row = by_id(lg, {"items": {"trade:kai": {"verdict": "skip", "note": "he is in a boot"}}})["trade:kai"]
    assert row["ruling"] == "skip" and row["ruling_note"] == "he is in a boot"


def test_unruled_rows_are_untouched():
    lg = league(trades=[trade(["Kai"], ["Maye"])])
    row = by_id(lg)["trade:kai"]
    assert row["ruling"] is None and row["ruling_note"] is None


def test_trades_shipping_the_same_player_are_flagged_as_alternatives():
    lg = league(trades=[trade(["Kai"], ["Maye"]), trade(["Odunze"], ["Maye"])])
    rows = by_id(lg)
    assert not rows["trade:kai"].get("warn")
    assert any("alternatives" in w for w in rows["trade:odunze"]["warn"])


def test_a_skipped_alternative_stops_being_an_alternative():
    """Two of three struck leaves one live move, and calling it an alternative is the confusion we set out to kill."""
    lg = league(trades=[trade(["Kai"], ["Maye"]), trade(["Odunze"], ["Maye"])])
    rows = by_id(lg, {"items": {"trade:kai": {"verdict": "skip", "note": "no"}}})
    assert not rows["trade:odunze"].get("warn")


def test_depth_warnings_speak_to_dustin():
    lg = league(trades=[trade(["Kai"], ["Maye"], why=["leaves me no backup QB"])])
    assert by_id(lg)["trade:kai"]["warn"] == ["leaves you no backup QB"]


def test_a_reach_is_labelled_as_one():
    lg = league(trades=[trade(["Kai"], ["Maye"], sendable=False, theirs=-0.4)])
    assert "reach" in by_id(lg)["trade:kai"]["label"]


def test_neutral_for_them_reads_as_words_not_plus_zero():
    lg = league(trades=[trade(["Kai"], ["Maye"], theirs=0.0)])
    assert "neutral for them" in by_id(lg)["trade:kai"]["text"]


# ---------- the cover item ----------

def cover_league(**kw):
    return league(
        roster=[player("Sick K", pos="K", slot="K", p0=0.5), player("WR", slot="WR")],
        lineup_win={"slots": {"K": ["Sick K"], "WR": ["WR"]}, "p_win": 0.7, "bench": []},
        waivers=[{"name": "Backup K", "pos": "K", "team": "DEN", "streamer": True, "delta_over_starter": 0.2,
                  "delta_week": 3.9, "week_slot": "K", "slot": "K", "why": [], "bid": 1, "mu_week": 8.0, "mu_ros": 8.0}],
        **kw)


def test_cover_item_when_the_only_kicker_may_sit():
    row = by_id(cover_league())["cover:k"]
    assert "Sick K" in row["text"] and "Backup K" in row["text"] and "only K" in row["text"]


def test_no_cover_item_when_a_healthy_backup_is_on_the_bench():
    lg = cover_league()
    lg["roster"].append(player("Spare K", pos="K", p0=0.02))
    assert "cover:k" not in ids(lg)


def test_no_cover_item_for_a_merely_questionable_starter():
    lg = cover_league()
    lg["roster"][0]["p_zero"] = 0.3
    assert "cover:k" not in ids(lg)


# ---------- lint ----------

def packet(lg):
    return {"generated": "2026-09-18T07:00:00", "shared": {"injury_watchlist": [], "exposure": {}}, "leagues": [lg]}


def test_read_lint_catches_a_typo_in_an_item_id():
    p = packet(league(trades=[trade(["Kai"], ["Maye"])]))
    warns = report.read_lint(p, {"L1": {"items": {"trade:kia": {"verdict": "skip", "note": "typo"}}}})
    assert any("no such row" in w for w in warns)


def test_read_lint_wants_a_ruling_on_every_trade():
    p = packet(league(trades=[trade(["Kai"], ["Maye"])]))
    assert any("no ruling" in w for w in report.read_lint(p, {}))
    assert not any("no ruling" in w for w in
                   report.read_lint(p, {"L1": {"items": {"trade:kai": {"verdict": "do"}}}}))


def test_read_lint_wants_a_reason_for_a_skip():
    p = packet(league(trades=[trade(["Kai"], ["Maye"])]))
    warns = report.read_lint(p, {"L1": {"items": {"trade:kai": {"verdict": "skip"}}}})
    assert any("needs a note" in w for w in warns)


def test_read_lint_catches_an_unknown_league():
    p = packet(league())
    assert any("no league by that name" in w for w in report.read_lint(p, {"L7": {"read": "hi"}}))


# ---------- the shared watch list ----------

def watch(name, league_name, starting_note=None, locked=False, p_zero=0.3):
    return {"name": name, "pos": "WR", "team": "NO", "league": league_name, "status": "QUESTIONABLE",
            "notes": None, "espn_id": 1, "p_zero": p_zero, "override_note": starting_note, "locked": locked}


@pytest.fixture
def two_leagues():
    l1 = league(name="L1", roster=[player("Olave", slot="WR")], lineup_win={"slots": {"WR": ["Olave"]}, "p_win": 0.6, "bench": []})
    l3 = league(name="L3", roster=[player("Olave", slot="WR")], lineup_win={"slots": {"WR": ["Olave"]}, "p_win": 0.6, "bench": []})
    return {"generated": "2026-09-18T07:00:00", "leagues": [l1, l3],
            "shared": {"injury_watchlist": [], "exposure": {}}}


def test_watchlist_merges_a_player_held_in_two_leagues(two_leagues):
    two_leagues["shared"]["injury_watchlist"] = [watch("Olave", "L1", "hamstring, limited Thu"), watch("Olave", "L3")]
    rows = report.watchlist(two_leagues)
    assert len(rows) == 1
    assert rows[0]["leagues"] == ["L1", "L3"] and rows[0]["override_note"] == "hamstring, limited Thu"


def test_watchlist_drops_a_bench_player_nobody_researched(two_leagues):
    two_leagues["shared"]["injury_watchlist"] = [watch("Monangai", "L1")]
    assert report.watchlist(two_leagues) == []


def test_watchlist_keeps_a_bench_player_the_research_found_something_on(two_leagues):
    two_leagues["shared"]["injury_watchlist"] = [watch("Bowers", "L1", "has not practiced since the meniscus trim")]
    rows = report.watchlist(two_leagues)
    assert len(rows) == 1 and rows[0]["starting"] is False


def test_watchlist_drops_players_who_already_played(two_leagues):
    two_leagues["shared"]["injury_watchlist"] = [watch("Olave", "L1", "hamstring", locked=True)]
    assert report.watchlist(two_leagues) == []


def test_watchlist_puts_starters_first(two_leagues):
    two_leagues["shared"]["injury_watchlist"] = [watch("Bowers", "L1", "note"), watch("Olave", "L1", "note")]
    assert [r["name"] for r in report.watchlist(two_leagues)] == ["Olave", "Bowers"]
