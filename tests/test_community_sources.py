from pathlib import Path

import httpx

from job_agent.community.models import Company, load_companies
from job_agent.community.sources import greenhouse, lever
from job_agent.community.sources.registry import fetch_company

GH = {"jobs": [{"id": 7, "title": " SWE, New Grad ", "absolute_url": "https://x/7",
                "location": {"name": "Bengaluru, India"}, "updated_at": "2026-10-01T10:00:00Z",
                "departments": [{"name": "Engineering"}],
                "content": "&lt;p&gt;Build &amp;amp; ship&lt;/p&gt;"}]}  # fmt: skip
LEVER = [{"id": "abc", "text": "Backend Engineer", "hostedUrl": "https://jobs.lever.co/x/abc",
          "categories": {"location": "Hyderabad", "team": "Platform", "commitment": "Full-time"},
          "createdAt": 1759300000000, "descriptionPlain": "Go and Postgres",
          "lists": [{"text": "Requirements", "content": "0-1 years"}],
          "workplaceType": "hybrid"}]  # fmt: skip


def client(payload) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))


def test_greenhouse_normalises():
    [p] = greenhouse.fetch(Company("Acme", "unicorn", "greenhouse", "acme"), client(GH))
    assert (p.title, p.location, p.department, p.posted_at) == (
        "SWE, New Grad",
        "Bengaluru, India",
        "Engineering",
        "2026-10-01",
    )
    assert p.description == "Build & ship" and p.key == "greenhouse:Acme:7"


def test_lever_normalises():
    [p] = lever.fetch(Company("Beta", "startup", "lever", "beta"), client(LEVER))
    assert (p.title, p.location, p.employment_type) == (
        "Backend Engineer",
        "Hyderabad",
        "Full-time",
    )
    assert "0-1 years" in p.description and p.extra["workplace"] == "hybrid"
    assert p.posted_at.startswith("2025-")


def test_unknown_platform_and_http_errors_are_reported_not_raised():
    co = Company("Gamma", "mnc", "workday", "gamma")
    assert "no fetcher" in fetch_company(co, client({})).error
    broken = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    res = fetch_company(Company("Delta", "startup", "lever", "delta"), broken)
    assert res.postings == [] and "HTTPStatusError" in res.error


def test_curated_list_loads():
    companies = load_companies(Path("config/companies.yaml"))
    assert len(companies) >= 40
    assert {c.ats for c in companies} <= {"greenhouse", "lever"}
    assert any(c.name == "Stripe" and c.tier == "unicorn" and c.india for c in companies)
