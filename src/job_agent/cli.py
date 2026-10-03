"""Command line entry point: `uv run job-agent --help`."""

from __future__ import annotations

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

    from job_agent.export import read_user_status, workbook_path, write_workbook
    from job_agent.fx import load_inr_rates
    from job_agent.report import build_report
    from job_agent.store import Store

    settings = get_settings()
    out_dir, today = settings.paths.output_dir, date.today().isoformat()
    with Store(settings.paths.data_dir / "jobs.db") as store:
        store.save_user_status(read_user_status(out_dir))
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
