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


if __name__ == "__main__":
    app()
