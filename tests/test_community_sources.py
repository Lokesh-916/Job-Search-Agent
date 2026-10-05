from pathlib import Path

import httpx

from job_agent.community.models import Company, load_companies
from job_agent.community.sources import greenhouse, lever
from job_agent.community.sources.registry import FETCHERS, fetch_company

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
    co = Company("Gamma", "mnc", "taleo", "gamma")
    assert "no fetcher" in fetch_company(co, client({})).error
    broken = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    res = fetch_company(Company("Delta", "startup", "lever", "delta"), broken)
    assert res.postings == [] and "HTTP 404" in res.error


def test_curated_list_loads():
    companies = load_companies(Path("config/companies.yaml"))
    assert len(companies) >= 60
    assert {c.ats for c in companies} <= set(FETCHERS)
    assert all(c.site for c in companies if c.ats == "workday")
    assert any(c.name == "Swiggy" and c.tier == "unicorn" for c in companies)


def test_workday_posted_dates():
    from datetime import date

    from job_agent.community.sources.workday import posted_date

    today = date(2026, 10, 5)
    assert posted_date("Posted Today", today) == "2026-10-05"
    assert posted_date("Posted Yesterday", today) == "2026-10-04"
    assert posted_date("Posted 30+ Days Ago", today) == "2026-09-05"
    assert posted_date("", today) is None


def test_ashby_and_smartrecruiters_normalise():
    from job_agent.community.sources import ashby, smartrecruiters

    ash = {
        "jobs": [
            {
                "id": "a1",
                "title": "AI Engineer",
                "jobUrl": "https://x/a1",
                "location": "Bengaluru",
                "secondaryLocations": [{"location": "Remote"}],
                "employmentType": "FullTime",
                "publishedAt": "2026-10-02T00:00:00Z",
                "compensation": {"compensationTierSummary": "₹20L – ₹30L"},
            }
        ]
    }
    [a] = ashby.fetch(Company("Sarvam AI", "startup", "ashby", "sarvam"), client(ash))
    assert a.location == "Bengaluru; Remote" and a.extra["pay"] == "₹20L – ₹30L"
    sr = {
        "totalFound": 1,
        "content": [
            {
                "id": "9",
                "name": "SDE 1",
                "releasedDate": "2026-10-01",
                "location": {"city": "Bengaluru", "remote": False},
                "typeOfEmployment": {"label": "Full-time"},
            }
        ],
    }
    [b] = smartrecruiters.fetch(
        Company("Swiggy", "unicorn", "smartrecruiters", "swiggy"), client(sr)
    )
    assert b.location == "Bengaluru, India" and b.url.endswith("/swiggy/9")


def test_source_errors_never_carry_urls():
    import httpx

    from job_agent.community.sources.registry import short_error

    req = httpx.Request("GET", "https://api.adzuna.com/v1/search?app_key=SECRET")
    exc = httpx.HTTPStatusError("boom", request=req, response=httpx.Response(503, request=req))
    assert short_error(exc) == "HTTP 503 from api.adzuna.com"
    assert "SECRET" not in short_error(httpx.ConnectError("x", request=req))


def test_eightfold_pages_and_describes():
    def handler(request: httpx.Request) -> httpx.Response:
        if "position_details" in request.url.path:
            return httpx.Response(200, json={"data": {"jobDescription": "<p>0-1 years</p>"}})
        start = int(request.url.params["start"])
        positions = [{"id": start + i, "name": f"Software Engineer {start + i}",
                      "locations": ["India, Telangana, Hyderabad"], "postedTs": "1790965800",
                      "positionUrl": f"/careers/job/{start + i}"} for i in range(10)]  # fmt: skip
        return httpx.Response(200, json={"data": {"positions": positions[: 15 - start],
                                                  "count": 15}})  # fmt: skip

    from job_agent.community.sources import eightfold

    c = httpx.Client(transport=httpx.MockTransport(handler))
    co = Company("Microsoft", "big_tech", "eightfold", "microsoft.com", site="careers.ms.test")
    posts = eightfold.fetch(co, c)
    assert len(posts) == 15 and posts[0].url == "https://careers.ms.test/careers/job/0"
    assert posts[0].location == "India, Telangana, Hyderabad" and posts[0].posted_at
    assert eightfold.describe(posts[0], c) == "0-1 years"
