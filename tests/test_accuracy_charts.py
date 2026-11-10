"""`scripts/accuracy_charts.py` draws the README's results charts from `examples/accuracy.json`.

The JSON is a transcription of `docs/accuracy.md`, so the two can drift apart the way the README once did; the Brier
rows are checked against the doc, and the SVGs have to be well-formed and the same bytes every run (the screenshot
script commits them).
"""
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "accuracy_charts.py"
DATA = ROOT / "examples" / "accuracy.json"
DOC = (ROOT / "docs" / "accuracy.md").read_text()


def _run(out_dir: Path) -> dict[str, bytes]:
    subprocess.run([sys.executable, str(SCRIPT), "--out-dir", str(out_dir)], check=True, capture_output=True)
    return {p.name: p.read_bytes() for p in sorted(out_dir.glob("*.svg"))}


def test_charts_are_well_formed_and_deterministic(tmp_path):
    a = _run(tmp_path / "a")
    b = _run(tmp_path / "b")
    assert set(a) == {"calibration.svg", "trade-reliability.svg"}
    assert a == b, "the chart bytes changed between two runs on the same data"
    for name, body in a.items():
        root = ET.fromstring(body)
        assert root.tag.endswith("svg"), name
        assert body.count(b"<circle") + body.count(b"<path") > 10, f"{name} drew almost nothing"


def test_committed_svgs_match_the_script(tmp_path):
    fresh = _run(tmp_path)
    for name, body in fresh.items():
        assert (ROOT / "examples" / name).read_bytes() == body, f"examples/{name} is stale: run scripts/screenshots.sh"


def test_brier_rows_match_the_doc():
    d = json.load(open(DATA))
    for lg, s in d["calibration"]["summary"].items():
        row = re.search(rf"^\| {lg} \| (\d+) \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \|$", DOC, re.M)
        assert row, f"docs/accuracy.md has no Brier row for {lg}"
        assert [int(row.group(1)), float(row.group(2)), float(row.group(3)), float(row.group(4))] == \
            [s["n"], s["brier"], s["log_loss"], s["ece"]], f"{lg} summary differs from docs/accuracy.md"


def test_scan_totals_match_the_doc():
    d = json.load(open(DATA))
    for sample, rows in d["trade_scan"]["totals"].items():
        for lg, (n, hit, promised, realized) in rows.items():
            assert re.search(rf"^\| {lg} \| {re.escape(sample)} \| {n} \| {hit:.2f} \| \+{promised:.2f} \| \+{realized:.2f} \|",
                             DOC, re.M), f"docs/accuracy.md has no matching row for {lg} / {sample}"
