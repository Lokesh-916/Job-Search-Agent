"""The community workbook (its own schema) and the one-message daily digest."""

from __future__ import annotations

import html
from collections import Counter
from datetime import date
from pathlib import Path

import xlsxwriter

from job_agent.community.feed import ranked
from job_agent.community.models import TIER_LABEL

TIER = {**TIER_LABEL, "other": "📌 Other"}
JOB_COLUMNS = [  # (header, row key / callable, width)
    ("New", lambda r, since: "🆕" if r["first_seen"] >= since else "", 5),
    ("Company", "company", 20), ("Tier", lambda r, d: TIER.get(r["tier"] or "other", ""), 12),
    ("Role", "title", 42), ("Category", "category", 18), ("Level", "level", 14),
    ("Location", "location", 26), ("Pay (if stated)", "pay", 16), ("Posted", "posted_at", 11),
    ("Apply", "url", 9), ("Eligibility", "eligibility", 22), ("Skills", "skills", 30),
    ("What you'd do", "summary", 50), ("Source", "source", 13),
]  # fmt: skip
INTERN_COLUMNS = [
    ("New", lambda r, since: "🆕" if r["first_seen"] >= since else "", 5),
    ("Company", "company", 22), ("Tier", lambda r, d: TIER.get(r["tier"] or "other", ""), 12),
    ("Internship", "title", 40), ("Category", "category", 18), ("Location", "location", 24),
    ("Stipend / month", "pay", 20), ("Apply by", "deadline", 11), ("Posted", "posted_at", 11),
    ("Apply", "url", 9), ("Eligibility", "eligibility", 22), ("Skills", "skills", 30),
    ("What you'd do", "summary", 50), ("Source", "source", 11),
]  # fmt: skip
EVENT_COLUMNS = [
    ("Name", "name", 40), ("Organizer", "organizer", 26), ("Mode", "mode", 10),
    ("City / venue", "city", 28), ("Starts", "starts", 11), ("Ends", "ends", 11),
    ("Register by", "deadline", 11), ("Prizes", "prize", 20), ("Link", "url", 9),
    ("Source", "source", 10),
]  # fmt: skip


def _value(row, spec, today: str):
    if callable(spec):
        return spec(row, today)
    # sqlite3.Row has no `in` for keys; notes columns exist only on enriched dict rows
    return row[spec] if spec in row.keys() else ""  # noqa: SIM118


def write_workbook(path: Path, jobs: list, interns: list, events: list, today: str,
                   check: list = (), new_since: str | None = None) -> Path:  # fmt: skip
    """`new_since`: postings first seen at/after this timestamp are marked new."""
    new_since = new_since or today
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(str(path), {"strings_to_urls": False})
    head = wb.add_format({"bold": True, "font_color": "white", "bg_color": "#2b37a8",
                          "text_wrap": True, "valign": "vcenter"})  # fmt: skip
    link = wb.add_format({"font_color": "#0563C1", "underline": 1})
    title = wb.add_format({"bold": True, "font_size": 16})
    bold = wb.add_format({"bold": True})

    hackathons = [e for e in events if e["kind"] == "Hackathon"]
    meetups = [e for e in events if e["kind"] != "Hackathon"]
    dash = wb.add_worksheet("📊 Today")
    dash.set_column(0, 0, 34)
    dash.set_column(1, 1, 14)
    dash.write(0, 0, f"Placement feed · {today}", title)
    rows = [
        ("💼 Jobs (India, entry level)", len(jobs)),
        ("   new today", sum(r["first_seen"] >= new_since for r in jobs)),
        ("🎓 Paid internships", len(interns)),
        ("   new today", sum(r["first_seen"] >= new_since for r in interns)),
        ("🏆 Open hackathons", len(hackathons)),
        ("🎤 Upcoming tech events", len(meetups)),
        ("🔍 Other openings (check experience)", len(check)),
        ("", ""),
        ("Jobs by category", ""),
        *Counter(r["category"] for r in jobs).most_common(),
        ("", ""),
        ("Level 'Not specified' = the posting doesn't say; check before applying.", ""),
        ("'Check experience' tab: big-company roles whose listing shows no requirements.", ""),
    ]
    for i, (k, v) in enumerate(rows, start=2):
        dash.write(i, 0, k, bold if k and not k.startswith("   ") else None)
        dash.write(i, 1, v)

    def sheet(name: str, columns, items) -> None:
        ws = wb.add_worksheet(name)
        data = [[_value(r, spec, new_since) for _, spec, _ in columns] for r in items]
        ws.add_table(0, 0, max(len(data), 1), len(columns) - 1, {
            "data": data or [[None] * len(columns)], "style": "Table Style Light 9",
            "columns": [{"header": h, "header_format": head} for h, _, _ in columns],
        })  # fmt: skip
        for c, (h, _, width) in enumerate(columns):
            ws.set_column(c, c, width)
            if h in ("Apply", "Link"):
                for r, row in enumerate(data, start=1):
                    if row[c]:
                        ws.write_url(r, c, row[c], link, string="open")
        ws.freeze_panes(1, 2)

    sheet("💼 Jobs", JOB_COLUMNS, jobs)
    sheet("🎓 Internships", INTERN_COLUMNS, interns)
    sheet("🏆 Hackathons", EVENT_COLUMNS, hackathons)
    sheet("🎤 Tech events", EVENT_COLUMNS, meetups)
    sheet("🔍 Check experience", JOB_COLUMNS, check)
    wb.close()
    return path


def job_line(r, pay_label: str = "") -> str:
    esc = html.escape
    pay = f" · {esc(r['pay'])}" if r["pay"] and pay_label else ""
    link = f'<a href="{esc(r["url"])}">{esc(r["title"][:70])}</a>'
    return f"• <b>{esc(r['company'])}</b> · {link} · {esc(r['location'][:40])}{pay}"


def event_line(e) -> str:
    when = e["starts"] or ""
    by = f" · register by {e['deadline']}" if e["deadline"] else ""
    esc = html.escape
    link = f'<a href="{esc(e["url"])}">{esc(e["name"][:60])}</a>'
    return f"• {link} · {esc(e['mode'])}, {esc((e['city'] or '')[:30])} · {when}{by}"


def distinct(rows: list) -> list:
    """One line per company + title (multi-location postings repeat otherwise)."""
    seen, out = set(), []
    for r in rows:
        key = (r["company"], r["title"].lower())
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


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


def digest_text(jobs: list, interns: list, events: list, today: str, top: int = 8,
                new_since: str | None = None) -> str:  # fmt: skip
    new_since = new_since or today
    jobs, interns = distinct(ranked(jobs)), distinct(ranked(interns))
    new_jobs = per_company([r for r in jobs if r["first_seen"] >= new_since] or jobs, 2)
    new_interns = per_company([r for r in interns if r["first_seen"] >= new_since] or interns, 2)
    soon = upcoming(events, today)[:5]
    d = date.fromisoformat(today)
    lines = [
        f"🗞️ <b>Placement Feed · {d.day} {d:%b}</b>",
        f"{len(jobs)} jobs · {len(interns)} paid internships · {len(events)} events, all in India",
        "",
        "💼 <b>Jobs</b>",
        *[job_line(r) for r in new_jobs[:top]],
        "",
        "🎓 <b>Internships</b>",
        *[job_line(r, "pay") for r in new_interns[:5]],
        "",
        "🏆 <b>Hackathons & events</b>",
        *[event_line(e) for e in soon],
        "",
        "📎 Full list with filters in the attached sheet. /suggest to send feedback.",
    ]
    return "\n".join(lines)[:4000]
