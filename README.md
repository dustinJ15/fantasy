# ff — fantasy football co-manager

Deterministic analytics for three ESPN redraft leagues, plus a morning briefing that Claude finishes by reading the news.

- **Code owns state and math:** projections blend, injury-aware distributions, value over own starter,
  lineup optimizer that maximizes win probability, Monte Carlo playoff/title odds, trade scanner, FAAB bids.
- **Claude owns judgment and prose:** reads injury/beat-writer news, adjusts `p_zero` / projections via `overrides.json`,
  explains the recommendations, drafts trade pitches, emails the briefing.
- **Read-only against ESPN.** You tap the buttons.

## Quick start
```
uv sync
cp .env.example .env          # see scripts/setup_cookies.md
$EDITOR leagues.toml
uv run ff setup-check
uv run ff sync                # pull ESPN + nflverse + FantasyPros mirror + Sleeper + odds
uv run ff briefing            # markdown for all leagues, no LLM needed
```

## Commands
| command | what |
|---|---|
| `ff setup-check` | verify cookies + league IDs, print teams |
| `ff doctor` | data freshness per source, cookie health |
| `ff sync [--force]` | refresh every source into `data/cache/` |
| `ff roster [--league X]` | my roster with blended projections and flags |
| `ff lineup [--week N]` | P(win)-optimal lineup vs this week's opponent, diff vs E[points] lineup |
| `ff waivers` | ranked free agents, FAAB max bids, streamers |
| `ff trades` | rival roster scan, candidate packages, both-side title-odds delta |
| `ff odds` | Monte Carlo playoff and title odds for every team |
| `ff packet` | write the versioned DecisionPacket JSON to `data/packets/` |
| `ff briefing [--overrides overrides.json]` | render the full markdown briefing |

Data sources are free and keyless: espn-api, nflreadpy, the dynastyprocess FantasyPros mirror, Sleeper, FantasyCalc, ESPN scoreboard odds, Open-Meteo.
