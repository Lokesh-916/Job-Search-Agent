import json
from datetime import date

import httpx
import pytest

from job_agent.fx import load_inr_rates, to_lpa

RATES = {"USD": 96.0, "INR": 1.0, "EUR": 108.0}


def test_to_lpa_conversions():
    assert to_lpa(120_000, "USD", "year", RATES) == 115.2
    assert to_lpa(1_200_000, "INR", None, RATES) == 12.0
    assert to_lpa(50_000, "inr", "month", RATES) == 6.0
    assert to_lpa(None, "USD", "year", RATES) is None
    assert to_lpa(100, "XYZ", "year", RATES) is None


def test_fetches_and_caches(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"rates": {"USD": 0.0104}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = tmp_path / "fx.json"
    rates = load_inr_rates(cache, client)
    assert rates["USD"] == pytest.approx(96.15, abs=0.01) and rates["INR"] == 1.0
    load_inr_rates(cache, client)
    assert len(calls) == 1  # second call served from today's cache


def test_offline_falls_back_to_stale_cache(tmp_path):
    cache = tmp_path / "fx.json"
    cache.write_text(json.dumps({"fetched_on": "2000-01-01", "inr_per_unit": RATES}))
    assert date.today().isoformat() != "2000-01-01"
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert load_inr_rates(cache, client) == RATES
