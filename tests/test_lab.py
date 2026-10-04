from datetime import date, datetime
from pathlib import Path

from job_agent.lab import Schedule, cron_line, next_occurrence, parse_cron, wait_deadline

REPO = Path("/home/u/projects/Job-Search-Agent")


def test_wait_deadline_wraps_midnight():
    assert wait_deadline(3, 6) == "09:00"
    assert wait_deadline(22, 6) == "04:00"


def test_next_occurrence():
    now = datetime(2026, 10, 4, 10, 30)
    assert next_occurrence(3, now) == date(2026, 10, 5)
    assert next_occurrence(23, now) == date(2026, 10, 4)


def test_daily_cron_roundtrip():
    sched = Schedule(3, None, ["--wait-gpu-until", "09:00"])
    line = cron_line(sched, REPO)
    assert line.startswith("0 3 * * * /home/u/projects/Job-Search-Agent/scripts/lab_run.sh")
    [back] = parse_cron("MAILTO=x\n" + line + "\n")
    assert back == sched and back.describe() == "daily at 03:00 (--wait-gpu-until 09:00)"


def test_once_cron_is_guarded_by_date():
    sched = Schedule(5, date(2026, 10, 6), ["--limit", "25"])
    line = cron_line(sched, REPO)
    assert line.startswith("0 5 6 10 * ")
    assert '"$(date +\\%F)" = "2026-10-06"' in line  # % must be escaped in crontab
    assert parse_cron(line) == [sched]
