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
        ("Enterprise Account Executive", "Mumbai", "", "Not a tech role"),
        ("Software Engineer", "Seattle, WA", "", "Not in India"),
        ("Backend Engineer", "Hyderabad", "You have 3+ years of experience with Go", "Needs 3+ years"),
    ],
)  # fmt: skip
def test_dropped_roles(title, location, description, reason):
    v = classify(post(title, location, description))
    assert not v.keep and v.reason == reason


def test_min_years_needs_experience_context():
    assert min_years("Founded 10 years ago. Requires 0-1 years of experience") == 0
    assert min_years("We are 5 years old") is None


def test_stipend():
    assert stipend_of("Stipend: 25,000 per month") == "₹25,000"
    assert stipend_of("₹15000 - 20000/month") == "₹15,000–20,000"
    assert stipend_of("no money mentioned") is None
