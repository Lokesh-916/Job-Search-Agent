"""Rule-based curation for the community feed (no LLM needed).

India-only, technical roles only, and a level per posting: internship, entry or experienced.
Experienced roles are dropped; unclear ones are kept and marked so students can check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from job_agent.community.models import Posting

INDIA = re.compile(
    r"\bindia\b|bengaluru|bangalore|hyderabad|secunderabad|mumbai|navi mumbai|thane|pune|"
    r"gurgaon|gurugram|new delhi|\bdelhi\b|noida|greater noida|chennai|kolkata|ahmedabad|"
    r"jaipur|kochi|cochin|coimbatore|indore|chandigarh|mohali|trivandrum|thiruvananthapuram|"
    r"visakhapatnam|vizag|vijayawada|nagpur|bhubaneswar|lucknow|mysore|mysuru|mangalore|"
    r"vadodara|surat|goa|\bIND\b|, IN\b",
    re.I,
)

CATEGORIES: list[tuple[str, re.Pattern]] = [
    ("ML / AI", re.compile(r"machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|"
                           r"\bnlp\b|computer vision|\bllm|genai|generative|applied scientist|"
                           r"research scientist|mlops", re.I)),
    ("Data", re.compile(r"data scien|data engineer|data analyst|analytics engineer|\bbi\b|"
                        r"business intelligence|big data|data platform", re.I)),
    ("DevOps / Cloud", re.compile(r"devops|site reliability|\bsre\b|cloud engineer|platform engineer|"
                                  r"infrastructure engineer|kubernetes", re.I)),
    ("Security", re.compile(r"security engineer|cyber ?security|appsec|penetration|soc analyst", re.I)),
    ("Mobile", re.compile(r"android|\bios\b|mobile (app )?developer|mobile engineer|flutter|"
                          r"react native", re.I)),
    ("Frontend", re.compile(r"front[- ]?end|ui engineer|react developer|web developer", re.I)),
    ("Full stack", re.compile(r"full[- ]?stack|mern|mean stack", re.I)),
    ("Backend", re.compile(r"back[- ]?end|java developer|golang|python developer|node(js)? developer|"
                           r"api engineer", re.I)),
    ("Embedded / Hardware", re.compile(r"embedded|firmware|vlsi|asic|fpga|hardware engineer|"
                                       r"verification engineer|design engineer|silicon|analog", re.I)),
    ("QA / Test", re.compile(r"\bqa\b|quality assurance|test engineer|sdet|automation test", re.I)),
    ("Software engineering", re.compile(r"software|\bsde\b|developer|engineer|programmer|"
                                        r"technical|solutions? (engineer|architect)|tech|python|"
                                        r"\bjava\b|javascript|typescript|golang|c\+\+|\.net\b|"
                                        r"coding|programming|web|app development", re.I)),
]  # fmt: skip
NON_TECH = re.compile(
    r"\b(sales|account (executive|manager)|business development|\bbdr\b|\bsdr\b|marketing|"
    r"recruit|talent|\bhr\b|human resources|payroll|finance|accountant|accounting|audit|tax|"
    r"legal|counsel|compliance|customer success|customer support|support associate|"
    r"operations (manager|associate|executive)|office manager|executive assistant|"
    r"content writer|copywriter|graphic designer|video editor|social media|procurement|"
    r"logistics|warehouse|driver|nurse|doctor|pharmac|teacher|tutor|counsell?or|"
    r"non[- ]?tech(nology|nical)?|trainer)\b",
    re.I,
)
SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|leader|manager|director|head|vp|vice president|architect|"
    r"chief|distinguished|fellow|expert|specialist|intermediate|mid[- ]level)\b|"
    r"\b(II|III|IV|V|[2-5])\s*$|(?-i:\b(?:II|III|IV)\b)|"  # "SDE - Test II, Alexa"
    r"(engineer|developer|development|sde|scientist|analyst|associate)[- ]*(II|III|IV|[2-5])\b",
    re.I,
)
TITLE_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|to)?\s*\d{0,2}\s*\+?\s*y(?:rs?|ears?)?\b", re.I)
NO_DESCRIPTION_SOURCES = {
    "workday",
    "smartrecruiters",
    "eightfold",
}  # listing APIs without job text
ENTRY = re.compile(
    r"new grad|graduate|fresher|campus|entry[- ]level|early career|junior|jr\.?\b|trainee|"
    r"associate (software|engineer|developer|data)|\bsde[- ]*(i|1)\b|"
    r"(engineer|scientist|developer)[- ]*(i|1)\b|"
    r"university|0\s*[-–to]+\s*[12]\s*(years|yrs)|20(26|27) (batch|grad)|batch of 20(26|27)",
    re.I,
)
# In descriptions only unambiguous phrases count ("graduate degree" is not a new-grad role).
ENTRY_DESC = re.compile(
    r"new grads?\b|fresher|entry[- ]level|early[- ]career|campus (hire|hiring|recruit)|"
    r"0\s*[-–to]+\s*[12]\s*(years|yrs)|20(26|27) (batch|graduates?|pass(ing)?[- ]?outs?)",
    re.I,
)
INTERN = re.compile(r"\bintern(ship)?s?\b|\bco-?op\b|summer analyst|apprentice", re.I)
YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|to|–)?\s*\d{0,2}\s*\+?\s*(?:years?|yrs?)\b", re.I)
EXPERIENCE = re.compile(r"experience|\bexp\b|professional|industry|hands-on|working", re.I)
STIPEND = re.compile(r"(?:stipend|₹|inr|rs\.?)\s*[:\-]?\s*([\d,]{4,7})(?:\s*(?:-|to)\s*([\d,]{4,7}))?",
                     re.I)  # fmt: skip


@dataclass(frozen=True)
class Verdict:
    keep: bool
    reason: str
    kind: str = "job"  # job | internship
    level: str = ""  # Internship | Entry level | Not specified
    category: str = ""


def in_india(location: str) -> bool:
    """Open in at least one Indian location (multi-city postings count)."""
    return bool(INDIA.search(location or ""))


def category_of(title: str, department: str = "") -> str | None:
    text = f"{title} {department}"
    if NON_TECH.search(title):
        return None
    for name, pattern in CATEGORIES:
        if pattern.search(text):
            return name
    return None


def min_years(description: str) -> int | None:
    """Years of experience a bachelor's graduate needs, if the text says.

    Counts "N years" near experience wording or followed by "of"/"in" ("5+ years in
    Java"), ignores company age ("for 40 years to create"). When the bar depends on the
    degree ("Bachelors + 2 years or Masters + 0 years"), the bachelor's figure wins.
    """
    found, bachelor = [], []
    for m in YEARS.finditer(description or ""):
        n = int(m.group(1))
        window = description[max(0, m.start() - 60) : m.end() + 40].lower()
        after = description[m.end() : m.end() + 4].lower()
        for_bachelor = "bachelor" in description[max(0, m.start() - 40) : m.start()].lower()
        if n > 15 or not (for_bachelor or EXPERIENCE.search(window)
                          or after.startswith((" of", " in"))):  # fmt: skip
            continue
        found.append(n)
        if for_bachelor:
            bachelor.append(n)
    if bachelor:
        return min(bachelor)
    return min(found) if found else None


def stipend_of(text: str) -> str | None:
    if m := STIPEND.search(text or ""):
        lo = m.group(1).replace(",", "")
        hi = (m.group(2) or "").replace(",", "")
        if int(lo) >= 1000:
            return f"₹{int(lo):,}" + (f"–{int(hi):,}" if hi else "")
    return None


JUNK = re.compile(r"test[ _]?job|_test\b|bug bash|do not apply|dummy|sample posting", re.I)


def classify(p: Posting) -> Verdict:
    if JUNK.search(p.title):
        return Verdict(False, "Test or placeholder posting")
    title = p.title.replace("_", " ")  # "IN_Bosch_Engineer_Sales" style titles
    if not in_india(p.location):
        return Verdict(False, "Not in India")
    category = category_of(title, p.department)
    if category is None:
        return Verdict(False, "Not a tech role")
    if INTERN.search(f"{title} {p.employment_type}") or p.extra.get("internship"):
        return Verdict(True, "Internship", "internship", "Internship", category)
    if SENIOR.search(title):
        return Verdict(False, "Senior role")
    if (m := TITLE_YEARS.search(title)) and int(m.group(1)) >= 2:
        return Verdict(False, f"Needs {m.group(1)}+ years")
    if ENTRY.search(title) or ENTRY_DESC.search(p.description[:3000]):
        return Verdict(True, "Entry level", "job", "Entry level", category)
    years = min_years(p.description)
    if years is not None and years >= 2:
        return Verdict(False, f"Needs {years}+ years")
    if p.source in NO_DESCRIPTION_SOURCES and not p.description.strip():
        # can't read the requirements: flag, don't promote
        return Verdict(True, "Experience unknown", "job", "Check experience", category)
    return Verdict(True, "Experience not stated", "job", "Not specified", category)
