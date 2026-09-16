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
# League ids arrive the same way (LEAGUES_TOML holds the file's contents); leagues.toml is untracked.
if [ ! -f leagues.toml ] && [ -n "${LEAGUES_TOML:-}" ]; then
  printf '%s\n' "$LEAGUES_TOML" > leagues.toml
fi
if [ ! -f leagues.toml ]; then
  echo "leagues.toml missing: set the LEAGUES_TOML environment variable (contents of the file) or copy leagues.example.toml" >&2
  exit 2
fi
uv run ff doctor
