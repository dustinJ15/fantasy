from __future__ import annotations

import json
from datetime import date

import typer
from rich import print as rprint
from rich.table import Table

from . import cache, report
from . import packet as packet_mod
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
            rprint(f"[red]{exc}[/]"); raise typer.Exit(1) from exc
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
    from .sources import fantasycalc, fantasypros, sleeper, vegas
    fantasypros.weekly_ecr(force); fantasypros.player_ids(force); rprint("fantasypros mirror ok")
    sleeper.players(force); sleeper.trending("add", 24, 100, force); rprint("sleeper ok")
    vegas.implied_totals(force=force); rprint("odds ok")
    fantasycalc.values(force=force); rprint("fantasycalc ok")
    for ref in leagues():
        packet_mod.league_snapshot(ref, force=True); rprint(f"espn {ref.name} ok")


DemoOpt = typer.Option(False, "--demo", help="Synthetic league, no ESPN account or network needed")


def _packet(league, overrides, sims=3000, demo=False):
    if demo:
        from . import demo as demo_mod
        return demo_mod.build_packet(overrides, sims=sims)
    return packet_mod.build(league, overrides, sims=sims)


@app.command("packet")
def packet_cmd(league: str | None = LeagueOpt, overrides: str | None = typer.Option(None), sims: int = 3000, demo: bool = DemoOpt):
    """Write the DecisionPacket JSON and print its path."""
    p = _packet(league, overrides, sims, demo)
    rprint(p["_path"])


def _load_json(path: str | None) -> dict | None:
    return json.load(open(path)) if path else None


@app.command()
def briefing(league: str | None = LeagueOpt, overrides: str | None = typer.Option(None), out: str | None = typer.Option(None), sims: int = 3000,
             short: bool = typer.Option(False, "--short", help="Action card only, no detail tables"),
             html: str | None = typer.Option(None, "--html", help="Also write an email-ready HTML file here"),
             reads: str | None = typer.Option(None, "--reads", help="reads.json with Claude's per-league read"),
             demo: bool = DemoOpt):
    """Render the markdown briefing: action card first, full detail below (no LLM needed)."""
    p = _packet(league, overrides, sims, demo)
    r = _load_json(reads)
    md = report.render(p, detail=not short, reads=r)
    path = out or str(PACKET_DIR / f"briefing-{date.today().isoformat()}.md")
    open(path, "w").write(md)
    if html:
        from .email_html import render_email
        open(html, "w").write(render_email(p, r))
    print(md)
    rprint(f"\n[dim]written to {path}{' and ' + html if html else ''}; packet {p['_path']}[/]")


@app.command("render-email")
def render_email_cmd(packet: str = typer.Option(..., "--packet", help="packet JSON written by `ff packet` / `ff briefing`"),
                     out: str = typer.Option("briefing.html", "--out"),
                     reads: str | None = typer.Option(None, "--reads", help="reads.json with Claude's per-league read"),
                     md: str | None = typer.Option(None, "--md", help="Also rewrite the markdown (plain-text body) with the reads"),
                     only_incoming: bool = typer.Option(False, "--only-incoming", help="Short alert email: just the incoming offers and the reply"),
                     full: bool = typer.Option(False, "--full", help="Append the full detail tables to the HTML (default: action cards only; the detail is in the markdown part)")):
    """Render the HTML email from an existing packet (seconds, no sims)."""
    from .email_html import render_email
    p = json.load(open(packet))
    r = _load_json(reads)
    for warn in report.voice_lint(r or {}):
        rprint(f"[yellow]voice: {warn}[/]")
    for warn in report.read_lint(p, r):
        rprint(f"[yellow]reads: {warn}[/]")
    open(out, "w").write(render_email(p, r, only_incoming=only_incoming, full=full))
    if md:
        open(md, "w").write(report.render(p, reads=r, only_incoming=only_incoming))
    rprint(f"[green]wrote {out}{' and ' + md if md else ''}[/]")


@app.command("to-html")
def to_html_cmd(file: str = typer.Argument(...), out: str = typer.Argument(...)):
    """Convert a generic markdown file to email HTML (legacy; the briefing uses render-email)."""
    from .html import to_html
    open(out, "w").write(to_html(open(file).read()))
    rprint(f"[green]wrote {out}[/]")


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


def _parse_since(txt: str) -> float:
    """'40m' / '6h' / '2d' -> seconds."""
    unit = txt[-1].lower()
    mult = {"m": 60, "h": 3600, "d": 86400}.get(unit)
    if mult is None:
        raise typer.BadParameter("use a number followed by m, h or d, e.g. 40m")
    return float(txt[:-1]) * mult


@app.command()
def incoming(league: str | None = LeagueOpt, sims: int = 1500,
             as_json: bool = typer.Option(False, "--json", help="Print the incoming_trades blocks as JSON"),
             new_since: str | None = typer.Option(None, "--new-since", help="Only offers proposed within this window (e.g. 40m); implies --json, always exits 0"),
             force: bool = typer.Option(False, "--force", help="Re-read ESPN instead of the 15-minute snapshot cache"),
             demo: bool = DemoOpt):
    """Offers other managers sent me, with an accept / decline / counter verdict. Read-only; you tap the button."""
    import time
    if new_since:
        # poller path: cheap sims, fresh ESPN read, JSON only
        cutoff_ms = (time.time() - _parse_since(new_since)) * 1000
        sims, as_json, force = min(sims, 200), True, True
    p = _packet(league, None, sims, demo) if demo else packet_mod.build(league, None, force=force, sims=sims)
    found = []
    for lg in p["leagues"]:
        for t in lg["incoming_trades"]:
            if new_since and (t.get("proposed_ts") or 0) < cutoff_ms:
                continue
            found.append({"league": lg["name"], "league_name": lg["league_name"], "week": lg["week"], **t})
    if as_json:
        print(json.dumps(found, indent=1, default=str)); return
    for lg in p["leagues"]:
        rprint(f"\n[bold]{lg['league_name']} — week {lg['week']}[/]")
        if lg.get("pending_trades_error"):
            rprint(f"[red]could not read pending trades: {lg['pending_trades_error']}[/]")
        for t in lg["incoming_trades"]:
            mk = f"  market {t['market_get']} for {t['market_give']}" if t.get("market_give") and t.get("market_get") else ""
            rprint(f"- [bold]{t['verdict'].upper()}[/] {report.incoming_line(t)}{mk}  {'; '.join(t['why'])}")
        for t in lg["outgoing_trades"]:
            rprint(f"- [dim]sent: your {', '.join(t['give'])} for {', '.join(t['get'])} to {t['rival']}[/]")
        if not lg["incoming_trades"] and not lg["outgoing_trades"]:
            rprint("[dim]no offers pending[/]")


@app.command()
def odds(league: str | None = LeagueOpt):
    for lg in _section(league, "odds"):
        t = Table("team", "record", "playoff %", "title %", "exp W")
        for _tid, o in sorted(lg["odds"].items(), key=lambda kv: -kv[1]["title_pct"]):
            t.add_row(("★ " if o["is_me"] else "") + o["name"], o["record"], str(o["playoff_pct"]), str(o["title_pct"]), str(o["exp_wins"]))
        rprint(t)


@app.command()
def email(file: str = typer.Argument(..., help="markdown file to send"), subject: str | None = typer.Option(None), to: str | None = typer.Option(None),
          html: str | None = typer.Option(None, "--html", help="HTML file from `ff render-email` to use as the rich body")):
    """Email a briefing via Gmail SMTP (needs GMAIL_USER / GMAIL_APP_PASSWORD in .env)."""
    from . import mail
    body = open(file).read()
    subj = subject or f"FF briefing — {date.today().isoformat()}"
    mail.send(subj, body, to, html=open(html).read() if html else None)
    rprint(f"[green]sent '{subj}' to {to or 'self'}[/]")


@app.command("log-projections")
def log_projections(league: str | None = LeagueOpt):
    """Append today's per-source projections to data/projlog/ (for accuracy tracking)."""
    from . import projlog
    p = _packet(league, None, sims=200)
    rprint(projlog.write(p))


@app.command()
def accuracy():
    """MAE / bias by source × position over logged weeks (needs >=1 completed week)."""
    from . import projlog
    from .sources import sleeper
    wk = sleeper.state().get("week", 1)
    df = projlog.accuracy(env().season, wk)
    if df.is_empty():
        rprint("no completed weeks logged yet"); return
    t = Table("pos", "source", "n", "MAE", "bias")
    for r in df.iter_rows(named=True):
        t.add_row(r["pos"], r["source"], str(r["n"]), str(r["mae"]), str(r["bias"]))
    rprint(t)


@app.command()
def heartbeat(fail: bool = typer.Option(False, "--fail", help="Report failure instead of success")):
    """Ping HEALTHCHECK_URL (healthchecks.io dead-man's switch). No-op if unset."""
    import os

    import requests
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
