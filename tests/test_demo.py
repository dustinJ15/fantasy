"""`ff briefing --demo` and friends run end to end with no credentials, no leagues.toml and no network."""
import json
import re
from pathlib import Path

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
    assert "**IR:** move " in md and " to IR" in md and "**Out:**" in md  # the hurt-player row and the timelines
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
    assert offers[0]["row_id"].startswith("offer:")  # the reads.json key the trade-offer skill rules on


def test_demo_overrides(tmp_path):
    ov = tmp_path / "o.json"
    ov.write_text(json.dumps({"100": {"p_zero": 1.0, "note": "ruled out (demo)"}}))
    r = runner.invoke(app, ["packet", "--demo", "--sims", "100", "--overrides", str(ov)])
    assert r.exit_code == 0, r.output
    p = json.load(open(r.output.strip()))
    me = next(x for x in p["leagues"][0]["roster"] if x["espn_id"] == 100)
    assert me["p_zero"] == 1.0 and me["sources"]["override_note"] == "ruled out (demo)"


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_examples_reads_rule_on_the_current_demo_card():
    """`examples/reads.json` is the one hand-written input in examples/; `scripts/screenshots.sh` renders it against the
    demo packet. It went stale once (TODO R2: the scan moved to a new package, so the trade row was unruled and the
    paste named a player no longer on the card). Same overrides as the script, so the row ids are the ones it renders."""
    from ff import demo, report
    reads = json.load(open(EXAMPLES / "reads.json"))
    p = demo.build_packet(str(EXAMPLES / "overrides.json"), sims=100, write=False)
    assert report.read_lint(p, reads) == []
    assert report.voice_lint(reads) == []
    rows = report.todos(p["leagues"][0])
    assert any(x["kind"] == "trade" for x in rows), "the demo card should carry a trade row for the example to rule on"
    assert len(reads["demo"]["items"]) >= 2, "the example should show more than one ruling"
    card = report.action_card(p, reads, show_ids=False)
    for field in ("paste", "reply"):
        for name in re.findall(r"\b[A-Z][a-z]{2,}\b", reads["demo"][field]):
            assert name in card, f"reads.json {field} names {name}, who is not on the card"


def test_the_demo_card_passes_the_card_lint_and_render_email_prints_it(tmp_path):
    """`ff render-email` runs `report.card_lint` on every league with the rulings in (B19): the demo card is clean, and
    a candidate the scan left without a reason is the one warning a stale packet shows."""
    from ff import demo, report
    p = demo.build_packet(None, sims=100, write=False)
    for lg in p["leagues"]:
        assert report.card_lint(lg) == []
    packet = tmp_path / "p.json"
    packet.write_text(json.dumps(p))
    r = runner.invoke(app, ["render-email", "--packet", str(packet), "--out", str(tmp_path / "b.html")])
    assert r.exit_code == 0, r.output
    assert "card:" not in r.output
    t = p["leagues"][0]["trades"][0]
    t.update(sendable=False, why_not=None, must_try=False, pushed=False)
    packet.write_text(json.dumps(p))
    r = runner.invoke(app, ["render-email", "--packet", str(packet), "--out", str(tmp_path / "b.html")])
    assert r.exit_code == 0, r.output
    assert "card: demo: the detail lists" in r.output and "does not say why" in r.output


def test_the_demo_carries_one_claim_in_and_the_card_prints_it_once():
    """B20: the synthetic league has one claim already placed; the card shows it as a claim in, nothing else adds
    the body or spends the drop, and the lint is clean."""
    from ff import demo, report
    p = demo.build_packet(None, sims=100, write=False)
    lg = p["leagues"][0]
    assert len(lg["pending_claims"]) == 1 and lg["pending_claims"][0]["drop"] == "Malik Okafor" and lg["pending_claims"][0]["bid"] == 9
    rows = report.todos(lg)
    claimed = [x for x in rows if x.get("claimed")]
    assert len(claimed) == 1 and claimed[0]["label"] == "Waiver (claim in)"
    name = claimed[0]["add"]["name"]
    assert claimed[0]["text"].startswith(f"claim in: {name} (RB) ($9, drop Malik Okafor), lands ")
    assert [x["id"] for x in rows if name in report.row_adds(x) or x.get("drop") == "Malik Okafor"] == [claimed[0]["id"]]
    assert report.card_lint(lg) == []
