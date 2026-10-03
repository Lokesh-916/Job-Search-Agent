import asyncio
import html
import json

import httpx

from job_agent.sources.waas.detail import fetch_details, parse_inertia_props, slim_detail

PROPS = {
    "job": {"id": 1, "title": "AI Engineer", "salaryRange": "$100K - $150K"},
    "companyFull": {
        "name": "Acme",
        "lat": 1.0,
        "logo_url": "x",
        "jobs": [{"id": 1, "title": "AI Engineer", "descriptionHtml": "long"}],
        "founders": [{"full_name": "Ada", "linkedin": "li", "avatar_thumb": "img"}],
    },
    "otherJobs": [],
}


def page(props: dict) -> str:
    payload = html.escape(json.dumps({"component": "JobDetailPage", "props": props}))
    return f'<div id="app" data-page="{payload}"></div>'


def test_parse_inertia_props_roundtrip():
    assert parse_inertia_props(page(PROPS))["job"]["title"] == "AI Engineer"


def test_slim_detail_drops_noise():
    slim = slim_detail(PROPS)
    assert "lat" not in slim["company"] and "logo_url" not in slim["company"]
    assert slim["company"]["open_jobs"] == [{"id": 1, "title": "AI Engineer"}]
    assert slim["company"]["founders"] == [{"full_name": "Ada", "linkedin": "li"}]


def test_fetch_details_handles_closed_and_errors(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        job_id = request.url.path.rsplit("/", 1)[-1]
        if job_id == "404":
            return httpx.Response(404)
        if job_id == "500":
            return httpx.Response(500)
        return httpx.Response(200, text=page(PROPS))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = asyncio.run(fetch_details(["1", "404", "500"], tmp_path, delay_s=0, client=client))
    assert out["1"]["job"]["title"] == "AI Engineer"
    assert out["404"] == {"closed": True}
    assert isinstance(out["500"], httpx.HTTPStatusError)
