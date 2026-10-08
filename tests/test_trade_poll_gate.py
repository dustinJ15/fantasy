"""scripts/trade_poll_gate.py: the trade-offer backstop polls Denver evenings and every weekday in season (C3, 2026-10-08).

The old gate was `date -u` arithmetic in the workflow (skip Monday, skip UTC hours 0-11), so an offer sent at 8 PM
Denver on a Sunday (02:00 UTC Monday) was not seen until the morning briefing; Monday daytime was skipped too.
"""
import importlib.util
import re
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("trade_poll_gate", ROOT / "scripts" / "trade_poll_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

DENVER = ZoneInfo("America/Denver")


def denver(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=DENVER)


@pytest.mark.parametrize("local, label", [
    (denver(2026, 10, 11, 20), "Sunday 8 PM Denver = Monday 02:00 UTC: the case from TODO C3"),
    (denver(2026, 10, 10, 20), "Saturday 8 PM Denver = Sunday 02:00 UTC"),
    (denver(2026, 10, 13, 18, 30), "Tuesday 6:30 PM Denver = Wednesday 00:30 UTC"),
    (denver(2026, 10, 14, 23, 59), "Wednesday 11:59 PM Denver"),
    (denver(2026, 10, 15, 0, 30), "Thursday half past midnight Denver, still an evening"),
    (denver(2026, 10, 12, 20), "Monday 8 PM Denver, after the night game"),
    (denver(2026, 10, 12, 10), "Monday 10 AM Denver: the old gate skipped all of Monday"),
    (denver(2026, 10, 13, 14), "Tuesday 2 PM Denver: the old gate polled this too"),
    (denver(2026, 10, 11, 6), "Sunday 6 AM Denver: the first poll of the day, with the briefing"),
    (denver(2026, 12, 3, 22), "a December evening, MST"),
    (denver(2027, 1, 5, 21), "January, still the season"),
])
def test_in_season_denver_evenings_and_every_weekday_poll(local, label):
    run, why = gate.decide(local.astimezone(UTC))
    assert run, f"{label}: {why}"


@pytest.mark.parametrize("local, label", [
    (denver(2026, 10, 12, 1), "1 AM Denver: quiet hours start"),
    (denver(2026, 10, 12, 3), "3 AM Denver"),
    (denver(2026, 10, 12, 5, 59), "5:59 AM Denver: last quiet minute; the briefing runs at 6"),
    (denver(2026, 12, 3, 3), "3 AM Denver in MST (10:00 UTC)"),
])
def test_small_hours_in_denver_skip(local, label):
    run, why = gate.decide(local.astimezone(UTC))
    assert not run, f"{label}: {why}"
    assert "quiet hours" in why


def test_quiet_hours_follow_denver_not_utc_across_the_dst_change():
    # 09:30 UTC is 3:30 AM MDT (quiet) in October and 2:30 AM MST (quiet) in November: skipped both times.
    assert not gate.decide(datetime(2026, 10, 20, 9, 30, tzinfo=UTC))[0]
    assert not gate.decide(datetime(2026, 11, 10, 9, 30, tzinfo=UTC))[0]
    # 07:30 UTC is 1:30 AM MDT (quiet) in October but 12:30 AM MST (evening) in November: the November run polls.
    assert not gate.decide(datetime(2026, 10, 20, 7, 30, tzinfo=UTC))[0]
    assert gate.decide(datetime(2026, 11, 10, 7, 30, tzinfo=UTC))[0]


@pytest.mark.parametrize("local", [denver(2026, 7, 15, 20), denver(2026, 8, 31, 20), denver(2027, 2, 1, 12)])
def test_off_season_skips(local):
    run, why = gate.decide(local.astimezone(UTC))
    assert not run and "off season" in why


def test_season_boundary_is_the_denver_calendar():
    # 2026-09-01 02:00 UTC is still Aug 31 in Denver: off season. Four hours later it is Sep 1 in Denver.
    assert not gate.decide(datetime(2026, 9, 1, 2, tzinfo=UTC))[0]
    assert gate.decide(datetime(2026, 9, 1, 12, tzinfo=UTC))[0]


def test_manual_runs_always_poll():
    july_3am = denver(2026, 7, 15, 3).astimezone(UTC)
    assert not gate.decide(july_3am, "schedule")[0]
    run, why = gate.decide(july_3am, "workflow_dispatch")
    assert run and "manual" in why


def test_naive_now_is_read_as_utc():
    assert gate.decide(datetime(2026, 10, 12, 2)) == gate.decide(datetime(2026, 10, 12, 2, tzinfo=UTC))


def test_main_prints_and_writes_github_output(tmp_path, capsys, monkeypatch):
    out = tmp_path / "out.txt"
    out.write_text("earlier=1\n")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    assert gate.main(["--now", "2026-10-12T02:00:00Z"]) == 0          # Sunday 8 PM Denver
    assert capsys.readouterr().out.startswith("run=true  in season, Denver 20:xx (Sun 2026-10-11 20:00 MDT)")
    assert out.read_text() == "earlier=1\nrun=true\n"
    assert gate.main(["--now", "2026-10-12T09:00:00+00:00", "--event", "schedule"]) == 0   # 3 AM Denver
    assert capsys.readouterr().out.startswith("run=false  quiet hours")
    assert out.read_text().endswith("run=true\nrun=false\n")


def test_workflow_gate_step_calls_the_script_and_nothing_else_decides():
    """The YAML's first step must defer to the script: no `date -u` arithmetic left to drift from the test."""
    wf = (ROOT / ".github" / "workflows" / "trade-poll.yml").read_text()
    assert "python3 scripts/trade_poll_gate.py" in wf
    assert "date -u" not in wf and '"$dow"' not in wf and '"$hour"' not in wf
    # the gate runs before checkout would be no use: the script has to be on disk first
    assert wf.index("actions/checkout") < wf.index("python3 scripts/trade_poll_gate.py")
    # the window stays wider than GitHub's ~3h real cadence
    assert re.search(r"--new-since \"\$\{\{ github\.event\.inputs\.window \|\| '6h' \}\}\"", wf)
    assert "default: '6h'" in wf
