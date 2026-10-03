import httpx

import job_agent.research.tools as tools


def fake_get(responses):
    def get(url, **kwargs):
        resp = responses(url, kwargs)
        resp.request = httpx.Request("GET", url)
        return resp

    return get


def test_searxng_results_are_normalised(monkeypatch):
    payload = {"results": [{"title": "Acme reviews", "url": "https://g.com/a", "content": "4.5★"}]}
    monkeypatch.setattr(
        tools.httpx, "get", fake_get(lambda u, k: httpx.Response(200, json=payload))
    )
    out = tools.search_web("acme", searxng_url="http://searx")
    assert out == [{"title": "Acme reviews", "url": "https://g.com/a", "snippet": "4.5★"}]


def test_search_never_raises(monkeypatch):
    monkeypatch.setattr(tools.httpx, "get", fake_get(lambda u, k: httpx.Response(503)))

    class Broken:
        def text(self, *a, **k):
            raise RuntimeError("No results found.")

    import ddgs

    monkeypatch.setattr(ddgs, "DDGS", Broken)
    assert tools.search_web("acme", searxng_url="http://searx") == []
    assert tools.format_results([]) == "No results."


def test_read_page_returns_text_or_reason(monkeypatch):
    html = "<html><body><h1>Acme</h1><p>We build agents.</p></body></html>"
    monkeypatch.setattr(
        tools.httpx,
        "get",
        fake_get(
            lambda u, k: httpx.Response(200, text=html, headers={"content-type": "text/html"})
        ),
    )
    assert tools.read_page("https://acme.dev") == "Acme\nWe build agents."
    monkeypatch.setattr(tools.httpx, "get", fake_get(lambda u, k: httpx.Response(404)))
    assert tools.read_page("https://acme.dev/x").startswith("Could not fetch")


def test_tools_are_named_for_the_agent():
    names = [t.name for t in tools.make_tools()]
    assert names == ["web_search", "read_webpage", "hacker_news_search"]
