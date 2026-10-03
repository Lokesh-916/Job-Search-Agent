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


if __name__ == "__main__":
    app()
