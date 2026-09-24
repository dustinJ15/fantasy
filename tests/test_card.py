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


# ---------- hurt players ----------

def injury(name, verdict, pos="RB", weeks_out=4.0, return_week=7, avail=0.6, fa=("Pickup", 1.2), occupant=None, trades=()):
    return {"espn_id": 1, "name": name, "pos": pos, "slot": "BE", "weeks_out": weeks_out, "return_week": return_week,
            "avail_ros": avail, "mu_ros_active": 14.0, "hold_ppw": 3.0, "hold_value": 29.4, "drop_value": 13.8,
            "back_eff": 9.8, "w_eff": 13.8, "ir_eligible": True, "ir_open": 1, "ir_occupant": occupant,
            "best_fa": {"name": fa[0], "pos": pos, "delta_over_starter": fa[1], "ppw": fa[1]} if fa else None,
            "add": {"name": fa[0], "pos": pos, "kind": "upgrade", "why": f"+{fa[1]:.1f}/wk"} if fa and verdict in ("ir", "drop") and not occupant else None,
            "trades": list(trades), "market": None, "verdict": verdict, "why": []}


def test_each_verdict_is_a_row_with_the_numbers_in_words():
    lg = league(injuries=[injury("Ankle Guy", "hold"), injury("Knee Guy", "ir", weeks_out=15, return_week=None, avail=0.0),
                          injury("Done Guy", "drop", weeks_out=15, return_week=None, avail=0.0),
                          injury("Sell Guy", "trade", trades=[{"rival": "Them", "get": ["Star"]}]),
                          injury("Back Guy", "activate", weeks_out=1, return_week=4)])
    rows = by_id(lg)
    assert rows["injury:ankle-guy"]["kind"] == "hold" and rows["injury:ankle-guy"]["label"] == "Holding"
    assert rows["injury:ankle-guy"]["text"] == "Ankle Guy (RB) out ~4 wks, back wk 7, 10 games at ~14/g on return"
    assert rows["injury:knee-guy"]["text"] == "move Knee Guy (RB) to IR (out the season), then add Pickup (RB, +1.2/wk)"
    assert rows["injury:done-guy"]["label"] == "Drop"
    assert rows["injury:done-guy"]["text"] == "drop Done Guy (RB): out the season, worth ~29 pts the rest of the way; add Pickup (RB, +1.2/wk)"
    assert "the offer to Them for Star ships Sell Guy (RB)" in rows["injury:sell-guy"]["text"] and rows["injury:sell-guy"]["trade_ids"] == ["trade:star"]
    assert rows["injury:back-guy"]["label"] == "Activate" and rows["injury:back-guy"]["text"].startswith("move Back Guy (RB) off IR")


def test_the_checklist_runs_in_espn_click_order_with_holds_last():
    """Offer, lineup, IR, pickups, drops with their add, trades, and the holds as a footnote at the very end."""
    lg = league(injuries=[injury("Ankle Guy", "hold"), injury("Knee Guy", "ir", weeks_out=15, return_week=None, avail=0.0),
                          injury("Done Guy", "drop", weeks_out=15, return_week=None, avail=0.0)],
                trades=[{"rival": "Them", "give": ["A"], "get": ["Kai"], "my_delta_ppw": 1.0, "their_delta_ppw": 0.5, "why": [], "sendable": True}])
    lg["open_spot_adds"] = [{"name": "Body", "pos": "WR", "kind": "depth", "why": "best body on the wire, depth only"}]
    assert ids(lg) == ["lineup", "injury:knee-guy", "injury:done-guy", "waiver:body", "trade:kai", "injury:ankle-guy"]


def test_a_one_game_hold_is_not_a_row():
    """Out this week and worth keeping is the lineup's business; a row saying "hold him" is just the injury report."""
    lg = league(injuries=[injury("Ankle Guy", "hold", weeks_out=1.0, return_week=4), injury("Knee Guy", "ir", weeks_out=1.0, return_week=4)])
    assert ids(lg) == ["lineup", "injury:knee-guy"]


def test_ir_swap_names_the_occupant():
    lg = league(injuries=[injury("Knee Guy", "ir", occupant="Old Stash")])
    assert "in place of Old Stash" in by_id(lg)["injury:knee-guy"]["text"]


def test_the_ir_occupant_is_never_the_drop_candidate():
    lg = league(roster=[player("Starter WR", slot="WR"), player("Bench WR", ros=3.0), {**player("Stash", ros=0.0), "slot": "IR"}])
    assert report._drop_candidate(lg) == "Bench WR"


def test_a_season_ender_on_the_bench_is_the_drop_candidate():
    lg = league(roster=[player("Starter WR", slot="WR"), player("Bench WR", ros=3.0), player("Done", ros=0.0)])
    assert report._drop_candidate(lg) == "Done"


def test_read_lint_wants_a_ruling_on_a_drop_but_not_a_hold():
    p = packet(league(injuries=[injury("Done Guy", "drop"), injury("Ankle Guy", "hold")]))
    warns = report.read_lint(p, {})
    assert any("injury:done-guy" in w and "no ruling" in w for w in warns)
    assert not any("injury:ankle-guy" in w for w in warns)
    assert not any("injury:done-guy" in w for w in report.read_lint(p, {"L1": {"items": {"injury:done-guy": {"verdict": "skip", "note": "IR-eligible per the app"}}}}))


def test_a_skipped_injury_row_is_struck_like_any_other():
    lg = league(injuries=[injury("Done Guy", "drop")])
    row = by_id(lg, {"items": {"injury:done-guy": {"verdict": "skip", "note": "he is in a boot, not done"}}})["injury:done-guy"]
    assert row["ruling"] == "skip" and row["ruling_note"]


def test_out_line_merges_leagues_and_carries_the_note():
    p = packet(league())
    p["shared"]["injured"] = [{"name": "Olave", "pos": "WR", "team": "NO", "league": "L1", "weeks_out": 4, "return_week": 7, "override_note": None},
                              {"name": "Olave", "pos": "WR", "team": "NO", "league": "L3", "weeks_out": 6, "return_week": 9, "override_note": "Schefter: 4-6 weeks"}]
    rows = report.injured_list(p)
    assert len(rows) == 1 and rows[0]["leagues"] == ["L1", "L3"] and rows[0]["weeks_out"] == 6
    line = report.injured_line(rows[0])
    assert "Olave out ~6 wks, back wk 9 (L1, L3)" in line and "Schefter" in line


def test_an_open_bench_spot_is_a_row_naming_who_fills_it():
    lg = league()
    lg["open_spots"] = 1
    lg["open_spot_adds"] = [{"name": "Seth McGowan", "pos": "RB", "kind": "handcuff", "why": "handcuff for Jonathan Taylor"}]
    row = by_id(lg)["waiver:seth-mcgowan"]
    assert row["label"] == "Open spot" and row["text"] == "add Seth McGowan (RB, handcuff for Jonathan Taylor) to the open bench spot"


# ---------- ESPN's position cap on trade rows ----------

def capped_league(**kw):
    """Six WRs rostered against a cap of six; a WR-for-RB trade has to drop one in the trade screen."""
    roster = [player("Starter WR", slot="WR"), player("WR Two", slot="WR"), player("WR Three", ros=8.0), player("WR Four", ros=6.0),
              player("WR Five", ros=4.0), player("WR Six", ros=1.0), player("RB One", pos="RB", slot="RB"), player("RB Two", pos="RB", ros=5.0)]
    lg = league(roster=roster, lineup_win={"slots": {"WR": ["Starter WR", "WR Two"], "RB": ["RB One"]}, "p_win": 0.6, "mu": 100.0, "sd": 20.0, "bench": []},
                settings={"lineup_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "K": 1, "D/ST": 1}, "position_limits": {"WR": 6, "RB": 6}})
    lg.update(kw)
    return lg


def capped_trade(**kw):
    t = trade(["Garrett Wilson"], ["RB Two"], **kw)
    t.update({"drops": [{"name": "WR Six", "pos": "WR", "cap": 6}], "get_pos": ["WR"]})
    return t


def test_trade_row_names_the_drop_the_cap_forces():
    row = by_id(capped_league(trades=[capped_trade()]))["trade:garrett-wilson"]
    assert row["drops"] == ["WR Six"]
    assert "drop WR Six in the trade screen (ESPN caps WR at 6)" in row["text"]


def test_a_waiver_drop_that_clears_the_cap_spares_the_trade_a_second_cut():
    """The pickup takes the cheapest body (the sixth WR); after that the WR-for-RB trade fits without a drop."""
    w = {"name": "Pickup RB", "pos": "RB", "streamer": False, "delta_week": 2.0, "delta_over_starter": 2.0, "week_slot": "RB", "slot": "RB"}
    rows = by_id(capped_league(trades=[capped_trade()], waivers=[w]))
    assert "drop WR Six" in rows["waiver:pickup-rb"]["text"]
    assert rows["trade:garrett-wilson"]["drops"] == [] and "trade screen" not in rows["trade:garrett-wilson"]["text"]


def test_a_waiver_pickup_at_the_capped_position_moves_the_cut_to_the_next_body():
    """Adding a WR and dropping the sixth keeps the count at six, so the trade still needs a cut, and not the same player."""
    w = {"name": "Pickup WR", "pos": "WR", "streamer": False, "delta_week": 2.0, "delta_over_starter": 2.0, "week_slot": "WR", "slot": "WR"}
    rows = by_id(capped_league(trades=[capped_trade()], waivers=[w]))
    assert "drop WR Six" in rows["waiver:pickup-wr"]["text"]
    assert rows["trade:garrett-wilson"]["drops"] == ["WR Five"]


def test_a_trade_row_without_cap_data_is_unchanged():
    row = by_id(league(trades=[trade(["Kai"], ["Maye"])]))["trade:kai"]
    assert row["drops"] == [] and "trade screen" not in row["text"]


def test_incoming_offer_says_what_accepting_would_cut():
    t = {"rival": "Rival", "give": ["RB Two"], "get": ["Garrett Wilson"], "my_delta_ppw": 1.2, "their_delta_ppw": 0.3, "verdict": "accept",
         "why": [], "drops": [{"name": "WR Six", "pos": "WR", "cap": 6}]}
    row = by_id(capped_league(incoming_trades=[t]))["offer:garrett-wilson"]
    assert "accepting means dropping WR Six (6-WR cap)" in row["text"]
