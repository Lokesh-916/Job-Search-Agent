"""Keyless research tools: web search (SearXNG or DuckDuckGo), page reader, HN search.

Every tool returns plain text and never raises: an agent on a small local model copes
much better with "no results" than with a stack trace.
"""

from __future__ import annotations

import httpx
from langchain_core.tools import tool

from job_agent.text import html_to_text

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153 Safari/537.36"  # noqa: E501
PAGE_CHARS = 4000
HN_API = "https://hn.algolia.com/api/v1/search"


def search_web(query: str, max_results: int = 5, searxng_url: str | None = None) -> list[dict]:
    """[{title, url, snippet}] from SearXNG when configured and reachable, else DuckDuckGo."""
    if searxng_url:
        try:
            resp = httpx.get(
                f"{searxng_url}/search", params={"q": query, "format": "json"}, timeout=20
            )
            resp.raise_for_status()
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                }
                for r in resp.json().get("results", [])[:max_results]
            ]
        except (httpx.HTTPError, ValueError):
            pass  # fall through to DuckDuckGo
    try:
        from ddgs import DDGS

        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in DDGS().text(query, max_results=max_results)
        ]
    except Exception:  # ddgs raises on "no results" and on rate limits alike
        return []


def format_results(results: list[dict]) -> str:
    if not results:
        return "No results."
    return "\n".join(f"- {r['title']} ({r['url']})\n  {r['snippet']}" for r in results)


def read_page(url: str, max_chars: int = PAGE_CHARS) -> str:
    try:
        resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return f"Could not fetch {url}: {type(exc).__name__}"
    if "html" not in resp.headers.get("content-type", "html"):
        return f"{url} is not an HTML page."
    return html_to_text(resp.text, max_chars) or "Page had no readable text."


def search_hn(query: str, max_results: int = 5) -> str:
    try:
        resp = httpx.get(HN_API, params={"query": query, "hitsPerPage": max_results}, timeout=20)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
    except (httpx.HTTPError, ValueError):
        return "HN search failed."
    lines = []
    for h in hits:
        title = h.get("title") or h.get("story_title") or "(comment)"
        text = html_to_text(h.get("comment_text") or h.get("story_text") or "", 300)
        lines.append(
            f"- {title} ({h.get('created_at', '')[:10]}, {h.get('points') or 0} pts) {text}"
        )
    return "\n".join(lines) or "No HN results."


def make_tools(searxng_url: str | None = None) -> list:
    """LangChain tools for the research agent."""

    @tool
    def web_search(query: str) -> str:
        """Search the web. Good queries: '<company> glassdoor reviews',
        '<company> interview experience', '<company> salary software engineer',
        '<company> funding round'."""
        return format_results(search_web(query, searxng_url=searxng_url))

    @tool
    def read_webpage(url: str) -> str:
        """Read the text of one web page (first few thousand characters)."""
        return read_page(url)

    @tool
    def hacker_news_search(query: str) -> str:
        """Search Hacker News stories and comments (launches, hiring threads, opinions)."""
        return search_hn(query)

    return [web_search, read_webpage, hacker_news_search]
