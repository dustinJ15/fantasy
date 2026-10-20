"""The markdown has one shape (TODO Docs-1): an index in `docs/README.md` that names every tracked `.md`, a CLAUDE.md
short enough that loading it every session is cheap, and plan and research docs that carry the same status header
and keep their open work in TODO.md, the only queue.

CLAUDE.md grew to 205 lines (half of it a failure table of fixed bugs) before 2026-10-20; every session paid for
reading it. These checks keep the shape from drifting back.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MAX_LINES = 90
HEADER_LINES = ("Status:", "Written:", "TODO ids:")
# A TODO id as the queue prints it: B12, C5, D9, Docs-1, R1.
ID_RE = re.compile(r"\b([A-Z][A-Za-z]*-?\d+)\b")


def tracked_markdown() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return sorted(p for p in out.split("\n") if p)


def plan_docs() -> list[Path]:
    return sorted(list((ROOT / "docs" / "plans").glob("*.md")) + list((ROOT / "docs" / "research").glob("*.md")))


def test_index_names_every_tracked_markdown_file():
    index = (ROOT / "docs" / "README.md").read_text()
    missing = [p for p in tracked_markdown() if p not in index]
    assert not missing, f"docs/README.md does not list {missing}"


def test_claude_md_stays_short():
    lines = (ROOT / "CLAUDE.md").read_text().count("\n")
    assert lines < CLAUDE_MAX_LINES, f"CLAUDE.md is {lines} lines; every session loads it. Fixed failure rows go to docs/failures.md"


def test_claude_md_links_the_index():
    head = "\n".join((ROOT / "CLAUDE.md").read_text().split("\n")[:5])
    assert "docs/README.md" in head, "CLAUDE.md should point at docs/README.md in its first lines"


@pytest.mark.parametrize("doc", plan_docs(), ids=lambda p: p.name)
def test_plan_has_the_status_header(doc: Path):
    head = doc.read_text().split("\n")[:8]
    for key in HEADER_LINES:
        assert any(line.startswith(key) for line in head), f"{doc.name} has no `{key}` line in its first lines"
    assert "Still open" in doc.read_text(), f"{doc.name} needs a 'Still open' section (or 'Still open: none')"


@pytest.mark.parametrize("doc", plan_docs(), ids=lambda p: p.name)
def test_plan_keeps_no_open_question_outside_the_queue(doc: Path):
    text = doc.read_text()
    assert not re.search(r"^#+ .*Open questions", text, re.M), f"{doc.name}: open questions belong in TODO.md"
    # Still open: either the word none, or TODO ids that TODO.md still lists unchecked.
    m = re.search(r"Still open:?\s*(.*)", text)
    assert m, doc.name
    rest = text[m.end():].split("\n## ")[0] if m.group(1).strip() == "" else m.group(1)
    if rest.strip().lower().startswith("none"):
        return
    todo = (ROOT / "TODO.md").read_text()
    ids = set(ID_RE.findall(rest))
    assert ids, f"{doc.name}: 'Still open' names no TODO id and is not 'none'"
    missing = sorted(i for i in ids if f"- [ ] **{i} (" not in todo)
    assert not missing, f"{doc.name} says {missing} are still open; TODO.md does not list them"
