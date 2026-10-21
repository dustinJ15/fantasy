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
    from . import mail
    rprint(f"[{'green' if mail.configured() else 'yellow'}]{mail.status()}[/]")
    if not ok:
        raise typer.Exit(2)


@app.command()
def sync(force: bool = typer.Option(False, "--force", help="Ignore cache TTLs")):
    """Refresh all sources."""
    from .sources import fantasycalc, fantasypros, sleeper, vegas
    fantasypros.weekly_ecr(force); fantasypros.player_ids(force); rprint("fantasypros mirror ok")
    # The player dump carries the injury designations and Sleeper is often a day ahead of ESPN on an IR or
    # season-ending tag, so it is refreshed every run (one download) rather than on its daily TTL.
    sleeper.players(True); sleeper.trending("add", 24, 100, force); rprint("sleeper ok")
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
    if r:
        from .rulings import record_rulings
        for line in record_rulings(p, r):
            rprint(f"[dim]remembered: {line}[/]")
    for warn in report.read_lint(p, r):
        rprint(f"[yellow]reads: {warn}[/]")
    for lg in p["leagues"]:  # the card as a whole, with the rulings in: a skipped row is off it (B19)
        for warn in report.card_lint(lg, report.apply_reads(report.todos(lg), (r or {}).get(lg["name"]))):
            rprint(f"[yellow]card: {lg['name']}: {warn}[/]")
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
            rprint(f"[dim]diff vs E[points] lineup (+{(lw.get('win_gain') or 0) * 100:.1f} pp P(win)):[/]", lg["lineup_diff"])


@app.command()
def waivers(league: str | None = LeagueOpt):
    for lg in _section(league, "waivers"):
        t = Table("target", "pos", "wk μ", "ROS/g", "Δ starter", "bid", "why")
        for w in lg["waivers"]:
            t.add_row(w["name"], w["pos"], str(w["mu_week"]), str(w["mu_ros"]), f"+{w['delta_over_starter']} {w['slot']}", f"${w['bid']}", "; ".join(w["why"][:3]))
        rprint(t)


@app.command()
def trades(league: str | None = LeagueOpt,
           explain: bool = typer.Option(False, "--explain", help="Print the acceptance scorecard behind each row (p(accept), its factors, what he is left with, the fallback)")):
    for lg in _section(league, "trades"):
        for c in lg["trades"]:
            word = f" · {c['accept_word']}" if c.get("accept_word") else ""
            rprint(f"- give {c['give']} → get {c['get']} ({c['rival']}): me {c['my_delta_ppw']:+.1f}, them {c['their_delta_ppw']:+.1f}{word}  {c['why']}")
            if explain:
                rprint(f"    p(accept) {c.get('p_accept')}: {'; '.join(c.get('accept_why') or []) or 'no factor moved it'}")
                rprint(f"    chart from his side {c.get('fair_his')}, best player {c.get('best_side') or 'unpriced'}, sendable {c.get('sendable')}, must_try {c.get('must_try')}")
                if c.get("after_line"):
                    rprint(f"    {c['after_line']}")
                if c.get("fallback"):
                    rprint(f"    {c['fallback']['text']}")


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
        # `row_id` is the row's reads.json key (`offer:<get>`), so the trade-offer skill can rule on it without a
        # draft render; `id` stays ESPN's transaction id
        for t, row in zip(lg["incoming_trades"], report.offer_rows(lg, None)):
            if new_since and (t.get("proposed_ts") or 0) < cutoff_ms:
                continue
            found.append({"league": lg["name"], "league_name": lg["league_name"], "week": lg["week"], "row_id": row["id"], **t})
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
            if t.get("accepted"):
                rprint(f"- [green]accepted{report.processes_note(t)}: your {', '.join(t['give'])} for {', '.join(t['get'])} with {t['rival']}[/]")
            else:
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
    """Email a briefing: the Apps Script relay over HTTPS (FF_MAIL_RELAY_URL / FF_MAIL_RELAY_TOKEN) or Gmail SMTP (GMAIL_USER / GMAIL_APP_PASSWORD)."""
    from . import mail
    body = open(file).read()
    subj = subject or f"FF briefing — {date.today().isoformat()}"
    sent_to = mail.send(subj, body, to, html=open(html).read() if html else None)
    rprint(f"[green]sent '{subj}' to {sent_to}[/]")


@app.command("log-projections")
def log_projections(league: str | None = LeagueOpt):
    """Append today's per-source projections to data/projlog/ (for accuracy tracking)."""
    from . import projlog
    p = _packet(league, None, sims=200)
    rprint(projlog.write(p))


@app.command()
def accuracy(week: int | None = typer.Option(None, "--week", help="Score the weeks before this one (default: the newest log's week)"),
             fit: bool = typer.Option(False, "--fit", help="Fit BASE_SIGMA / CV_FLOOR per position to the blend residuals and print "
                                                             "them next to the current constants (writes nothing)")):
    """MAE / bias by source × position over logged weeks (needs >=1 completed week). Offline: the week comes from the log."""
    from . import projlog
    wk = week if week is not None else projlog.current_week(env().season)
    if fit:
        rows = projlog.sigma_fit(env().season, wk) if wk is not None else []
        if not any(r["n"] for r in rows):
            rprint("no completed weeks logged yet"); return
        rprint(f"[dim]blend residuals of the weeks before week {wk}; sigma = max({projlog.projections.SIGMA_FLOOR_FRAC} × BASE_SIGMA, "
               f"CV_FLOOR × mu), Gaussian NLL on a grid; a position is fitted at n ≥ {projlog.FIT_MIN_N}[/]")
        t = Table("pos", "n", "BASE_SIGMA now", "fit", "CV_FLOOR now", "fit", "on floor", "rmse", "verdict")
        for r in rows:
            base = "—" if r["base_fit"] is None else f"{r['base_fit']:.1f}"
            cv = "—" if r["cv_fit"] is None else f"{r['cv_fit']:.2f}"
            verdict = "fit" if r["fitted"] else f"keep prior (n < {r['min_n']})"
            if r["n"] and r["base_fit"] is None:
                verdict += "; floor never binds, BASE_SIGMA unidentified"
            t.add_row(r["pos"], str(r["n"]), str(r["base_prior"]), base, str(r["cv_prior"]), cv, str(r["floor_rows"]),
                      "—" if r["rmse"] is None else str(r["rmse"]), verdict)
        rprint(t); return
    df = projlog.accuracy(env().season, wk) if wk is not None else projlog.pl.DataFrame()
    if df.is_empty():
        rprint("no completed weeks logged yet"); return
    rprint(f"[dim]weeks before week {wk} ({'--week' if week is not None else 'the newest log'})[/]")
    t = Table("pos", "source", "n", "MAE", "bias")
    for r in df.iter_rows(named=True):
        t.add_row(r["pos"], r["source"], str(r["n"]), str(r["mae"]), str(r["bias"]))
    rprint(t)


@app.command("fit-opportunity")
def fit_opportunity(start: int = typer.Option(2016, "--from", help="First season of the training sample"),
                    end: int = typer.Option(2025, "--to", help="Last season (the live season is partial; leave it out)")):
    """Fit OPPORTUNITY_WEIGHT and OPPORTUNITY_RATIO_CLIP (model/projections.py) and XFP_PER_ATTEMPT (model/usage.py), then
    OPPONENT_K (this week's opponent factor), VEGAS_K (this week's implied total, on nflverse schedules' closing
    lines) and TREND_K (the last three games' usage against the season's), to nflverse weekly stats of past seasons, leave-one-season-out, and print
    them next to the constants (writes nothing; docs/plans/fitted-projection.md says how to adopt a row). Needs the
    network, no cookies."""
    from . import opfit
    out = opfit.run(range(start, end + 1))
    a = out["attempt"]
    rprint(f"[dim]{out['rows']} training rows over {start}-{end}: a player at a week, his season so far on one side (≥ "
           f"{opfit.projections.OPPORTUNITY_MIN_GAMES} games, ≥ {opfit.FIT_MIN_PPG} PPR a game) and his points a game over the rest of "
           f"it on the other (≥ {opfit.FIT_MIN_GAMES_AFTER} games); the model is `opportunity_mult`'s, scored leave-one-season-out[/]")
    rng = f"{min(a['by_season'].values())}-{max(a['by_season'].values())} by season" if a["by_season"] else "no QB rows"
    rprint(f"XFP_PER_ATTEMPT now {opfit.usage.XFP_PER_ATTEMPT}; fit {a['per_attempt']} on {a['n']} QB weeks ({rng}; "
           f"attempts and carries both free: {a['joint']})")
    for pos, v in out["values"].items():
        rprint(f"[dim]{pos} per-opportunity refit (information only): target {v['per_target']}, carry {v['per_carry']}, "
               f"air yard {v['per_air_yard']} on {v['n']} weeks[/]")
    clip, table = out["clip"], out["clip_table"]
    prior = opfit.projections.OPPORTUNITY_RATIO_CLIP
    rprint(f"OPPORTUNITY_RATIO_CLIP now {prior} (pooled rmse {table[prior]}); fit {clip} (pooled rmse {table[clip]}); "
           f"no clip at all {table[opfit.NO_CLIP]}")
    t = Table("pos", "n", "WEIGHT now", "fit", "rmse w=0", "rmse now", "rmse fit", "folds", "verdict")
    for r in out["weights"]:
        folds = f"{min(r['w_folds'])}-{max(r['w_folds'])}" if r["w_folds"] else "—"
        verdict = "fit" if r["fitted"] else ("keep prior" if r["n"] >= r["min_n"] else f"keep prior (n < {r['min_n']})")
        t.add_row(r["pos"], str(r["n"]), str(r["w_prior"]), "—" if r["w_fit"] is None else str(r["w_fit"]),
                  str(r["rmse_none"]), str(r["rmse_prior"]), str(r["rmse_fit"]), folds, verdict)
    rprint(t)
    for r in out["weights"]:
        if r["w_by_games"]:
            rprint(f"[dim]{r['pos']} weight by games played: " + ", ".join(f"{k}: {v[0]} (n {v[1]})" for k, v in r["w_by_games"].items() if v[0] is not None) + "[/]")
    opp = out["opponent"]
    rprint(f"[dim]{opp['rows']} opponent rows: a player at a week (≥ {opfit.projections.OPPORTUNITY_MIN_GAMES} games, ≥ {opfit.FIT_MIN_PPG} PPR a "
           f"game so far), the defense he faced with its schedule-adjusted points-allowed factor through the week before (≥ "
           f"{opfit.projections.OPPONENT_MIN_GAMES} games), and his points that week; the model is `opponent_mult`'s, "
           f"`ppg * (1 + k * (factor - 1))` held to ±{opfit.projections.OPPONENT_MULT_CAP:.0%}, scored leave-one-season-out[/]")
    t = Table("pos", "n", "OPPONENT_K now", "fit", "rmse k=0", "rmse now", "rmse fit", "folds", "verdict")
    for r in opp["weeks"]:
        folds = f"{min(r['k_folds'])}-{max(r['k_folds'])}" if r["k_folds"] else "—"
        verdict = "fit" if r["fitted"] else ("keep prior" if r["n"] >= r["min_n"] else f"keep prior (n < {r['min_n']})")
        t.add_row(r["pos"], str(r["n"]), str(r["k_prior"]), "—" if r["k_fit"] is None else str(r["k_fit"]),
                  str(r["rmse_none"]), str(r["rmse_prior"]), str(r["rmse_fit"]), folds, verdict)
    rprint(t)
    for r in opp["weeks"]:
        if r["k_fit"] is not None:
            rprint(f"[dim]{r['pos']}: without the cap rmse {r['rmse_nocap']}, the cap binds on {r['cap_binds']:.1%} of rows; the unadjusted "
                   f"factor fits k {r['k_raw']} at rmse {r['rmse_raw']}; k by the defense's games played: "
                   + ", ".join(f"{k}: {v[0]} (n {v[1]})" for k, v in r["k_by_def_games"].items() if v[0] is not None) + "[/]")
    veg = out["vegas"]
    rprint(f"[dim]{veg['rows']} implied-total rows: a player at a week (≥ {opfit.projections.OPPORTUNITY_MIN_GAMES} games, ≥ {opfit.FIT_MIN_PPG} PPR a "
           f"game so far), his level moved toward his usage by `opportunity_mult`, times this week's opponent multiplier at "
           f"OPPONENT_K, and his team's implied total off nflverse's closing line; the model is `blend`'s, "
           f"`level * (1 + k * (implied / {opfit.projections.LEAGUE_AVG_IMPLIED} - 1))`, scored leave-one-season-out. Mean implied "
           f"total over every team-game: {veg['league_implied']} (LEAGUE_AVG_IMPLIED {opfit.projections.LEAGUE_AVG_IMPLIED})[/]")
    t = Table("pos", "n", "VEGAS_K now", "fit", "rmse k=0", "rmse now", "rmse fit", "folds", "k on raw ppg", "verdict")
    for r in veg["weeks"]:
        folds = f"{min(r['k_folds'])}-{max(r['k_folds'])}" if r["k_folds"] else "—"
        verdict = "fit" if r["fitted"] else ("keep prior" if r["n"] >= r["min_n"] else f"keep prior (n < {r['min_n']})")
        t.add_row(r["pos"], str(r["n"]), str(r["k_prior"]), "—" if r["k_fit"] is None else str(r["k_fit"]),
                  str(r["rmse_none"]), str(r["rmse_prior"]), str(r["rmse_fit"]), folds, "—" if r["k_ppg"] is None else str(r["k_ppg"]), verdict)
    rprint(t)
    tr = out["trend"]
    rprint(f"[dim]{tr['rows']} trend rows: step 1's rows, his level moved toward his usage by `opportunity_mult` (trend off), and his last "
           f"{opfit.projections.RECENT_GAMES} games' xFP-lite a game over his season's, held to {opfit.projections.OPPORTUNITY_RATIO_CLIP}; the model is "
           f"`trend_mult`'s, `level * (1 + t * (ratio - 1))`, scored leave-one-season-out[/]")
    t = Table("pos", "n", "TREND_K now", "fit", "rmse t=0", "rmse now", "rmse fit", "folds", "moved ≥10%", "verdict")
    for r in tr["weeks"]:
        folds = f"{min(r['t_folds'])}-{max(r['t_folds'])}" if r["t_folds"] else "—"
        verdict = "fit" if r["fitted"] else ("keep prior" if r["n"] >= r["min_n"] else f"keep prior (n < {r['min_n']})")
        t.add_row(r["pos"], str(r["n"]), str(r["t_prior"]), "—" if r["t_fit"] is None else str(r["t_fit"]), str(r["rmse_none"]),
                  str(r["rmse_prior"]), str(r["rmse_fit"]), folds, "—" if r["moved"] is None else f"{r['moved']:.0%}", verdict)
    rprint(t)
    for r in tr["weeks"]:
        if r["t_by_games"]:
            rprint(f"[dim]{r['pos']} t by games played: " + ", ".join(f"{k}: {v[0]} (n {v[1]})" for k, v in r["t_by_games"].items() if v[0] is not None) + "[/]")


@app.command("replay-pull")
def replay_pull(season: int = typer.Option(..., "--season", help="The season to archive (a past one, or the current one up to last week)"),
                league: str | None = LeagueOpt):
    """Archive a season's box scores (every matchup, both lineups as set, ESPN's pre-kickoff projection and the actual
    per player) into data/replay/ for `ff backtest`. Read-only; needs the cookies."""
    from . import backtest
    for ref in leagues(league):
        try:
            lg = espn.connect(ref, season)
        except espn.CookieError as exc:
            rprint(f"[red]{exc}[/]"); raise typer.Exit(1) from exc
        rep = backtest.pull_replay(ref, lg, season)
        path = backtest.save_replay(rep)
        skipped = f"; skipped the two-week matchup weeks {rep['skipped_weeks']}" if rep["skipped_weeks"] else ""
        missing = f"; {rep['universe_missing']} rostered players the universe pull does not reach" if rep["universe_missing"] else ""
        rprint(f"[green]{ref.name}: {len(rep['weeks'])} weeks, {sum(len(w['matchups']) for w in rep['weeks'])} matchups, "
               f"{len(rep['players'])} players in the universe -> {path}{skipped}{missing}[/]")


@app.command()
def backtest(replay: list[str] = typer.Option(None, "--replay", help="Replay file(s) from `ff replay-pull`; default: every file under data/replay/"),
             trades: bool = typer.Option(False, "--trades", help="Score the offers ESPN executed (data/projlog/offer_outcomes.json) against the replays instead"),
             scan: bool = typer.Option(False, "--scan", help="The scanner replay: every package the trade scan would have proposed each week, for every team, graded against the weeks after"),
             claims: bool = typer.Option(False, "--claims", help="The claim replay: every free agent the waiver ranking would have listed each week, for every team, graded against the weeks after, next to the adds the managers made"),
             prior: bool = typer.Option(False, "--prior", help="The prior replay: every body's rest-of-season price each week, rostered and wire apart, against his points a game after it, under the preseason-total prior and its alternatives"),
             fit: bool = typer.Option(False, "--fit", help="The blend question (D10 step 5): the fitted weekly number against ESPN's, each player-week, MAE and the inverse-error mixing weight per position; reads nflverse (the network)"),
             sims: int = typer.Option(None, "--sims", help="Draws per week for the playoff odds behind --scan"),
             as_json: bool = typer.Option(False, "--json", help="Print the result as JSON")):
    """Replay a season through the same code: P(win) calibration and the optimizer against the lineups managers set
    (default), the trades I made against what the players then scored (--trades), every package the scan would
    have proposed against the weeks that followed (--scan), every claim the waiver ranking would have listed
    (--claims), every body's rest-of-season price against what he scored after (--prior), or the fitted weekly number
    against ESPN's (--fit). Offline, from the replay files, except --fit, which reads nflverse."""
    from . import backtest as bt
    paths = [bt.load_replay(p) for p in (replay or sorted(str(p) for p in bt.REPLAY_DIR.glob("*.json")))]
    if not paths:
        rprint(f"no replay files under {bt.REPLAY_DIR}; run `ff replay-pull --season 2025` first"); raise typer.Exit(1)
    if fit:
        seasons = sorted({r["season"] for r in paths})
        inp = {s: bt.fit_inputs(s, sorted({w["week"] for r in paths if r["season"] == s for w in r["weeks"]}),
                                {pid for r in paths if r["season"] == s for pid in r["players"]}) for s in seasons}
        last = {s: max(w["week"] for r in paths if r["season"] == s for w in r["weeks"]) for s in seasons}
        logged = {k: v for s in seasons for k, v in bt.projlog_sources(s, last[s] + 1).items()}
        res = bt.fit_hits(paths, inp, logged)
        if as_json:
            print(json.dumps(res, indent=1)); return
        _print_fit(res); return
    if prior:
        results = [bt.prior_hits(r) for r in paths]
        if as_json:
            print(json.dumps(results, indent=1)); return
        for res in results:
            _print_prior(res)
        return
    if claims:
        results = [bt.claim_hits(r) for r in paths]
        if as_json:
            print(json.dumps(results, indent=1)); return
        for res in results:
            _print_claims(res)
        return
    if scan:
        results = [bt.scan_hits(r, sims=sims or bt.SCAN_SIMS) for r in paths]
        if as_json:
            print(json.dumps(results, indent=1)); return
        for res in results:
            _print_scan(res)
        return
    if trades:
        from .rulings import load_outcomes
        rows = bt.trade_hits(load_outcomes(), {r["league"]: r for r in paths})
        if as_json:
            print(json.dumps(rows, indent=1)); return
        if not rows:
            rprint("no accepted offers in the outcome log"); return
        t = Table("league", "gave", "got", "closed", "from wk", "weeks", "missing", "realized /wk", "predicted /wk", "hit")
        for r in rows:
            fmt = lambda x: "—" if x is None else f"{x:+.1f}"
            t.add_row(r["league"], ", ".join(r["give"]), ", ".join(r["get"]), r["closed"] or "—", str(r["from_week"] or "—"),
                      str(r["weeks"]), str(r["missing"]), fmt(r["realized_ppw"]), fmt(r["predicted_ppw"]),
                      "—" if r["hit"] is None else ("yes" if r["hit"] else "no"))
        rprint(t); return
    results = [bt.lineup_calibration(r) for r in paths]
    if as_json:
        print(json.dumps(results, indent=1)); return
    for res in results:
        rprint(f"\n[bold]{res['league']} {res['season']}[/] weeks {res['weeks'][0] if res['weeks'] else '—'}-{res['weeks'][-1] if res['weeks'] else '—'}"
               + (f"  [yellow]{res['score_mismatch']} lineup(s) whose starters' actuals do not sum to ESPN's score[/]" if res["score_mismatch"] else ""))
        c = res["calibration"]
        if not c:
            rprint("  no matchups"); continue
        rprint(f"  P(win) of the set lineups: n {c['n']}, Brier {c['brier']} (coin flip 0.25), log loss {c['log_loss']}, ECE {c['ece']}")
        t = Table("P(win) bin", "n", "predicted", "won")
        for b in c["bins"]:
            t.add_row(f"{b['lo']:.1f}-{b['hi']:.1f}", str(b["n"]), "—" if b["p_mean"] is None else f"{b['p_mean']:.2f}",
                      "—" if b["won"] is None else f"{b['won']:.2f}")
        rprint(t)
        o = res["optimizer"]
        t = Table("lineup", "points /wk", "win rate")
        for k, label in (("set", "as the manager set it"), ("ev", "highest points"), ("win", "P(win)")):
            t.add_row(label, f"{o['pts'][k]:.1f}", f"{o['win_rate'][k]:.3f}")
        rprint(t)
        d = o["differs"]
        rprint(f"  {o['team_weeks']} team-weeks; the highest-points lineup had {o['ev_over_set']:+.1f}/wk on the one set. "
               f"P(win) lineup differed from it {d['n']} times" + (f" (under {d['min_n']}: not a verdict)" if d["n"] < d["min_n"] else "")
               + (f": won {d['win_rate']['win']} vs {d['win_rate']['ev']}, promised {d['gain_promised']:+.3f}, realized {d['gain_realized']:+.3f}"
                  if d["n"] else ""))


def _print_scan(res: dict) -> None:
    """The scanner replay's tables: one row per sample (every package, the card's top three per team-week, each with
    and without the packages touching a player ESPN had at zero that week), then the reliability rows by promise."""
    fmt = lambda x: "—" if x is None else f"{x:+.2f}"
    rate = lambda x: "—" if x is None else f"{x:.2f}"
    if not res["weeks"]:
        rprint(f"\n[bold]{res['league']} {res['season']}[/]: no regular-season week with a later one to grade"); return
    rprint(f"\n[bold]{res['league']} {res['season']}[/] packages proposed in weeks {res['weeks'][0]}-{res['weeks'][-1]}, graded through week "
           f"{res['through']}: {res['team_weeks']} team-weeks, {res['candidates']} packages, the sim at {res['sims']} draws")
    rprint(f"  [dim]{res['chart']}[/]")
    t = Table("sample", "n", "hit", "promised /wk", "realized lineup /wk", "realized raw /wk")
    for sample, label in (("all", "every package"), ("top3", "the card's top 3")):
        for split, word in (("every", ""), ("clean", ", nobody at zero"), ("touches_zero", ", touching a zero")):
            x = res[sample][split]
            if split != "every" and not x["n"]:
                continue
            t.add_row(label + word, str(x["n"]), rate(x["hit"]), fmt(x["pred_mean"]), fmt(x["realized_mean"]), fmt(x["realized_raw_mean"]))
    rprint(t)
    t = Table("promised /wk", "sample", "n", "hit", "promised", "realized lineup /wk")
    for sample, label in (("all", "every package"), ("top3", "the card's top 3")):
        for b in res[sample]["every"]["bins"]:
            hi = "+" if b["hi"] is None else f"-{b['hi']:.0f}"
            t.add_row(f"{b['lo']:.0f}{hi}", label, str(b["n"]), rate(b["hit"]), fmt(b["pred_mean"]), fmt(b["realized_mean"]))
    rprint(t)


def _print_claims(res: dict) -> None:
    """The claim replay's tables: one row per sample (every row the ranking listed, the card's first claim per
    team-week, the claim-worthy rows, each with and without a zero touched, and each split again by whether the
    claimed body or the displaced starter went dark after the row, and by the claimed body's preseason total: none, or
    zeroed on the pull day because he is on IR or Out, each dark share apart; then the managers' actual adds) on the rest-of-season promise, with the distinct players behind each n;
    the same samples' START NOW rows on their one-week promise; then the reliability rows by promised upgrade."""
    fmt = lambda x: "—" if x is None else f"{x:+.2f}"
    rate = lambda x: "—" if x is None else f"{x:.2f}"
    if not res["weeks"]:
        rprint(f"\n[bold]{res['league']} {res['season']}[/]: no regular-season week with a later one to grade"); return
    rprint(f"\n[bold]{res['league']} {res['season']}[/] claims ranked in weeks {res['weeks'][0]}-{res['weeks'][-1]}, graded through week "
           f"{res['through']}: {res['team_weeks']} team-weeks, {res['rows']} rows, {res['adds']['n']} adds the managers made"
           + (f" ({res['adds']['unpriced']} more not in the universe)" if res["adds"]["unpriced"] else ""))
    rprint(f"  [dim]{res['trending']}[/]")
    if not res.get("zeroed_known"):
        rprint("[yellow]pulled before the pull-day flag: the no-total rows still hold the bodies whose total ESPN zeroed (on IR or Out "
               "on the pull day); `ff replay-pull` again reads them apart[/]")
    samples = (("all", "every row"), ("top1", "the card's first claim"), ("claim_worthy", "claim-worthy"))
    rows = []
    for sample, label in samples:
        for split, word in (("every", ""), ("clean", ", nobody at zero"), ("touches_zero", ", touching a zero")):
            if split == "every" or res[sample]["touches_zero"]["n"]:
                rows.append((label + word, res[sample][split]))
        for split, word in (("nobody_dark", ", both on the field after"), ("went_dark", ", a body dark after"),
                            ("dark_no_prior", ", dark, no preseason total"), ("dark_zeroed", ", dark, total zeroed on the pull day")):
            if res[sample]["went_dark"]["n"] and (split != "dark_zeroed" or res[sample][split]["n"]):
                rows.append((label + word, res[sample][split]))
        for split, word in (("no_prior", ", no preseason total"), ("zeroed", ", total zeroed on the pull day")):
            if res[sample][split]["n"]:
                rows.append((label + word, res[sample][split]))
    rows.append(("the managers' adds", res["adds"]))
    t = Table("sample", "n", "bodies", "hit", "promised /wk over the starter", "realized /wk")
    for label, x in rows:
        t.add_row(label, str(x["n"]), str(x["bodies"]), rate(x["hit"]), fmt(x["pred_mean"]), fmt(x["realized_mean"]))
    rprint(t)
    t = Table("START NOW rows", "n", "hit", "promised this week", "realized")
    for label, x in rows:
        w = x["week"]
        t.add_row(label, str(w["n"]), rate(w["hit"]), fmt(w["pred_mean"]), fmt(w["realized_mean"]))
    rprint(t)
    t = Table("promised /wk", "sample", "n", "hit", "promised", "realized /wk")
    for sample, label in samples + (("adds", "the managers' adds"),):
        bins = res[sample]["bins"] if sample == "adds" else res[sample]["every"]["bins"]
        for b in bins:
            lo = "" if b["lo"] is None else f"{b['lo']:.0f}"
            hi = "+" if b["hi"] is None else (f"-{b['hi']:.0f}" if b["lo"] is not None else f"under {b['hi']:.0f}")
            t.add_row(lo + hi, label, str(b["n"]), rate(b["hit"]), fmt(b["pred_mean"]), fmt(b["realized_mean"]))
    rprint(t)


def _print_prior(res: dict) -> None:
    """The prior replay's table: one row per sample (the rostered bodies, the wire, the wire bodies near a starter, each
    with and without a preseason total, the bodies whose total ESPN zeroed on the pull day apart, and again on the rows
    where he scored after), a column per prior with its bias (the price over his points a game after) and mean
    absolute error."""
    fmt = lambda v: "—" if v["bias"] is None else f"{v['bias']:+.2f} / {v['mae']:.2f}"
    if not res["weeks"]:
        rprint(f"\n[bold]{res['league']} {res['season']}[/]: no regular-season week with a later one to grade"); return
    rprint(f"\n[bold]{res['league']} {res['season']}[/] every body priced in weeks {res['weeks'][0]}-{res['weeks'][-1]}, graded through week "
           f"{res['through']}: {res['rows']} rows; each cell is bias / mean absolute error, points a game. stays fades the total "
           f"over {res['fades']['stays']} games, faster over {res['fades']['faster']}; larger takes the larger of the total and this week's number")
    if not res.get("zeroed_known"):
        rprint("[yellow]pulled before the pull-day flag: the no-total rows still hold the bodies whose total ESPN zeroed (on IR or Out "
               "on the pull day); `ff replay-pull` again reads them apart[/]")
    t = Table("sample", "n", "bodies", *res["variants"])
    for kind, label in (("rostered", "rostered"), ("wire", "wire"), ("near", "wire near a starter")):
        for prior, pw in (("total", "a total"), ("no_total", "no total"), ("zeroed", "total zeroed on the pull day")):
            for split, sw in (("every", ""), ("on_field", ", on the field after")):
                x = res[kind][prior][split]
                if x["n"]:
                    t.add_row(f"{label}, {pw}{sw}", str(x["n"]), str(x["bodies"]), *(fmt(x[v]) for v in res["variants"]))
    rprint(t)


def _print_fit(res: dict) -> None:
    """The blend question's tables: per sample, a row per position with each source's mean absolute error / bias
    (forecast minus actual, points), the inverse-error weight on each mixed source and the mix scored
    leave-one-week-out; a position under the minimum sample says so."""
    cell = lambda v: "—" if v["mae"] is None else f"{v['mae']:.2f} / {v['bias']:+.2f}"
    rprint(f"\n[bold]the fitted weekly number against ESPN's[/] {', '.join(str(s) for s in res['seasons'])} "
           f"{', '.join(res['leagues'])}, weeks {res['weeks'][0] if res['weeks'] else '—'}-{res['weeks'][-1] if res['weeks'] else '—'}; "
           f"each cell is mean absolute error / bias, points a week; rows with ESPN at {res['min_proj']:.0f}+")
    samples = (("replay", "every player-week"), ("both", f"the fitted number at {res['min_proj']:.0f}+ too"),
               ("rostered", "rostered that week"), ("projlog", "the projlog's rows (Sleeper and the live blend)"))
    for key, label in samples:
        if key not in res:
            continue
        rows = res[key]
        srcs = [k for k, v in rows[0].items() if isinstance(v, dict) and "mae" in v and k != "mix"]
        mixed = list((next((r["weights"] for r in rows if r["weights"]), None) or {}).keys())
        name = {"espn_vegas": "espn+line", "espn_matchup": "espn+line+def"}
        t = Table("pos", "n", *(name.get(s, s) for s in srcs), *(f"w {m}" for m in mixed), "mix, held out", title=label)
        for r in rows:
            w = r["weights"] or {}
            t.add_row(r["pos"], str(r["n"]) + ("" if r["counts"] else f" (under {r['min_n']})"), *(cell(r[s]) for s in srcs),
                      *(f"{w[m]:.2f}" if m in w else "—" for m in mixed), cell(r["mix"]))
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
