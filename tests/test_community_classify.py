import pytest

from job_agent.community.classify import classify, in_india, min_years, stipend_of
from job_agent.community.models import Posting


def post(title, location="Bengaluru, India", description="", employment_type="", department=""):
    return Posting("x", "Acme", "1", title, "u", location=location, description=description,
                   employment_type=employment_type, department=department)  # fmt: skip


@pytest.mark.parametrize(
    ("location", "expected"),
    [("Bengaluru, Karnataka", True), ("Remote, India", True), ("Gurgaon", True),
     ("Remote", False), ("San Francisco, CA", False), ("Remote - US", False),
     ("London; Bangalore", True)],
)  # fmt: skip
def test_in_india(location, expected):
    assert in_india(location) is expected


@pytest.mark.parametrize(
    ("title", "kind", "level", "category"),
    [
        ("Software Engineer, New Grad 2027", "job", "Entry level", "Software engineering"),
        ("SDE I", "job", "Entry level", "Software engineering"),
        ("Machine Learning Intern", "internship", "Internship", "ML / AI"),
        ("Data Analyst", "job", "Not specified", "Data"),
        ("Graduate Engineer Trainee - Embedded", "job", "Entry level", "Embedded / Hardware"),
        ("Full Stack Developer", "job", "Not specified", "Full stack"),
        ("Python Internship", "internship", "Internship", "Software engineering"),
        (
            "Software Development Engineer -I, Merchant Tech",
            "job",
            "Entry level",
            "Software engineering",
        ),
        ("Applied Scientist I, Ads", "job", "Entry level", "ML / AI"),
    ],
)
def test_kept_roles(title, kind, level, category):
    v = classify(post(title))
    assert v.keep and (v.kind, v.level, v.category) == (kind, level, category)


@pytest.mark.parametrize(
    ("title", "location", "description", "reason"),
    [
        ("Senior Software Engineer", "Pune", "", "Senior role"),
        ("Software Engineer II", "Pune", "", "Senior role"),
        ("Software Development Engineer - Test II, Alexa", "Pune", "", "Senior role"),
        ("Research Intern (PhD), Storage Systems for AI", "Hyderabad", "", "PhD / MBA only"),
        ("Software Engineering PMTS", "Hyderabad", "", "Senior role"),
        ("Enterprise Account Executive", "Mumbai", "", "Not a tech role"),
        ("Software Engineer", "Seattle, WA", "", "Not in India"),
        ("Backend Engineer", "Hyderabad", "You have 3+ years of experience with Go", "Needs 3+ years"),
        ("Software Engineering Technical Leader - 10+yrs", "Bangalore", "", "Senior role"),
        ("Software Engineer - Python - 4 to 8 yrs", "Bangalore", "", "Needs 4+ years"),
        ("Software Development Engineer 4", "Noida", "", "Senior role"),
        ("Staff Engineer I", "Bengaluru", "", "Senior role"),
        ("Intermediate Backend Engineer, India", "Bangalore", "", "Senior role"),
        ("sgupta13_test_job", "Bangalore", "", "Test or placeholder posting"),
        ("Apprentice Role for Non-Technology hiring", "Pune", "", "Not a tech role"),
        ("Software Development II, Core Services", "Bengaluru", "", "Senior role"),
        ("Associate II, ML Data Operations", "Chennai", "", "Senior role"),
        ("IN_Bosch Rexroth India_Engineer / Executive_Sales_Industrial", "New Delhi", "", "Not a tech role"),
    ],
)  # fmt: skip
def test_dropped_roles(title, location, description, reason):
    v = classify(post(title, location, description))
    assert not v.keep and v.reason == reason


def test_min_years_needs_experience_context():
    assert min_years("Founded 10 years ago. Requires 0-1 years of experience") == 0
    assert min_years("We are 5 years old") is None


def test_min_years_reads_real_requirement_phrasing():
    assert min_years("- 10+ year of experience") == 10
    assert min_years("Innovating for 40 years to create... - 3 years of professional work") == 3
    assert min_years("- 5+ years in Enterprise Software Applications") == 5
    assert min_years("Bachelors + 2 years of related experience OR Masters + 0 years") == 2
    assert min_years("Bachelors (8-12 years) or Master's degree (6-10 years)") == 8
    assert min_years("We've been innovating fearlessly for 40 years to create solutions") is None


def test_stipend():
    assert stipend_of("Stipend: 25,000 per month") == "₹25,000"
    assert stipend_of("₹15000 - 20000/month") == "₹15,000–20,000"
    assert stipend_of("no money mentioned") is None


def test_description_less_sources_are_flagged_not_promoted():
    p = Posting("workday", "Cisco", "1", "Software Engineer", "u", location="Bangalore, India")
    v = classify(p)
    assert v.keep and v.level == "Check experience"
    p2 = Posting(
        "workday", "Micron", "2", "Graduate Engineering Technician", "u", location="Hyderabad"
    )
    assert classify(p2).level == "Entry level"


def test_titles_are_unescaped():
    assert post("AI &amp; ML Engineer").title == "AI & ML Engineer"
