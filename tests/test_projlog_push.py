"""scripts/projlog_push.sh against a scratch bare remote: the projlog branch takes exactly the new files as a
fast-forward, main and the checkout are untouched, and a ruling edited during the run is not lost (C1, 2026-10-08)."""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "projlog_push.sh"
OLD_CSV = "data/projlog/2026-w05-2026-10-07.csv"
NEW_CSV = "data/projlog/2026-w05-2026-10-08.csv"
SKIPS = "data/projlog/skipped_trades.json"
OLD_SKIPS = '{"L1|Henry": "2026-10-07"}\n'
NEW_SKIPS = '{"L1|Henry": "2026-10-07", "L2|Chase": "2026-10-08"}\n'


def git_env(home: Path) -> dict:
    """No user config: the machine's push.negotiate or default branch must not shape the test."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=str(home), GIT_CONFIG_GLOBAL=str(home / "gitconfig"), GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="seed", GIT_AUTHOR_EMAIL="seed@t", GIT_COMMITTER_NAME="seed", GIT_COMMITTER_EMAIL="seed@t")
    return env


class Scratch:
    def __init__(self, root: Path, with_projlog: bool = True):
        self.root = root
        self.env = git_env(root)
        (root / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n")
        self.remote = root / "remote.git"
        self.git(root, "init", "--quiet", "--bare", str(self.remote))
        seed = root / "seed"
        self.git(root, "init", "--quiet", str(seed))
        (seed / ".gitignore").write_text("data/projlog/\n")
        (seed / "app.py").write_text("code\n")
        self.git(seed, "add", "-A"); self.git(seed, "commit", "--quiet", "-m", "main 1")
        if with_projlog:
            self.git(seed, "checkout", "--quiet", "-b", "projlog")
            (seed / ".gitignore").write_text("!data/projlog/\n")
            (seed / "data/projlog").mkdir(parents=True)
            (seed / OLD_CSV).write_text("old,row\n")
            (seed / SKIPS).write_text(OLD_SKIPS)
            self.git(seed, "add", "-A"); self.git(seed, "commit", "--quiet", "-m", "projlog: week 5 2026-10-07")
            self.git(seed, "checkout", "--quiet", "main")
        (seed / "app2.py").write_text("more\n")
        self.git(seed, "add", "-A"); self.git(seed, "commit", "--quiet", "-m", "main 2")
        self.git(seed, "push", "--quiet", str(self.remote), "main", *(["projlog"] if with_projlog else []))
        self.clone = root / "clone"
        self.git(root, "clone", "--quiet", "--branch", "main", str(self.remote), str(self.clone))

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, text=True, capture_output=True).stdout.strip()

    def remote_git(self, *args: str) -> str:
        return self.git(self.remote, *args)

    def script(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in self.env.items() if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}   # the cloud sets none
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd or self.clone, env=env, text=True, capture_output=True)

    def tip(self, ref: str) -> str:
        return self.remote_git("rev-parse", ref)

    def count(self, ref: str) -> int:
        return int(self.remote_git("rev-list", "--count", ref))

    def checkout_state(self) -> tuple:
        """Everything a push must leave alone: HEAD, the branch, the index, tracked files, local branches."""
        c = self.clone
        return (self.git(c, "rev-parse", "HEAD"), self.git(c, "branch", "--show-current"),
                self.git(c, "status", "--porcelain"), self.git(c, "diff", "--cached", "--name-only"),
                self.git(c, "for-each-ref", "--format=%(refname)", "refs/heads"))


@pytest.fixture
def scratch(tmp_path):
    return Scratch(tmp_path)


def test_restore_lands_untracked_files_and_leaves_the_checkout_alone(scratch):
    before = scratch.checkout_state()
    r = scratch.script("--restore")
    assert r.returncode == 0, r.stderr
    assert "restored data/projlog" in r.stdout
    assert (scratch.clone / OLD_CSV).read_text() == "old,row\n"
    assert (scratch.clone / SKIPS).read_text() == OLD_SKIPS
    assert scratch.checkout_state() == before
    assert scratch.git(scratch.clone, "status", "--porcelain", "--ignored") == "!! data/"


def test_push_fast_forwards_exactly_the_new_files_and_never_touches_main(scratch):
    assert scratch.script("--restore").returncode == 0
    main_before, projlog_before = scratch.tip("main"), scratch.tip("projlog")
    assert scratch.count("projlog") == 2
    before = scratch.checkout_state()
    assert before[1] == "main"

    (scratch.clone / NEW_CSV).write_text("new,row\n")
    (scratch.clone / SKIPS).write_text(NEW_SKIPS)   # the morning's ruling, written by ff render-email
    r = scratch.script("projlog: week 5 2026-10-08")
    assert r.returncode == 0, r.stderr
    assert "pushed" in r.stdout and "origin/projlog" in r.stdout

    # The remote: one new commit, fast-forward from the old tip, carrying exactly the two changed paths.
    tip = scratch.tip("projlog")
    assert scratch.count("projlog") == 3
    assert scratch.remote_git("rev-parse", f"{tip}^") == projlog_before
    assert scratch.remote_git("diff", "--name-only", projlog_before, tip).splitlines() == [NEW_CSV, SKIPS]
    assert scratch.remote_git("show", f"{tip}:{NEW_CSV}") == "new,row"
    assert scratch.remote_git("show", f"{tip}:{SKIPS}") == NEW_SKIPS.strip()
    assert scratch.remote_git("show", f"{tip}:{OLD_CSV}") == "old,row"
    assert scratch.remote_git("show", f"{tip}:.gitignore") == "!data/projlog/"   # the rest of the tree rides along as is
    assert scratch.remote_git("log", "-1", "--format=%s|%an|%cn", tip) == "projlog: week 5 2026-10-08|ff-routine|ff-routine"
    assert scratch.tip("main") == main_before
    assert scratch.remote_git("for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines() == ["main", "projlog"]

    # The clone: still on main at the same commit, nothing staged, no projlog branch, the files still untracked.
    assert scratch.checkout_state() == before
    assert (scratch.clone / SKIPS).read_text() == NEW_SKIPS


def test_push_builds_on_the_remote_tip_not_on_the_restored_one(scratch):
    assert scratch.script("--restore").returncode == 0
    # Another run pushed in between (a re-run, a hand fix): ours must land on top of it, not fork from the stale tip.
    other = scratch.root / "other"
    scratch.git(scratch.root, "clone", "--quiet", "--branch", "projlog", str(scratch.remote), str(other))
    (other / "data/projlog/hand_fix.json").write_text("{}\n")
    scratch.git(other, "add", "-A"); scratch.git(other, "commit", "--quiet", "-m", "projlog: hand fix")
    scratch.git(other, "push", "--quiet", "origin", "projlog")
    mid = scratch.tip("projlog")

    (scratch.clone / NEW_CSV).write_text("new,row\n")
    r = scratch.script("projlog: week 5 2026-10-08")
    assert r.returncode == 0, r.stderr
    tip = scratch.tip("projlog")
    assert scratch.count("projlog") == 4
    assert scratch.remote_git("rev-parse", f"{tip}^") == mid
    assert scratch.remote_git("diff", "--name-only", mid, tip).splitlines() == [NEW_CSV]
    assert scratch.remote_git("show", f"{tip}:data/projlog/hand_fix.json") == "{}"


def test_nothing_to_commit_pushes_nothing(scratch):
    assert scratch.script("--restore").returncode == 0
    tip = scratch.tip("projlog")
    r = scratch.script("projlog: again")
    assert r.returncode == 0, r.stderr
    assert "nothing to commit" in r.stdout
    assert scratch.tip("projlog") == tip and scratch.count("projlog") == 2


def test_a_run_whose_restore_failed_cannot_delete_history(scratch):
    (scratch.clone / "data/projlog").mkdir(parents=True)
    (scratch.clone / NEW_CSV).write_text("new,row\n")   # only today's file on disk, yesterday's never restored
    r = scratch.script("projlog: week 5 2026-10-08")
    assert r.returncode == 0, r.stderr
    tip = scratch.tip("projlog")
    assert scratch.count("projlog") == 3
    assert scratch.remote_git("diff", "--name-only", f"{tip}^", tip).splitlines() == [NEW_CSV]
    assert scratch.remote_git("show", f"{tip}:{OLD_CSV}") == "old,row"
    assert scratch.remote_git("show", f"{tip}:{SKIPS}") == OLD_SKIPS.strip()


def test_first_push_creates_the_branch_with_only_the_logs(tmp_path):
    s = Scratch(tmp_path, with_projlog=False)
    r = s.script("--restore")
    assert r.returncode == 0 and "no projlog branch" in r.stdout
    (s.clone / "data/projlog").mkdir(parents=True)
    (s.clone / NEW_CSV).write_text("new,row\n")
    r = s.script("projlog: week 5 2026-10-08")
    assert r.returncode == 0, r.stderr
    assert s.count("projlog") == 1
    assert s.remote_git("ls-tree", "-r", "--name-only", "projlog").splitlines() == [NEW_CSV]
    assert s.tip("main") == s.git(s.clone, "rev-parse", "HEAD")


def test_no_projlog_dir_is_a_no_op(scratch):
    r = scratch.script("projlog: empty")
    assert r.returncode == 0 and "nothing to push" in r.stdout
    assert scratch.count("projlog") == 2


def test_unreachable_remote_fails_loudly(scratch):
    scratch.git(scratch.clone, "remote", "set-url", "origin", str(scratch.root / "gone.git"))
    (scratch.clone / "data/projlog").mkdir(parents=True)
    (scratch.clone / NEW_CSV).write_text("new,row\n")
    r = scratch.script("projlog: week 5 2026-10-08")
    assert r.returncode == 1
    assert "cannot reach origin" in r.stderr
