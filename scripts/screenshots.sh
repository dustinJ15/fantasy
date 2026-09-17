#!/usr/bin/env bash
# Regenerate everything in examples/ from the demo league. No credentials, no network.
# Needs Google Chrome on PATH (headless screenshot); rich draws the terminal SVG itself.
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="${CHROME:-google-chrome}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

echo "packet + email"
PACKET="$(uv run ff packet --demo --sims 3000 --overrides examples/overrides.json)"
cp "$PACKET" examples/packet.json
uv run ff render-email --packet examples/packet.json --reads examples/reads.json --out examples/briefing.html --md examples/briefing.md

echo "email screenshot"
# First pass: ask the page how tall it is, so the capture is cropped to content instead of a fixed viewport.
sed 's#</body>#<script>document.title=document.documentElement.scrollHeight</script></body>#' examples/briefing.html > "$TMP/measure.html"
H="$("$CHROME" --headless=new --disable-gpu --no-sandbox --window-size=640,800 --dump-dom "file://$TMP/measure.html" 2>/dev/null \
    | grep -o '<title>[0-9]*</title>' | grep -o '[0-9]*')"
"$CHROME" --headless=new --disable-gpu --no-sandbox --hide-scrollbars --force-device-scale-factor=2 \
    --window-size="640,$H" --screenshot=examples/briefing.png "file://$PWD/examples/briefing.html" 2>/dev/null
echo "  examples/briefing.png (640x$H css px @2x)"

echo "terminal svg"
uv run python - <<'PY'
from unittest.mock import patch
from rich.console import Console
from ff import cli
con = Console(record=True, width=96, force_terminal=True, color_system="truecolor", highlight=False)
con.print("[bold green]$[/] ff incoming --demo")
with patch.object(cli, "rprint", con.print):
    try:
        cli.app(["incoming", "--demo", "--sims", "1500"], standalone_mode=False)
    except SystemExit:
        pass
con.save_svg("examples/incoming.svg", title="ff incoming --demo")
print("  examples/incoming.svg")
PY
