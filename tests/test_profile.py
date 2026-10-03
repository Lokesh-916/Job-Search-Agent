from job_agent.profile import full_brief, preferences_brief

PROFILE = {
    "location": "Kurnool, India",
    "education": {"degree": "B.Tech AI", "graduation": "2027-05"},
    "preferences": {"favourite_work": "agents", "also_happy_with": ["backend", "devops"]},
    "projects": [{"name": "X"}],
    "name": "not in full brief",
}


def test_preferences_brief_mentions_wants():
    brief = preferences_brief(PROFILE)
    assert "agents" in brief and "backend, devops" in brief and "Kurnool" in brief


def test_full_brief_skips_identity_fields():
    brief = full_brief(PROFILE)
    assert "projects" in brief and "not in full brief" not in brief
