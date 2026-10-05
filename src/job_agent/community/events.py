"""Hackathons and tech events in India (plus online ones), from public event sites."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import httpx

from job_agent.community.classify import INDIA
from job_agent.community.sources.registry import short_error

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/153", "Accept": "application/json"}


@dataclass
class Event:
    source: str
    external_id: str
    kind: str  # Hackathon | Meetup / workshop
    name: str
    organizer: str
    mode: str  # Online | In person
    city: str
    starts: str | None  # ISO date
    ends: str | None
    deadline: str | None  # registration closes
    prize: str
    url: str

    def __post_init__(self) -> None:
        self.name = html.unescape(self.name or "")
        self.organizer = html.unescape(self.organizer or "")

    @property
    def key(self) -> str:
        return f"{self.source}:{self.external_id}"


def _date(value: str | None) -> str | None:
    return (value or "")[:10] or None


def devfolio(client: httpx.Client) -> list[Event]:
    resp = client.post("https://api.devfolio.co/api/search/hackathons",
                       json={"type": "application_open", "from": 0, "size": 60})  # fmt: skip
    resp.raise_for_status()
    out = []
    for hit in resp.json().get("hits", {}).get("hits", []):
        h = hit.get("_source", {})
        online = str(h.get("is_online")).lower() == "true"
        place = ", ".join(x for x in (h.get("city"), h.get("state")) if x) or (
            h.get("location") or ""
        )
        if not online and place and not INDIA.search(f"{place} {h.get('country') or ''}"):
            continue
        settings = h.get("hackathon_setting") or {}
        out.append(Event(
            "devfolio", str(h.get("uuid") or h.get("slug")), "Hackathon", h.get("name", ""),
            h.get("hosted_by") or "Devfolio", "Online" if online else "In person",
            place or ("Online" if online else "India"), _date(h.get("starts_at")),
            _date(h.get("ends_at")), _date(settings.get("reg_ends_at")),
            f"{len(h.get('prizes') or [])} prize tracks" if h.get("prizes") else "",
            f"https://{h.get('slug')}.devfolio.co",
        ))  # fmt: skip
    return out


def _rupees(prizes: list) -> str:
    cash = sum(p.get("cash") or 0 for p in prizes or [] if isinstance(p, dict))
    return f"₹{cash:,} in prizes" if cash else ""


def unstop(client: httpx.Client, pages: int = 3) -> list[Event]:
    out = []
    for page in range(1, pages + 1):
        resp = client.get("https://unstop.com/api/public/opportunity/search-result",
                          headers=HEADERS,
                          params={"opportunity": "hackathons", "page": page, "per_page": 50,
                                  "oppstatus": "open"})  # fmt: skip
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        for item in data.get("data") or []:
            online = item.get("region") == "online"
            addr = item.get("address_with_country_logo") or {}
            city = ", ".join(x for x in (addr.get("city"), addr.get("state")) if x)
            out.append(Event(
                "unstop", str(item["id"]), "Hackathon", item.get("title", ""),
                (item.get("organisation") or {}).get("name", ""),
                "Online" if online else "In person", city or ("Online" if online else "India"),
                _date(item.get("start_date")), _date(item.get("end_date")),
                _date((item.get("regnRequirements") or {}).get("end_regn_dt")),
                _rupees(item.get("prizes")), item.get("seo_url", ""),
            ))  # fmt: skip
        if page >= (data.get("last_page") or 1):
            break
    return out


def devpost(client: httpx.Client, pages: int = 3) -> list[Event]:
    """Global platform: keep online hackathons and ones located in India."""
    out = []
    for page in range(1, pages + 1):
        resp = client.get("https://devpost.com/api/hackathons", headers=HEADERS,
                          params={"status[]": ["upcoming", "open"], "page": page})  # fmt: skip
        resp.raise_for_status()
        for h in resp.json().get("hackathons", []):
            where = (h.get("displayed_location") or {}).get("location", "")
            online = "online" in where.lower()
            if not online and not INDIA.search(where):
                continue
            prize = re.sub(r"<[^>]+>", "", h.get("prize_amount") or "")
            out.append(Event(
                "devpost", str(h["id"]), "Hackathon", h.get("title", ""),
                h.get("organization_name") or "", "Online" if online else "In person",
                where or "Online", None, None, None,
                f"{prize} in prizes" if prize.strip("$0, ") else "", h.get("url", ""),
            ))  # fmt: skip
    return out


def gdg(client: httpx.Client, pages: int = 8) -> list[Event]:
    """Google Developer Group meetups and workshops run by Indian chapters."""
    out = []
    url = "https://gdg.community.dev/api/event_slim/"
    params: dict | None = {"status": "Live", "page_size": 100}
    for _ in range(pages):
        resp = client.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        data = resp.json()
        for e in data.get("results", []):
            chapter = e.get("chapter_title") or ""
            if not INDIA.search(chapter):
                continue
            online = str(e.get("is_virtual_event")).lower() == "true" or \
                e.get("audience_type") == "VIRTUAL"  # fmt: skip
            out.append(Event(
                "gdg", str(e["id"]), "Meetup / workshop", e.get("title", ""), chapter,
                "Online" if online else "In person", chapter.replace("GDG", "").strip(),
                _date(e.get("start_date")), _date(e.get("end_date")), None, "",
                e.get("static_url", ""),
            ))  # fmt: skip
        url = (data.get("links") or {}).get("next")
        params = None
        if not url:
            break
    return out


FETCHERS = {"devfolio": devfolio, "unstop": unstop, "devpost": devpost, "gdg": gdg}


def fetch_all(client: httpx.Client) -> tuple[list[Event], dict[str, str]]:
    events, errors = [], {}
    for name, fn in FETCHERS.items():
        try:
            events += fn(client)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            errors[name] = short_error(exc)
    return events, errors
