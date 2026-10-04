"""Talking to the GPU box: forward commands over SSH, manage cron schedules, report status.

Commands typed on a laptop are re-run on the lab box (where the database, GPU and Ollama
live) and their output streams back. On the lab box itself (`lab.host: local`) everything
runs directly.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from job_agent.settings import LabConfig

MARK = "# job-agent:schedule"
UV = "$HOME/.local/bin/uv"


WINDOWS_OPENSSH = Path(r"C:\Windows\System32\OpenSSH")


def ssh_tool(configured: str, tool: str = "ssh") -> str:
    """Prefer Windows' own OpenSSH: Git-for-Windows' ssh doesn't see the Windows key agent."""
    native = WINDOWS_OPENSSH / f"{tool}.exe"
    if os.name == "nt" and configured == "ssh" and native.exists():
        return str(native)
    return configured if tool == "ssh" else configured.replace("ssh", tool)


def forward(lab: LabConfig, argv: list[str], llm: bool = False) -> int:
    """Run `job-agent <argv>` on the lab box, streaming its output. Returns the exit code."""
    cmd = f"{UV} run job-agent {shlex.join(argv)}"
    if llm:
        cmd = f"scripts/with_ollama.sh {cmd}"
    remote = f"cd {lab.repo} && PYTHONIOENCODING=utf-8 {cmd}"
    tty = ["-t"] if sys.stdin.isatty() and sys.stdout.isatty() else []
    return subprocess.call([ssh_tool(lab.ssh), *tty, lab.host, remote])


def start_detached(repo: Path, args: list[str]) -> None:
    """Start a logged pipeline run in the background (survives the SSH session ending)."""
    subprocess.Popen(
        ["nohup", str(repo / "scripts" / "lab_run.sh"), *args],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# --- cron -------------------------------------------------------------------------------


@dataclass
class Schedule:
    hour: int
    once_on: date | None  # None = daily
    args: list[str]

    def describe(self) -> str:
        when = f"once on {self.once_on}" if self.once_on else "daily"
        extra = f" ({' '.join(self.args)})" if self.args else ""
        return f"{when} at {self.hour:02d}:00{extra}"


def wait_deadline(hour: int, window_hours: int) -> str:
    """HH:MM until which a run starting at `hour` waits for a free GPU."""
    return f"{(hour + window_hours) % 24:02d}:00"


def next_occurrence(hour: int, now: datetime) -> date:
    today_slot = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return (today_slot if today_slot > now else today_slot + timedelta(days=1)).date()


def cron_line(sched: Schedule, repo: Path) -> str:
    run = f"{repo.as_posix()}/scripts/lab_run.sh {shlex.join(sched.args)}".rstrip()
    if sched.once_on:
        day = sched.once_on
        guard = f'[ "$(date +\\%F)" = "{day.isoformat()}" ] && '  # never fires another year
        return f"0 {sched.hour} {day.day} {day.month} * {guard}{run} {MARK} once"
    return f"0 {sched.hour} * * * {run} {MARK} daily"


def parse_cron(text: str) -> list[Schedule]:
    out = []
    for line in text.splitlines():
        if MARK not in line:
            continue
        minute, hour, dom, month, *_ = line.split()
        args_part = line.split("lab_run.sh", 1)[1].split(MARK, 1)[0].strip()
        once = None
        if line.rstrip().endswith("once"):
            m = re.search(r'"(\d{4}-\d{2}-\d{2})"', line)
            once = date.fromisoformat(m.group(1)) if m else None
        out.append(Schedule(int(hour), once, shlex.split(args_part)))
    return out


def read_crontab() -> str:
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return res.stdout if res.returncode == 0 else ""


def write_crontab(text: str) -> None:
    subprocess.run(["crontab", "-"], input=text, text=True, check=True)


def add_schedule(sched: Schedule, repo: Path, replace_daily: bool = True) -> None:
    lines = read_crontab().splitlines()
    if replace_daily and sched.once_on is None:
        lines = [ln for ln in lines if not (MARK in ln and ln.rstrip().endswith("daily"))]
    lines.append(cron_line(sched, repo))
    write_crontab("\n".join(lines) + "\n")


def clear_schedules() -> int:
    lines = read_crontab().splitlines()
    keep = [ln for ln in lines if MARK not in ln]
    write_crontab("\n".join(keep) + ("\n" if keep else ""))
    return len(lines) - len(keep)


def run_in_progress(repo: Path) -> int | None:
    lock = repo / "logs" / ".running"
    try:
        pid = int(lock.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def latest_log(repo: Path) -> Path | None:
    logs = sorted((repo / "logs").glob("run-*.log"), key=lambda p: p.stat().st_mtime)
    return logs[-1] if logs else None
