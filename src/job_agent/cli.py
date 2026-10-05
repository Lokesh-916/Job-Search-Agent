"""Command line entry point: `uv run job-agent --help`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from job_agent.preflight import run_checks
from job_agent.settings import get_settings

app = typer.Typer(help="Scout fresher-friendly startup jobs into a daily Excel workbook.")
console = Console()


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@app.callback()
def main() -> None:
    """Job-Search-Agent CLI."""
    # Config, data and workbooks are project-relative; work from any terminal folder.
    if (PROJECT_ROOT / "pyproject.toml").exists():
        os.chdir(PROJECT_ROOT)


@app.command()
def doctor() -> None:
    """Check GPU headroom, Ollama, and the WaaS login session. Never loads a model."""
    settings = get_settings()
    table = Table("check", "status", "detail")
    failed = False
    for c in run_checks(settings):
        status = "[green]ok[/]" if c.ok else ("[red]FAIL[/]" if c.fatal else "[yellow]warn[/]")
        failed |= c.fatal and not c.ok
        table.add_row(c.name, status, c.detail)
    console.print(f"model: [bold]{settings.llm.model}[/]")
    console.print(table)
    raise typer.Exit(1 if failed else 0)


@app.command()
def login() -> None:
    """Open a browser to sign in to Work at a Startup; close the window when done."""
    from job_agent.sources.waas.session import interactive_login

    settings = get_settings()
    console.print("Sign in with your YC account, open the jobs page, then [bold]close it[/].")
    if interactive_login(settings.browser, settings.paths.session):
        console.print(f"[green]Session saved[/] -> {settings.paths.session}")
    else:
        console.print("[red]No logged-in WaaS page seen; session not saved.[/]")
        raise typer.Exit(1)


@app.command()
def fetch() -> None:
    """Pull matching WaaS jobs into the local database (no LLM involved)."""
    from job_agent.sources.waas.fetch import fetch_waas
    from job_agent.store import Store

    settings = get_settings()
    with Store(settings.paths.data_dir / "jobs.db") as store, console.status("Fetching WaaS..."):
        r = fetch_waas(settings, store)
    console.print(
        f"found [bold]{r.found}[/] | new {len(r.new)} | details {r.fetched} | "
        f"new/changed postings {len(r.changed)} | closed {r.closed} | failed {len(r.failed)}"
    )
    for job_id, err in list(r.failed.items())[:5]:
        console.print(f"  [red]{job_id}[/] {err}")


@app.command()
def report() -> None:
    """Write today's workbook from what's already in the database (no LLM calls)."""
    from datetime import date

    from job_agent.export import workbook_path, write_workbook
    from job_agent.fx import load_inr_rates
    from job_agent.report import build_report
    from job_agent.store import Store

    settings = get_settings()
    out_dir, today = settings.paths.output_dir, date.today().isoformat()
    with Store(settings.paths.data_dir / "jobs.db") as store:
        rates = load_inr_rates(settings.paths.data_dir / "fx.json")
        rep = build_report(store, settings, rates, run_date=today)
    info = [("Run date", today), ("Model", settings.llm.model), ("Jobs", len(rep.jobs)),
            ("USD → INR", round(rates.get("USD", 0), 2))]  # fmt: skip
    path = workbook_path(out_dir, today)
    try:
        write_workbook(rep, path, settings.scoring.top_pick_threshold, info)
    except PermissionError:
        console.print(f"[red]{path} is open in Excel.[/] Close it and run again.")
        raise typer.Exit(1) from None
    console.print(f"[green]Wrote[/] {path.resolve()}")


@app.command()
def run(
    limit: int = typer.Option(None, help="Cap jobs per LLM stage (for test runs)."),
    skip_fetch: bool = typer.Option(False, help="Use jobs already in the database."),
    notify: bool = typer.Option(True, help="Send the Telegram digest + workbook."),
    wait_gpu_until: str = typer.Option(
        None, help="HH:MM. Wait (polling every 5 min) for free VRAM until this time."
    ),
) -> None:
    """Full pipeline: fetch -> triage -> extract -> assess -> workbook -> Telegram."""
    import asyncio
    from datetime import datetime, timedelta

    from job_agent.graph import run_pipeline
    from job_agent.preflight import wait_for_vram

    settings = get_settings()
    if wait_gpu_until:
        hh, mm = map(int, wait_gpu_until.split(":"))
        now = datetime.now()
        deadline = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if deadline <= now:  # e.g. started 22:00, wait until 04:00 tomorrow
            deadline += timedelta(days=1)
        console.print(
            f"Waiting for {settings.vram.min_free_mib} MiB free VRAM until {deadline:%H:%M}"
        )
        if not wait_for_vram(settings, deadline):
            console.print(
                "[yellow]GPU never freed up; running anyway so the user gets a notice.[/]"
            )
    state = asyncio.run(
        run_pipeline(settings, {"limit": limit, "skip_fetch": skip_fetch, "notify": notify})
    )
    for key, value in state.get("log", []):
        console.print(f"  {key}: {value}")
    if state.get("abort"):
        console.print(f"[red]Aborted:[/] {state['abort']}")
        raise typer.Exit(1)
    console.print(f"[green]Done[/] -> {state.get('workbook')}")


def _on_lab(llm: bool = False) -> None:
    """On a laptop, re-run this exact command on the lab box and exit with its status."""
    lab = get_settings().lab
    if not lab.is_local:
        from job_agent.lab import forward

        raise typer.Exit(forward(lab, sys.argv[1:], llm=llm))


def _hour(value: int) -> int:
    if not 0 <= value <= 23:
        raise typer.BadParameter("hour must be between 0 and 23")
    return value


@app.command()
def now(
    limit: int = typer.Option(None, help="Cap jobs per LLM stage (quick test)."),
    wait_hours: int = typer.Option(0, help="If the GPU is busy, keep checking for this long."),
) -> None:
    """Start a run right away on the lab box. Results arrive on Telegram."""
    _on_lab()
    from datetime import datetime

    from job_agent.lab import start_detached, wait_deadline

    args = ["--limit", str(limit)] if limit else []
    if wait_hours:
        args += ["--wait-gpu-until", wait_deadline(datetime.now().hour, wait_hours)]
    start_detached(Path.cwd(), args)
    console.print("[green]Started.[/] Watch it with [bold]job-agent status[/] / "
                  "[bold]job-agent logs[/]; the digest + workbook come to Telegram.")  # fmt: skip


@app.command()
def schedule(
    hour: int = typer.Argument(..., callback=_hour, help="Hour of day, 0-23 (lab box time)."),
    once: bool = typer.Option(False, "--once", help="Only the next occurrence, not daily."),
    limit: int = typer.Option(None, help="Cap jobs per LLM stage."),
    wait_hours: int = typer.Option(6, help="How long a run waits for a busy GPU."),
) -> None:
    """Run every day at HOUR:00 (or just once with --once). Replaces the daily schedule."""
    _on_lab()
    from datetime import datetime

    from job_agent.lab import Schedule, add_schedule, next_occurrence, wait_deadline

    args = ["--wait-gpu-until", wait_deadline(hour, wait_hours)]
    if limit:
        args += ["--limit", str(limit)]
    sched = Schedule(hour, next_occurrence(hour, datetime.now()) if once else None, args)
    add_schedule(sched, Path.cwd())
    console.print(f"[green]Scheduled[/] {sched.describe()}")


@app.command()
def unschedule() -> None:
    """Remove every scheduled run."""
    _on_lab()
    from job_agent.lab import clear_schedules

    console.print(f"Removed {clear_schedules()} scheduled run(s).")


@app.command()
def status() -> None:
    """GPU headroom, running/scheduled runs and the last run's numbers."""
    _on_lab()
    import json

    from job_agent.lab import latest_log, parse_cron, read_crontab, run_in_progress
    from job_agent.preflight import free_vram_mib
    from job_agent.store import Store

    settings, repo = get_settings(), Path.cwd()
    free = free_vram_mib()
    need = settings.vram.min_free_mib
    gpu = "no GPU here" if free is None else f"{free} MiB free (needs {need})"
    ready = "" if free is None else (" [green]ready[/]" if free >= need else " [yellow]busy[/]")
    console.print(f"🎮 GPU: {gpu}{ready}")
    pid = run_in_progress(repo)
    console.print(f"🏃 Run in progress: {'yes (pid ' + str(pid) + ')' if pid else 'no'}")
    schedules = parse_cron(read_crontab())
    console.print("⏰ Schedules: " + ("; ".join(s.describe() for s in schedules) or "none"))
    with Store(settings.paths.data_dir / "jobs.db") as store:
        runs = store.runs()
    if runs:
        last, s = runs[-1], json.loads(runs[-1]["summary_json"] or "{}")
        out = s.get("outcome", {})
        console.print(
            f"📊 Last run: {s.get('run_date') or last['started_at'][:10]} · {last['model']} · "
            f"{s.get('duration_min', '?')} min · {out.get('scored', 0)} scored · "
            f"{out.get('top_picks', 0)} top picks"
            + (f" · [red]aborted: {s['aborted']}[/]" if s.get("aborted") else "")
        )
    if log := latest_log(repo):
        console.print(f"📜 {log.name}: " + log.read_text(errors="ignore").strip().splitlines()[-1])


@app.command()
def logs(lines: int = typer.Option(40, "-n", help="How many lines.")) -> None:
    """Show the end of the latest run log."""
    _on_lab()
    from job_agent.lab import latest_log

    log = latest_log(Path.cwd())
    if not log:
        console.print("No runs logged yet.")
        return
    console.print(f"[bold]{log.name}[/]")
    console.print("\n".join(log.read_text(errors="ignore").splitlines()[-lines:]), markup=False)


CHARTS_DIR = Path("docs/metrics")
WHERE = {
    "remote_foreign": "🌍 remote",
    "remote_india": "🏠 remote (IN)",
    "india_onsite": "🏢 India office",
    "abroad_sponsored": "✈️ abroad",
    "needs_review": "🔎 review",
}


@app.command()
def stats(runs: int = typer.Option(10, "-n", help="How many recent runs to list.")) -> None:
    """Per-run metrics table + charts (light/dark PNGs, copied into docs/metrics/)."""
    lab = get_settings().lab
    if not lab.is_local:
        from job_agent.lab import forward, pull_files

        code = forward(lab, sys.argv[1:])
        if code == 0 and pull_files(lab, "data/charts/*.png", CHARTS_DIR) == 0:
            console.print(f"[green]Charts copied[/] -> {CHARTS_DIR}")
        raise typer.Exit(code)
    import json

    from job_agent.charts import render_all
    from job_agent.fx import load_inr_rates
    from job_agent.report import build_report
    from job_agent.store import Store

    settings = get_settings()
    with Store(settings.paths.data_dir / "jobs.db") as store:
        rows = store.runs()[-runs:]
        call_counts = {r["run_id"]: len(store.llm_calls(r["run_id"])) for r in rows}
        rates = load_inr_rates(settings.paths.data_dir / "fx.json")
        jobs = build_report(store, settings, rates).jobs
        made = render_all(store, settings.paths.data_dir / "charts", jobs,
                          settings.preferences.salary_floor_lpa,
                          settings.scoring.top_pick_threshold)  # fmt: skip
    table = Table("date", "model", "min", "LLM calls", "tok/s", "scored", "top", "failed")
    for r in rows:
        s = json.loads(r["summary_json"] or "{}")
        llm = s.get("llm", {})
        calls = call_counts[r["run_id"]]
        speeds = [v["tokens_per_s"] for v in llm.values() if v.get("tokens_per_s")]
        out = s.get("outcome", {})
        table.add_row(
            s.get("run_date") or r["started_at"][:10], r["model"].split(":", 1)[-1],
            str(s.get("duration_min", "")), str(calls or ""),
            f"{sum(speeds) / len(speeds):.0f}" if speeds else "",
            str(out.get("scored", "")), str(out.get("top_picks", "")),
            str(sum(v["errors"] for v in llm.values())),
        )  # fmt: skip
    console.print(table)
    console.print(f"{len(made)} charts -> {settings.paths.data_dir / 'charts'}")


@app.command()
def top(
    n: int = typer.Option(15, "-n", help="How many jobs."),
    tab: str = typer.Option(
        None, help="remote_foreign | remote_india | india_onsite | abroad_sponsored"
    ),
    compact: bool = typer.Option(False, help="Two short lines per job (for Telegram)."),
) -> None:
    """Best-scoring jobs from the database, no LLM needed."""
    _on_lab()
    from job_agent.fx import load_inr_rates
    from job_agent.report import build_report, research_columns
    from job_agent.store import Store

    settings = get_settings()
    with Store(settings.paths.data_dir / "jobs.db") as store:
        rates = load_inr_rates(settings.paths.data_dir / "fx.json")
        rep = build_report(store, settings, rates, research_columns(store))
    jobs = [j for j in rep.jobs if j["Score"] is not None and (not tab or j["_bucket"] == tab)]
    if compact:  # phone-friendly: two short lines per job
        for i, j in enumerate(jobs[:n], start=1):
            pay = j["Realistic (₹ LPA)"] or j["Listed (₹ LPA)"] or "pay n/a"
            console.print(f"{i}. {j['Tier']} {j['Score']:.0f}  {j['Title'][:38]} @ {j['Company']}",
                          markup=False)  # fmt: skip
            console.print(f"   {WHERE.get(j['_bucket'], j['_bucket'])} · {pay} · "
                          f"DSA {j['DSA risk']} · id {j['Job ID']}", markup=False)  # fmt: skip
        if not jobs:
            console.print("No scored jobs yet.")
        if rep.pending:
            console.print(f"\n{rep.pending} fetched jobs not processed yet.")
        return
    table = Table("score", "title", "company", "where", "pay (₹ LPA)", "DSA", "verdict", "id")
    for j in jobs[:n]:
        table.add_row(
            f"{j['Tier']} {j['Score']:.0f}", j["Title"][:40], j["Company"][:20],
            WHERE.get(j["_bucket"], j["_bucket"]), j["Realistic (₹ LPA)"] or j["Listed (₹ LPA)"],
            j["DSA risk"], j["Verdict"], j["Job ID"],
        )  # fmt: skip
    console.print(table)
    if rep.pending:
        console.print(f"[dim]{rep.pending} fetched jobs not processed yet.[/]")


@app.command()
def show(job_id: str = typer.Argument(..., help="Job ID (last column of `top`).")) -> None:
    """Everything known about one job: facts, judgment, score breakdown, company research."""
    _on_lab()
    from job_agent.fx import load_inr_rates
    from job_agent.report import build_report, research_columns
    from job_agent.store import Store

    settings = get_settings()
    with Store(settings.paths.data_dir / "jobs.db") as store:
        rates = load_inr_rates(settings.paths.data_dir / "fx.json")
        rep = build_report(store, settings, rates, research_columns(store))
    job = next((j for j in rep.jobs if j["Job ID"] == job_id), None)
    if job is None:
        console.print(f"[red]No processed job {job_id}.[/]")
        raise typer.Exit(1)
    table = Table(show_header=False, box=None)
    for key, value in job.items():
        if value not in (None, "") and not key.startswith("_"):
            table.add_row(f"[bold]{key}[/]", str(value))
    console.print(table)


def _need_gpu() -> None:
    from job_agent.preflight import check_ollama, check_vram

    settings = get_settings()
    for check in (check_vram(settings), check_ollama(settings)):
        if check.fatal and not check.ok:
            console.print(f"[yellow]Not now:[/] {check.name} — {check.detail}. Try again later.")
            raise typer.Exit(2)


def _as_text(model) -> str:
    """Readable plain text for a helper result (terminal and Telegram)."""
    lines: list[str] = []
    for name, value in model:
        title = name.replace("_", " ").capitalize()
        if isinstance(value, list):
            lines.append(f"\n{title}:")
            for item in value:
                if hasattr(item, "model_dump"):
                    first, *rest = item.model_dump().items()
                    lines.append(f"• {first[1]}")
                    for k, v in rest:
                        v = "; ".join(v) if isinstance(v, list) else v
                        lines.append(f"    {k.replace('_', ' ')}: {v}")
                else:
                    lines.append(f"• {item}")
        else:
            lines.append(f"\n{title}:\n{value}")
    return "\n".join(lines).strip()


def _helper(kind: str, job_id: str, telegram: bool, extra: str = "") -> None:
    _on_lab(llm=True)
    _need_gpu()
    import asyncio
    import html

    from job_agent.assistant import UnknownJobError, job_helper
    from job_agent.profile import load_profile
    from job_agent.store import Store

    settings = get_settings()
    with Store(settings.paths.data_dir / "jobs.db") as store, console.status(f"Writing {kind}..."):
        try:
            result = asyncio.run(
                job_helper(kind, store, load_profile(settings.paths.profile), job_id, extra=extra)
            )
        except UnknownJobError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from None
        row = store.get(job_id)
        title = f"{kind.capitalize()} · {row['title']} @ {row['company_name']}"
    text = _as_text(result)
    console.rule(title)
    console.print(text, markup=False)
    if telegram:
        from job_agent.notify import Telegram

        Telegram(settings.secrets).send_message(
            f"<b>{html.escape(title)}</b>\n\n{html.escape(text)}"[:4000]
        )


TELEGRAM_OPT = typer.Option(False, "--telegram", help="Also send the result to Telegram.")


@app.command()
def pitch(
    job_id: str,
    note: str = typer.Option("", help="Extra instruction, e.g. 'mention my Jev work'."),
    telegram: bool = TELEGRAM_OPT,
) -> None:
    """[LLM] Founder message, cover note and subject line for one job."""
    _helper("pitch", job_id, telegram, note)


@app.command()
def prep(job_id: str, telegram: bool = TELEGRAM_OPT) -> None:
    """[LLM] Interview prep: likely rounds, topics, questions with answer pointers."""
    _helper("prep", job_id, telegram)


@app.command()
def tailor(job_id: str, telegram: bool = TELEGRAM_OPT) -> None:
    """[LLM] Which projects to lead the resume with, rewritten bullets, keywords, gaps."""
    _helper("tailor", job_id, telegram)


@app.command()
def ask(question: str = typer.Argument(..., help='e.g. "remote AI jobs above 20 LPA?"')) -> None:
    """[LLM] Ask anything about your jobs; an agent searches the database to answer."""
    _on_lab(llm=True)
    _need_gpu()
    import asyncio

    from job_agent.assistant import ask as ask_agent
    from job_agent.fx import load_inr_rates
    from job_agent.report import build_report, research_columns
    from job_agent.store import Store

    settings = get_settings()
    with Store(settings.paths.data_dir / "jobs.db") as store, console.status("Thinking..."):
        rates = load_inr_rates(settings.paths.data_dir / "fx.json")
        records = build_report(store, settings, rates, research_columns(store)).jobs
        answer = asyncio.run(ask_agent(question, records, store))
    console.print(answer, markup=False)


@app.command()
def bot() -> None:
    """Run the Telegram control bot (on the lab box; deploy/job-agent-bot.service keeps it up)."""
    settings = get_settings()
    if not settings.lab.is_local:
        console.print("Run the bot on the lab box (lab.host: local), not here.")
        raise typer.Exit(1)
    from job_agent.bot import build_app

    console.print("Bot polling Telegram. Ctrl+C to stop.")
    build_app(settings, Path.cwd()).run_polling(drop_pending_updates=True)


community_app = typer.Typer(help="The batch placement feed (India jobs, internships, events).")
app.add_typer(community_app, name="community")


@community_app.command("refresh")
def community_refresh() -> None:
    """Fetch every source, curate, and build today's sheet (no messages sent)."""
    _on_lab()
    from job_agent.community.service import db_path, refresh_and_build
    from job_agent.community.store import CommunityStore

    settings = get_settings()
    with CommunityStore(db_path(settings)) as store:
        stats, path = refresh_and_build(settings, store)
    console.print(f"fetched {sum(stats.fetched.values())} postings "
                  f"({', '.join(f'{k} {v}' for k, v in stats.fetched.most_common())})")  # fmt: skip
    console.print(f"kept {stats.kept['job']} jobs, {stats.kept['internship']} internships, "
                  f"{stats.events} events · new: {dict(stats.new)}")  # fmt: skip
    console.print(f"job texts fetched for Workday/SmartRecruiters listings: {stats.described}")
    console.print(f"dropped: {dict(stats.dropped.most_common(6))}")
    for name, err in stats.errors.items():
        console.print(f"  [yellow]{name}[/]: {err}")
    console.print(f"[green]Sheet[/] {path}")


@community_app.command("enrich")
def community_enrich(
    limit: int = typer.Option(None, help="Read at most this many postings."),
    daily: bool = typer.Option(
        False,
        "--daily",
        help="Morning mode: obey community.enrich, "
        "use enrich_limit, and skip quietly when the GPU is busy.",
    ),
) -> None:
    """LLM notes on each posting (fresher-friendly?, batches, CTC, skills). Needs the GPU."""
    _on_lab(llm=True)
    import asyncio

    from job_agent.community.enrich import enrich
    from job_agent.community.service import current, db_path, needs_checking, rebuild
    from job_agent.community.store import CommunityStore

    settings = get_settings()
    if daily:
        if not settings.community.enrich:
            return
        limit = limit or settings.community.enrich_limit
        try:
            _need_gpu()
        except typer.Exit:
            return  # the feed goes out without notes today
    else:
        _need_gpu()
    with CommunityStore(db_path(settings)) as store:
        jobs, interns, _ = current(store)
        rows = jobs + interns + needs_checking(store)
        stats = asyncio.run(enrich(settings, store, rows, limit=limit))
        console.print(f"notes: {dict(stats)}")
        console.print(f"[green]Sheet[/] {rebuild(settings, store)}")


@community_app.command("send")
def community_send(
    me_only: bool = typer.Option(False, "--me", help="Send only to the coordinator (preview)."),
) -> None:
    """Send today's feed to every approved member (or just to you with --me)."""
    _on_lab()
    from job_agent.community.service import db_path, deliver
    from job_agent.community.store import CommunityStore

    settings = get_settings()
    with CommunityStore(db_path(settings)) as store:
        targets = [int(settings.secrets.telegram_chat_id)] if me_only else None
        sent, failed = deliver(settings, store, targets)
    console.print(f"sent to {sent}; failed {len(failed)}")


@community_app.command("daily")
def community_daily() -> None:
    """Refresh, then send to everyone. This is what the morning cron runs."""
    community_refresh()
    community_send(me_only=False)


@community_app.command("users")
def community_users() -> None:
    """Who has joined, and their status."""
    _on_lab()
    from job_agent.community.service import db_path
    from job_agent.community.store import CommunityStore

    with CommunityStore(db_path(get_settings())) as store:
        rows = store.users()
    table = Table("status", "name", "roll", "username", "joined", "last active", "feeds")
    for r in rows:
        active = (r["last_active"] or "")[:10]
        table.add_row(r["status"], r["name"] or "", r["roll_no"] or "", r["username"] or "",
                      r["joined_at"][:10], active, str(r["digests"]))  # fmt: skip
    console.print(table)


@community_app.command("bot")
def community_bot() -> None:
    """Run the community bot (on the lab box; deploy/job-agent-community-bot.service)."""
    settings = get_settings()
    if not settings.lab.is_local:
        console.print("Run the bot on the lab box (lab.host: local), not here.")
        raise typer.Exit(1)
    from job_agent.community.bot import build_app

    console.print("Community bot polling Telegram. Ctrl+C to stop.")
    build_app(settings).run_polling(drop_pending_updates=True)


@app.command("notify-test")
def notify_test() -> None:
    """Send a test message to the configured Telegram chat."""
    from job_agent.notify import Telegram

    Telegram(get_settings().secrets).send_message(
        "👋 <b>Job-Search-Agent</b> is wired up. Daily picks will land here."
    )
    console.print("[green]Sent.[/] Check Telegram.")


if __name__ == "__main__":
    app()
