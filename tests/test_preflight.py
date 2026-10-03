from datetime import datetime, timedelta

import job_agent.preflight as pf
from job_agent.settings import Settings


def test_wait_for_vram_polls_until_free(monkeypatch):
    readings = iter([2000, 4000, 12000])
    monkeypatch.setattr(pf, "free_vram_mib", lambda: next(readings))
    slept = []
    ok = pf.wait_for_vram(Settings(), datetime.now() + timedelta(hours=1), 60, slept.append)
    assert ok and slept == [60, 60]


def test_wait_for_vram_gives_up_at_deadline(monkeypatch):
    monkeypatch.setattr(pf, "free_vram_mib", lambda: 1000)
    assert not pf.wait_for_vram(Settings(), datetime.now() + timedelta(seconds=30), 60, print)


def test_no_gpu_is_not_fatal(monkeypatch):
    monkeypatch.setattr(pf, "free_vram_mib", lambda: None)
    check = pf.check_vram(Settings())
    assert check.ok and not check.fatal
