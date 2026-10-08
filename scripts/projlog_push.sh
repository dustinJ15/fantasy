#!/usr/bin/env bash
# The projlog branch, both directions, without ever touching the checkout.
#
#   scripts/projlog_push.sh [MESSAGE]     commit data/projlog on top of origin/projlog and push it (fast-forward only)
#   scripts/projlog_push.sh --restore     copy origin/projlog's data/projlog into the working tree as untracked files
#
# Why not `git checkout projlog`: cloud_setup.sh restores data/projlog as untracked files, and git refuses to switch
# to a branch that would overwrite them; the old fallback branched off main and was rejected non-fast-forward, so a
# morning's rulings were lost. This script builds the commit in a temporary index straight from FETCH_HEAD, so HEAD,
# the index and the working tree stay exactly as they were (the clone may be on main or on a detached HEAD, either is
# fine), the commit's parent is the remote tip fetched a moment ago, and the push is a fast-forward. Only additions
# and modifications under data/projlog go in: a file missing from the working tree is kept, never deleted, so a run
# whose restore failed cannot wipe the history. Nothing is ever force-pushed and no branch is rewritten.
#
# Exit codes: 0 pushed or nothing to commit; 1 fetch, push or git failure (the briefing says so in one line and moves on).
set -euo pipefail

REMOTE="${PROJLOG_REMOTE:-origin}"
BRANCH="${PROJLOG_BRANCH:-projlog}"
DIR="data/projlog"
ATTEMPTS=3

export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-ff-routine}" GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-routine@ff.local}"
export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$GIT_AUTHOR_NAME}" GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-$GIT_AUTHOR_EMAIL}"

cd "$(git rev-parse --show-toplevel)"

# Fetch the remote tip into FETCH_HEAD. Prints "tip" (a commit id) or "none" (the branch does not exist yet); exits 1
# when the remote cannot be reached, which is not the same thing as the branch being absent.
fetch_tip() {
  local rc=0
  git ls-remote --exit-code --heads "$REMOTE" "refs/heads/$BRANCH" >/dev/null 2>&1 || rc=$?
  case "$rc" in
    0) git fetch --quiet "$REMOTE" "refs/heads/$BRANCH" >/dev/null && git rev-parse --verify --quiet FETCH_HEAD ;;
    2) echo none ;;
    *) echo "projlog: cannot reach $REMOTE ($BRANCH): ls-remote exit $rc" >&2; return 1 ;;
  esac
}

restore() {
  local tip
  tip="$(fetch_tip)" || return 1
  if [ "$tip" = none ]; then echo "projlog: no $BRANCH branch on $REMOTE yet, nothing to restore"; return 0; fi
  if ! git rev-parse --verify --quiet "$tip:$DIR" >/dev/null; then echo "projlog: $BRANCH has no $DIR, nothing to restore"; return 0; fi
  # git archive | tar never touches the index, unlike `git checkout <rev> -- path`; the files land untracked (and, on
  # main, ignored), which is exactly how the packet reads them and how `push` picks them up.
  git archive --format=tar "$tip" "$DIR" | tar -x
  echo "projlog: restored $DIR from $REMOTE/$BRANCH ($(git rev-parse --short "$tip"))"
}

push() {
  local msg="$1" tip tree parent_tree commit attempt
  if [ ! -d "$DIR" ]; then echo "projlog: no $DIR here, nothing to push"; return 0; fi
  for attempt in $(seq 1 "$ATTEMPTS"); do
    tip="$(fetch_tip)" || return 1
    local index; index="$(mktemp)"
    rm -f "$index"   # git wants to create the index file itself
    (
      export GIT_INDEX_FILE="$index"
      if [ "$tip" != none ]; then git read-tree "$tip"; fi
      git add --force --ignore-removal -- "$DIR"
      git write-tree
    ) > "$index.tree"
    tree="$(tail -n1 "$index.tree")"; rm -f "$index" "$index.tree"
    if [ "$tip" != none ]; then
      parent_tree="$(git rev-parse "$tip^{tree}")"
      if [ "$tree" = "$parent_tree" ]; then echo "projlog: nothing to commit ($REMOTE/$BRANCH already has $DIR as it is)"; return 0; fi
      commit="$(git commit-tree "$tree" -p "$tip" -m "$msg")"
    else
      commit="$(git commit-tree "$tree" -m "$msg")"
    fi
    # Plain refspec, no force: the remote only takes a fast-forward. If somebody pushed in between, go round again
    # from the new tip; the commit is rebuilt from scratch, so nothing is ever rewritten.
    if git push --quiet "$REMOTE" "$commit:refs/heads/$BRANCH" 2>/dev/null; then
      echo "projlog: pushed $(git rev-parse --short "$commit") to $REMOTE/$BRANCH ($msg)"
      return 0
    fi
    echo "projlog: push attempt $attempt rejected, refetching" >&2
  done
  echo "projlog: push to $REMOTE/$BRANCH failed after $ATTEMPTS attempts" >&2
  return 1
}

case "${1:-}" in
  --restore) restore ;;
  -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
  *) push "${1:-projlog: $(date -u +%F)}" ;;
esac
