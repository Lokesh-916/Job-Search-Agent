"""The community workbook (its own schema) and the one-message daily digest."""

from __future__ import annotations

import contextlib
import html
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import xlsxwriter

from job_agent.community.feed import ranked
from job_agent.community.models import TIER_LABEL

TIER = {**TIER_LABEL, "other": "📌 Other"}
SOURCE_LABEL = {
    "unstop": "Unstop",
    "adzuna": "Adzuna",
    "devfolio": "Devfolio",
    "devpost": "Devpost",
    "gdg": "Google Developer Groups",
    "hack2skill": "Hack2skill",
}  # everything else is the company's own careers page
NEW = ("New", lambda r, since: "🆕" if r["first_seen"] >= since else "", 6)
TIER_COL = ("Tier", lambda r, d: TIER.get(r["tier"] or "other", ""), 13)
SOURCE = ("Source", lambda r, d: SOURCE_LABEL.get(r["source"], "Careers page"), 14)
NOTES = [("Eligibility", "eligibility", 24), ("Skills", "skills", 30),
         ("What you'd do", "summary", 50)]  # LLM notes; hidden when not filled  # fmt: skip
JOB_COLUMNS = [  # (header, row key / callable, width)
    NEW, ("Company", "company", 20), TIER_COL, ("Role", "title", 44),
    ("Category", "category", 18), ("Level", "level", 14), ("Location", "location", 30),
    ("Pay (if stated)", "pay", 16), ("Posted", "posted_at", 12), ("Apply", "url", 9),
    *NOTES, SOURCE,
]  # fmt: skip
INTERN_COLUMNS = [
    NEW, ("Company", "company", 20), TIER_COL, ("Internship", "title", 44),
    ("Category", "category", 18), ("Location", "location", 30), ("Stipend / month", "pay", 20),
    ("Apply by", "deadline", 12), ("Posted", "posted_at", 12), ("Apply", "url", 9),
    *NOTES, SOURCE,
]  # fmt: skip
EVENT_COLUMNS = [
    ("Name", "name", 44), ("Organizer", "organizer", 28), ("Mode", "mode", 11),
    ("City / venue", "city", 30), ("Starts", "starts", 12), ("Ends", "ends", 12),
    ("Register by", "deadline", 12), ("Prizes", "prize", 20), ("Link", "url", 9), SOURCE,
]  # fmt: skip
DATES = {"Posted", "Starts", "Ends", "Register by", "Apply by"}
LINKS = {"Apply": "Apply ↗", "Link": "Open ↗"}
INK, MUTED, ACCENT = "#14161f", "#5d6275", "#2b37a8"


def _value(row, spec, today: str):
    if callable(spec):
        return spec(row, today)
    # sqlite3.Row has no `in` for keys; notes columns exist only on enriched dict rows
    return row[spec] if spec in row.keys() else ""  # noqa: SIM118


def merged(rows: list) -> list:
    """One row per company + role; a role posted for several cities lists them all."""
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["company"], r["title"].strip().lower())
        if key not in out:
            out[key] = dict(r)
            continue
        places = out[key]["location"].split("; ")
        for place in (r["location"] or "").split("; "):
            if place and place not in places:
                places.append(place)
        out[key]["location"] = "; ".join(p for p in places if p)
    return list(out.values())


def write_workbook(path: Path, jobs: list, interns: list, events: list, today: str,
                   check: list = (), new_since: str | None = None,
                   picks: list = ()) -> Path:  # fmt: skip
    """`new_since`: postings first seen at/after this timestamp are marked new."""
    new_since = new_since or today
    jobs, interns, check = merged(jobs), merged(interns), merged(check)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(str(path), {"strings_to_urls": False})
    base = {"font_name": "Calibri", "font_size": 11, "valign": "vcenter"}
    fmt = {
        "head": wb.add_format({**base, "bold": True, "font_color": "white", "bg_color": ACCENT,
                               "text_wrap": True}),
        "link": wb.add_format({**base, "font_color": ACCENT, "underline": 1}),
        "date": wb.add_format({**base, "num_format": "d mmm yyyy", "align": "left"}),
        "title": wb.add_format({**base, "bold": True, "font_size": 20, "font_color": INK}),
        "sub": wb.add_format({**base, "font_color": MUTED, "italic": True}),
        "section": wb.add_format({**base, "bold": True, "font_size": 12, "font_color": ACCENT,
                                  "bottom": 1, "bottom_color": "#d6d9f0"}),
        "label": wb.add_format({**base}),
        "num": wb.add_format({**base, "bold": True, "align": "right", "num_format": "#,##0"}),
        "small": wb.add_format({**base, "font_color": MUTED}),
    }  # fmt: skip

    hackathons = [e for e in events if e["kind"] == "Hackathon"]
    meetups = [e for e in events if e["kind"] != "Hackathon"]
    d = date.fromisoformat(today)
    dash = wb.add_worksheet("📊 Today")
    dash.hide_gridlines(2)
    dash.set_column(0, 0, 2)
    dash.set_column(1, 1, 46)
    dash.set_column(2, 2, 12)
    dash.set_column(3, 3, 60)
    dash.set_row(1, 30)
    dash.write(1, 1, f"Placement Feed · {d.day} {d:%B %Y}", fmt["title"])
    dash.write(2, 1, "Tech jobs, paid internships, hackathons and events in India. "
                     "Refreshed every morning at 8.", fmt["sub"])  # fmt: skip
    row = 4

    def section(name: str) -> None:
        nonlocal row
        dash.write(row, 1, name, fmt["section"])
        dash.write_blank(row, 2, None, fmt["section"])
        row += 1

    section("Today at a glance")
    glance = [
        ("💼 Jobs, entry level", len(jobs)),
        ("🏢 at Big Tech and MNCs", sum(r["tier"] in BIG_TIERS for r in jobs)),
        ("🎓 Paid internships", len(interns)),
        ("🆕 New since yesterday", sum(r["first_seen"] >= new_since for r in jobs + interns)),
        ("🏆 Open hackathons", len(hackathons)),
        ("🎤 Upcoming tech events", len(meetups)),
    ]
    if check:
        glance.append(("🔍 To check (experience not stated)", len(check)))
    for label, n in glance:
        dash.write(row, 1, label, fmt["label"])
        dash.write_number(row, 2, n, fmt["num"])
        row += 1
    if picks:
        row += 1
        section("🏛️ Big names today")
        for r in picks:
            dash.write_url(row, 1, r["url"], fmt["link"], string=f"{r['company']} · {r['title']}")
            dash.write(row, 3, short_place(r["location"]), fmt["small"])
            row += 1
    row += 1
    section("Jobs by category")
    for name, n in Counter(r["category"] for r in jobs).most_common():
        dash.write(row, 1, name, fmt["label"])
        dash.write_number(row, 2, n, fmt["num"])
        row += 1
    row += 1
    section("Reading the sheet")
    notes = (
        "🆕 marks roles that appeared since yesterday's feed.",
        "Level 'Not specified': the posting doesn't say. Read it before applying.",
        "Click a column header's arrow to filter by company, city or category.",
    )
    for note in notes:
        dash.write(row, 1, note, fmt["small"])
        row += 1

    def sheet(name: str, columns, items) -> None:
        if not items:
            return
        data = [[_value(r, spec, new_since) for _, spec, _ in columns] for r in items]
        keep = [c for c, col in enumerate(columns)  # drop empty LLM-note columns
                if col not in NOTES or any(row[c] for row in data)]  # fmt: skip
        columns = [columns[c] for c in keep]
        data = [[row[c] for c in keep] for row in data]
        ws = wb.add_worksheet(name)
        ws.add_table(0, 0, len(data), len(columns) - 1, {
            "data": data, "style": "Table Style Light 9",
            "columns": [{"header": h, "header_format": fmt["head"]} for h, _, _ in columns],
        })  # fmt: skip
        ws.set_row(0, 22)
        for c, (h, _, width) in enumerate(columns):
            ws.set_column(c, c, width)
            for r, values in enumerate(data, start=1):
                value = values[c]
                if h in LINKS and value:
                    ws.write_url(r, c, value, fmt["link"], string=LINKS[h])
                elif h in DATES and value:
                    with contextlib.suppress(ValueError):  # else keep the text as written
                        ws.write_datetime(r, c, datetime.fromisoformat(value[:10]), fmt["date"])
        ws.freeze_panes(1, 2)

    sheet("💼 Jobs", JOB_COLUMNS, jobs)
    sheet("🎓 Internships", INTERN_COLUMNS, interns)
    sheet("🏆 Hackathons", EVENT_COLUMNS, hackathons)
    sheet("🎤 Tech events", EVENT_COLUMNS, meetups)
    sheet("🔍 Check experience", JOB_COLUMNS, check)
    wb.close()
    return path


def short_place(location: str) -> str:
    """'Bangalore, India; Hyderabad, Telangana, India' -> 'Bangalore +1'."""
    places = [p.strip() for p in re.split(r";|\|", location or "") if p.strip()]
    if not places:
        return ""
    parts = [p.strip() for p in places[0].split(",") if p.strip()]
    # "India, Telangana, Hyderabad" (country first) vs "Hyderabad, Telangana, India"
    city = parts[-1] if parts[0].lower() == "india" and len(parts) > 1 else parts[0]
    more = f" +{len(places) - 1}" if len(places) > 1 else ""
    return f"{city[:28]}{more}"


def day(iso: str | None) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d:%b}"


def job_line(r, pay_label: str = "") -> str:
    esc = html.escape
    stated = r["pay"] and not r["pay"].startswith("Paid (")  # skip "amount not listed"
    pay = f" · {esc(r['pay'])}" if stated and pay_label else ""
    link = f'<a href="{esc(r["url"])}">{esc(r["title"][:60])}</a>'
    return f"• <b>{esc(r['company'])}</b> · {link} · {esc(short_place(r['location']))}{pay}"


def event_line(e) -> str:
    esc = html.escape
    link = f'<a href="{esc(e["url"])}">{esc(e["name"][:55])}</a>'
    where = (
        e["mode"]
        if e["mode"] == "Online"
        else ", ".join(
            x for x in (e["mode"], (e["city"] or "").split(",")[0].split(" (")[0][:24]) if x
        )
    )
    when = f"starts {day(e['starts'])}" if e["starts"] else ""
    by = f"register by {day(e['deadline'])}" if e["deadline"] else ""
    return " · ".join(x for x in (f"• {link}", esc(where), when, by) if x)


EVENT_SOURCES = ("hack2skill", "devfolio", "devpost", "gdg", "unstop")  # most reputable first


def featured_events(events: list, today: str, n: int = 5, per_source: int = 2) -> list:
    """Open events for the message: big platforms first, a few per site, soonest first."""
    soon = upcoming(events, today)
    soon.sort(key=lambda e: EVENT_SOURCES.index(e["source"]) if e["source"] in EVENT_SOURCES
              else len(EVENT_SOURCES))  # fmt: skip
    counts: dict[str, int] = {}
    out = []
    for e in soon:
        counts[e["source"]] = counts.get(e["source"], 0) + 1
        if counts[e["source"]] <= per_source:
            out.append(e)
    return sorted(out[:n], key=lambda e: e["deadline"] or e["starts"] or "9999")


MAX_MESSAGE = 4000  # Telegram's limit is 4096; never cut the HTML mid-tag


def upcoming(events: list, today: str) -> list:
    """Events you can still sign up for: registration open, or starting today or later."""
    open_ = [e for e in events if (e["deadline"] and e["deadline"] >= today)
             or (not e["deadline"] and (e["starts"] or "") >= today)]  # fmt: skip
    return sorted(open_, key=lambda e: e["deadline"] or e["starts"] or "9999")


def per_company(rows: list, cap: int) -> list:
    counts: dict[str, int] = {}
    out = []
    for r in rows:
        counts[r["company"]] = counts.get(r["company"], 0) + 1
        if counts[r["company"]] <= cap:
            out.append(r)
    return out


BIG_TIERS = ("big_tech", "mnc")
CLEAR_LEVELS = ("Entry level", "Internship")


def big_picks(jobs: list, interns: list, new_since: str, recent: set[str] = frozenset(),
              n: int = 3) -> list:  # fmt: skip
    """Up to `n` Big Tech / MNC roles for the top of the message, one per company: new ones
    first, then ones not featured lately, Big Tech before MNC, clear fresher roles first."""
    pool = [r for r in merged(interns + jobs) if r["tier"] in BIG_TIERS]
    pool.sort(key=lambda r: r["posted_at"] or "", reverse=True)  # newest first, then:
    pool.sort(key=lambda r: (
        r["first_seen"] < new_since,
        r["key"] in recent,
        BIG_TIERS.index(r["tier"]),
        r["level"] not in CLEAR_LEVELS,
    ))  # fmt: skip
    return per_company(pool, 1)[:n]


def pick_line(r) -> str:
    kind = "Internship" if r["kind"] == "internship" else (r["level"] or "Job")
    if kind == "Not specified":
        kind = "Job"
    return f"{job_line(r, 'pay')} · <i>{html.escape(kind)}</i>"


def digest_text(jobs: list, interns: list, events: list, today: str, top: int = 6,
                new_since: str | None = None, picks: list = ()) -> str:  # fmt: skip
    new_since = new_since or today
    jobs, interns = merged(ranked(jobs)), merged(ranked(interns))
    featured = {r["key"] for r in picks}
    rest_jobs = [r for r in jobs if r["key"] not in featured]
    rest_interns = [r for r in interns if r["key"] not in featured]
    new_jobs = per_company([r for r in rest_jobs if r["first_seen"] >= new_since] or rest_jobs, 2)
    new_interns = per_company(
        [r for r in rest_interns if r["first_seen"] >= new_since] or rest_interns, 2
    )
    fresh = sum(r["first_seen"] >= new_since for r in jobs + interns)
    big = sum(r["tier"] in BIG_TIERS for r in jobs + interns)
    d = date.fromisoformat(today)
    head = [
        f"🗞️ <b>Placement Feed · {d.day} {d:%b}</b>",
        f"{len(jobs)} jobs · {len(interns)} paid internships · {len(events)} events · all in India",
        f"🏢 {big} at Big Tech / MNCs · 🆕 {fresh} new today",
    ]
    sections = {  # title -> lines; trimmed from the longest until the message fits
        "🏛️ <b>Big names today</b>": [pick_line(r) for r in picks],
        "💼 <b>Jobs</b>": [job_line(r) for r in new_jobs[:top]],
        "🎓 <b>Internships</b>": [job_line(r, "pay") for r in new_interns[:5]],
        "🏆 <b>Hackathons & events</b>": [event_line(e) for e in featured_events(events, today)],
    }
    foot = ["", "📎 The attached sheet has the full list: filter by company, city or category.",
            "💡 /suggest a company or report a bad listing."]  # fmt: skip

    def render() -> str:
        body = [x for title, items in sections.items() if items for x in ("", title, *items)]
        return "\n".join(head + body + foot)

    text = render()
    while len(text) > MAX_MESSAGE:
        longest = max(sections.values(), key=len)
        if len(longest) <= 1:
            break
        longest.pop()
        text = render()
    return text
