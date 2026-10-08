"""README.md names files, commands and numbers; each has to exist in the tree it describes (TODO R1).

The README went stale once (2026-09-23 to 2026-10-08: a test count off by a factor of eight, FAAB bids no league
used, a diagram missing two modules). These checks are cheap and keep it honest.
"""
import glob
import re
import subprocess
import sys
from pathlib import Path

import pytest

from ff.cli import app

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()

# Backticked repo paths: `src/ff/model/lineup.py`, `scripts/projlog_push.sh`, `tests/`, `examples/`, a `*` glob.
PATH_RE = re.compile(r"`((?:src/ff|scripts|tests|examples|docs|\.claude|\.github)/[A-Za-z0-9_./*-]*)`")
# The ff commands the Commands table lists: the first word after `ff` in a backticked cell.
COMMAND_RE = re.compile(r"`ff ([a-z-]+)")
# Terms the 2026-10-08 backlog run put in the model that the README has to mention (TODO R1 lists them as missing).
REQUIRED_PHRASES = ["ledger", "projlog", "wind", "priority", "set lineup", "playoff week",
                    "common random numbers", "handcuff", "doorbell"]


def _readme_paths() -> list[str]:
    seen = []
    for m in PATH_RE.finditer(README):
        p = m.group(1)
        if p not in seen:
            seen.append(p)
    return seen


@pytest.mark.parametrize("path", _readme_paths())
def test_every_backticked_path_exists(path):
    if "*" in path:
        assert glob.glob(str(ROOT / path)), f"README names `{path}` and nothing matches it"
    else:
        assert (ROOT / path).exists(), f"README names `{path}` and it is not in the tree"


def test_readme_names_paths_at_all():
    """Guards the regex: a README with no backticked paths would pass the test above by having nothing to check."""
    assert len(_readme_paths()) >= 5, _readme_paths()


def test_every_ff_command_in_the_table_exists():
    registered = {c.name or c.callback.__name__.replace("_", "-") for c in app.registered_commands}
    named = {m.group(1) for m in COMMAND_RE.finditer(README)}
    assert named, "the Commands table should name ff commands in backticks"
    missing = sorted(named - registered)
    assert not missing, f"README names ff commands that do not exist: {missing}"


def test_test_count_is_not_a_stale_number():
    """A fixed "runs N tests" is allowed only when N is what pytest collects today; the README is better off not
    stating one."""
    m = re.search(r"runs (\d+) tests", README)
    if not m:
        return
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"], cwd=ROOT,
                         capture_output=True, text=True, check=False).stdout
    collected = int(re.search(r"(\d+) tests? collected", out).group(1))
    assert int(m.group(1)) == collected, f"README says {m.group(1)} tests, pytest collects {collected}"


@pytest.mark.parametrize("phrase", REQUIRED_PHRASES)
def test_readme_mentions_the_current_model(phrase):
    assert phrase.lower() in README.lower(), f"README never mentions {phrase!r}"
