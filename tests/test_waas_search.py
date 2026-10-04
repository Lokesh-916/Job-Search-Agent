import httpx
import pytest

from job_agent.settings import WaasSourceConfig
from job_agent.sources.waas.search import (
    AlgoliaOpts,
    SessionExpiredError,
    build_filters,
    parse_algolia_opts,
    search_jobs,
)


def test_build_filters_default():
    assert build_filters(WaasSourceConfig()) == (
        "(job_type:fulltime) "
        "AND (min_experience:0) "
        "AND (remote:yes OR remote:only OR locations_for_search:IN OR us_visa_required:possible) "
        "AND (us_visa_required:none OR us_visa_required:possible OR locations_for_search:IN)"
    )


def test_build_filters_roles_and_no_visa_clause():
    cfg = WaasSourceConfig(
        roles=["eng"], exclude_us_auth_required=False, include_visa_sponsored=False
    )
    f = build_filters(cfg)
    assert f.startswith("(role:eng) AND ")
    assert "us_visa_required" not in f


def test_parse_algolia_opts():
    html = '<script>window.AlgoliaOpts = {"app":"APP1","key":"k3y","valid_until":1};</script>'
    assert parse_algolia_opts(html) == AlgoliaOpts(app="APP1", key="k3y")


def test_parse_algolia_opts_logged_out():
    with pytest.raises(SessionExpiredError):
        parse_algolia_opts("<html>please log in</html>")


def test_search_jobs_paginates():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = len(calls)
        calls.append(request)
        return httpx.Response(200, json={"results": [{"hits": [{"id": str(page)}], "nbPages": 2}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    hits = search_jobs(AlgoliaOpts("APP", "KEY"), "role:eng", client)
    assert [h["id"] for h in hits] == ["0", "1"]
    assert calls[0].headers["X-Algolia-API-Key"] == "KEY"
    assert "distinct=false" in calls[0].content.decode()
