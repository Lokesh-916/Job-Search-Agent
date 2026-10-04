"""Command line entry point: `uv run job-agent --help`."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from job_agent.preflight import run_checks
from job_agent.settings import get_settings

app = typer.Typer(help="Scout fresher-friendly startup jobs into a daily Excel workbook.")
console = Console()


@app.callback()
def main() -> None:
    """Job-Search-Agent CLI."""


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
