from __future__ import annotations

import json
from datetime import date

import typer
from rich import print as rprint
from rich.table import Table

from . import cache, packet as packet_mod, report
from .config import PACKET_DIR, env, leagues
from .sources import espn

app = typer.Typer(help="Fantasy football co-manager (read-only against ESPN).", no_args_is_help=True)
LeagueOpt = typer.Option(None, "--league", "-l", help="Only this league (name from leagues.toml)")


@app.command()
def setup_check(league: str | None = LeagueOpt):
    """Verify cookies + league IDs; print teams and which is mine."""
    e = env()
    if not e.has_cookies:
        rprint("[yellow]No ESPN_S2/SWID in .env — public leagues only.[/]")
    for ref in leagues(league):
        try:
            lg = espn.connect(ref)
        except espn.CookieError as exc:
            rprint(f"[red]{exc}[/]"); raise typer.Exit(1)
        me = espn.my_team(lg, ref.team_id)
        rprint(f"[bold]{ref.name}[/] → {lg.settings.name} ({lg.settings.team_count} teams, week {lg.current_week}, FAAB={lg.settings.faab})")
        for t in lg.teams:
            rprint(f"   {'★' if me and t.team_id == me.team_id else ' '} {t.team_id:>2} {t.team_name}  {t.wins}-{t.losses}")
        if not me:
            rprint("   [yellow]could not identify my team from SWID; check SWID braces/case[/]")


@app.command()
def doctor():
    """Data freshness and cookie health."""
    ok = True
    for ref in leagues():
        try:
            lg = espn.connect(ref); lg.scoreboard()
            rprint(f"[green]ESPN {ref.name}: ok (week {lg.current_week})[/]")
        except espn.CookieError as exc:
            ok = False; rprint(f"[red]ESPN {ref.name}: COOKIES DEAD — {exc}[/]")
    t = Table("cache file", "age (h)")
    for name, age in cache.freshness().items():
        t.add_row(name, f"{age/3600:.1f}")
    rprint(t)
    if not ok:
        raise typer.Exit(2)


@app.command()
def sync(force: bool = typer.Option(False, "--force", help="Ignore cache TTLs")):
    """Refresh all sources."""
    from .sources import fantasypros, sleeper, vegas, fantasycalc
    fantasypros.weekly_ecr(force); fantasypros.player_ids(force); rprint("fantasypros mirror ok")
    sleeper.players(force); sleeper.trending("add", 24, 100, force); rprint("sleeper ok")
    vegas.implied_totals(force=force); rprint("odds ok")
    fantasycalc.values(force=force); rprint("fantasycalc ok")
    for ref in leagues():
        packet_mod.league_snapshot(ref, force=True); rprint(f"espn {ref.name} ok")


def _packet(league, overrides, sims=3000):
    return packet_mod.build(league, overrides, sims=sims)


@app.command("packet")
def packet_cmd(league: str | None = LeagueOpt, overrides: str | None = typer.Option(None), sims: int = 3000):
    """Write the DecisionPacket JSON and print its path."""
    p = _packet(league, overrides, sims)
    rprint(p["_path"])


@app.command()
def briefing(league: str | None = LeagueOpt, overrides: str | None = typer.Option(None), out: str | None = typer.Option(None), sims: int = 3000):
    """Render the full markdown briefing (no LLM needed)."""
    p = _packet(league, overrides, sims)
    md = report.render(p)
    path = out or str(PACKET_DIR / f"briefing-{date.today().isoformat()}.md")
    open(path, "w").write(md)
    print(md)
    rprint(f"\n[dim]written to {path}[/]")


def _section(league, key, sims=1500):
    p = _packet(league, None, sims)
    for lg in p["leagues"]:
        rprint(f"\n[bold]{lg['league_name']} — week {lg['week']}[/]")
        yield lg


@app.command()
def roster(league: str | None = LeagueOpt):
    for lg in _section(league, "roster"):
        t = Table("player", "pos", "slot", "wk μ", "sd", "p0", "ROS/g", "flags")
        for p in lg["roster"]:
            t.add_row(p["name"], p["pos"], p["slot"], str(p["mu"]), str(p["sd"]), str(p["p_zero"]), str(p["mu_ros"]), ", ".join(p["flags"]))
        rprint(t)


@app.command()
def lineup(league: str | None = LeagueOpt):
    for lg in _section(league, "lineup"):
        lw = lg["lineup_win"]
        rprint(f"vs {lg['opponent']['name']} ({lg['opponent']['mu']} ± {lg['opponent']['sd']})  P(win)={lw['p_win']}  proj {lw['mu']} ± {lw['sd']}")
        for s, names in lw["slots"].items():
            rprint(f"  {s:10} {', '.join(names)}")
        if lg["lineup_diff"]:
            rprint("[dim]diff vs E[points] lineup:[/]", lg["lineup_diff"])


@app.command()
def waivers(league: str | None = LeagueOpt):
    for lg in _section(league, "waivers"):
        t = Table("target", "pos", "wk μ", "ROS/g", "Δ starter", "bid", "why")
        for w in lg["waivers"]:
            t.add_row(w["name"], w["pos"], str(w["mu_week"]), str(w["mu_ros"]), f"+{w['delta_over_starter']} {w['slot']}", f"${w['bid']}", "; ".join(w["why"][:3]))
        rprint(t)


@app.command()
def trades(league: str | None = LeagueOpt):
    for lg in _section(league, "trades"):
        for c in lg["trades"]:
            rprint(f"- give {c['give']} → get {c['get']} ({c['rival']}): me {c['my_delta_ppw']:+.1f}, them {c['their_delta_ppw']:+.1f}  {c['why']}")


@app.command()
def odds(league: str | None = LeagueOpt):
    for lg in _section(league, "odds"):
        t = Table("team", "record", "playoff %", "title %", "exp W")
        for tid, o in sorted(lg["odds"].items(), key=lambda kv: -kv[1]["title_pct"]):
            t.add_row(("★ " if o["is_me"] else "") + o["name"], o["record"], str(o["playoff_pct"]), str(o["title_pct"]), str(o["exp_wins"]))
        rprint(t)


@app.command()
def email(file: str = typer.Argument(..., help="markdown file to send"), subject: str | None = typer.Option(None), to: str | None = typer.Option(None)):
    """Email a briefing markdown file via Gmail SMTP (needs GMAIL_USER / GMAIL_APP_PASSWORD in .env)."""
    from . import mail
    body = open(file).read()
    subj = subject or f"FF briefing — {date.today().isoformat()}"
    mail.send(subj, body, to)
    rprint(f"[green]sent '{subj}' to {to or 'self'}[/]")


@app.command()
def heartbeat(fail: bool = typer.Option(False, "--fail", help="Report failure instead of success")):
    """Ping HEALTHCHECK_URL (healthchecks.io dead-man's switch). No-op if unset."""
    import os, requests
    url = os.getenv("HEALTHCHECK_URL")
    if not url:
        rprint("[dim]HEALTHCHECK_URL not set; skipping heartbeat[/]"); return
    try:
        requests.get(url.rstrip("/") + ("/fail" if fail else ""), timeout=15)
        rprint(f"[green]heartbeat {'FAIL' if fail else 'ok'} sent[/]")
    except Exception as exc:
        rprint(f"[yellow]heartbeat failed: {exc}[/]")


if __name__ == "__main__":
    app()
