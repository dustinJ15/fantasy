"""`ff briefing --demo` and friends run end to end with no credentials, no leagues.toml and no network."""
import json
import re

from typer.testing import CliRunner

from ff.cli import app

runner = CliRunner()


def test_briefing_demo(tmp_path):
    out = tmp_path / "b.md"
    r = runner.invoke(app, ["briefing", "--demo", "--sims", "150", "--out", str(out)])
    assert r.exit_code == 0, r.output
    md = out.read_text()
    assert "Demo League" in md and "## Waivers" in md and "## League odds" in md
    assert "The Tuesday Regrets offers " in md  # incoming offer verdict is the first checklist item
    assert not re.search(r"\b(RB|WR|TE|QB)\d_\d\b|FA_", md), "demo names should read like people, not fixture codes"


def test_packet_and_incoming_demo(tmp_path):
    r = runner.invoke(app, ["packet", "--demo", "--sims", "100"])
    assert r.exit_code == 0, r.output
    p = json.load(open(r.output.strip()))
    assert p["demo"] is True and p["leagues"][0]["name"] == "demo" and p["shared"]["incoming_trade_count"] == 1
    r = runner.invoke(app, ["incoming", "--demo", "--json", "--sims", "100"])
    assert r.exit_code == 0, r.output
    offers = json.loads(r.output)
    assert len(offers) == 1 and offers[0]["verdict"] in ("accept", "decline", "counter")


def test_demo_overrides(tmp_path):
    ov = tmp_path / "o.json"
    ov.write_text(json.dumps({"100": {"p_zero": 1.0, "note": "ruled out (demo)"}}))
    r = runner.invoke(app, ["packet", "--demo", "--sims", "100", "--overrides", str(ov)])
    assert r.exit_code == 0, r.output
    p = json.load(open(r.output.strip()))
    me = next(x for x in p["leagues"][0]["roster"] if x["espn_id"] == 100)
    assert me["p_zero"] == 1.0 and me["sources"]["override_note"] == "ruled out (demo)"
