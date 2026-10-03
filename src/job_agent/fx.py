"""Salary normalisation to INR lakhs per annum (LPA), with daily-cached FX rates."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

FX_URL = "https://api.frankfurter.dev/v1/latest?from=INR"
HOURS_PER_YEAR = 2080
LAKH = 100_000


def load_inr_rates(cache_path: Path, client: httpx.Client | None = None) -> dict[str, float]:
    """INR value of one unit of each currency, e.g. {"USD": 96.3}. Fetched at most once a day."""
    cached = json.loads(cache_path.read_text()) if cache_path.exists() else None
    if cached and cached.get("fetched_on") == date.today().isoformat():
        return cached["inr_per_unit"]
    try:
        resp = (client or httpx.Client(timeout=15, follow_redirects=True)).get(FX_URL)
        resp.raise_for_status()
        rates = {cur: 1 / r for cur, r in resp.json()["rates"].items() if r}
    except (httpx.HTTPError, ValueError, KeyError):
        if cached:  # offline: yesterday's rates beat no rates
            return cached["inr_per_unit"]
        raise
    rates["INR"] = 1.0
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"fetched_on": date.today().isoformat(), "inr_per_unit": rates}, indent=1)
    )
    return rates


def to_lpa(
    amount: float | None, currency: str | None, period: str | None, rates: dict[str, float]
) -> float | None:
    """Convert a salary figure to INR lakhs per annum; None if it can't be done honestly."""
    if amount is None or not currency:
        return None
    per_unit = rates.get(currency.upper())
    if per_unit is None:
        return None
    yearly = amount * {"month": 12, "hour": HOURS_PER_YEAR}.get(period or "year", 1)
    return round(yearly * per_unit / LAKH, 1)
