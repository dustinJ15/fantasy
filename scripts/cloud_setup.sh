#!/usr/bin/env bash
# Bootstrap inside a fresh cloud clone (Claude Code routine). Idempotent.
set -euo pipefail
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}"
export NFLREADPY_TIMEOUT="${NFLREADPY_TIMEOUT:-120}"
cd "$(dirname "$0")/.."
if ! command -v uv >/dev/null 2>&1; then
  pip install --quiet --user uv 2>/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv python install 3.13 >/dev/null 2>&1 || true
uv sync --quiet || uv sync --quiet   # one retry for flaky downloads
# Cookies arrive as environment variables in the cloud; write them to .env so the CLI finds them.
if [ ! -f .env ] && [ -n "${ESPN_S2:-}" ]; then
  printf 'ESPN_S2=%s\nSWID=%s\nSEASON=%s\n' "$ESPN_S2" "$SWID" "${SEASON:-2026}" > .env
fi
# League ids arrive the same way; leagues.toml is untracked. LEAGUES_TOML is either the raw file contents or, because
# the cloud env box is one KEY=VALUE per line, its base64 (`base64 -w0 leagues.toml`).
if [ ! -f leagues.toml ] && [ -n "${LEAGUES_TOML:-}" ]; then
  case "$LEAGUES_TOML" in
    *"[[league]]"*) printf '%s\n' "$LEAGUES_TOML" > leagues.toml ;;
    *) printf '%s' "$LEAGUES_TOML" | tr -d ' \r\n\t' | base64 -d > leagues.toml ;;
  esac
fi
if [ ! -f leagues.toml ]; then
  echo "leagues.toml missing: set the LEAGUES_TOML environment variable (contents of the file) or copy leagues.example.toml" >&2
  exit 2
fi
# Memory that lives on the projlog branch (projection logs, skipped trade rulings): restore it so the packet can read
# it. Best-effort; a fresh repo with no projlog branch is fine.
if [ ! -d data/projlog ]; then
  (git fetch --quiet origin projlog && git checkout --quiet origin/projlog -- data/projlog && git reset --quiet -- data/projlog) || true
fi
uv run ff doctor
