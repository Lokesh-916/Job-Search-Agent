from job_agent.schemas import Assessment, Extraction, Triage
from job_agent.scoring import hard_reject, pay_score, score_job
from job_agent.settings import Preferences, Scoring

RATES = {"USD": 96.0, "INR": 1.0}
PREFS = Preferences()
KEEP = Triage(category="ai_engineering", keep=True, reason="agents")


def ex(**kw) -> Extraction:
    base = dict(
        category="ai_engineering",
        builds_ai=True,
        work_mode="remote",
        india_eligible="yes",
        relocation_abroad_required=False,
        visa_sponsorship="not_needed",
        fresher_ok="yes",
        salary_min=30_000,
        salary_max=50_000,
        salary_currency="USD",
        salary_period="year",
        summary="s",
    )
    return Extraction(**{**base, **kw})


def assess(**kw) -> Assessment:
    base = dict(
        fit_score=80,
        why_fit="w",
        dsa_risk="low",
        sponsorship_credible="not_applicable",
        joining_fit="ok",
        company_quality=7,
        verdict="apply_now",
        pitch="p",
        realistic_salary_lpa_min=28,
        realistic_salary_lpa_max=36,
    )
    return Assessment(**{**base, **kw})


def run(e, a, country="US", triage=KEEP):
    return score_job("1", triage, e, a, country, RATES, PREFS, Scoring())


def test_pay_curve_is_monotonic():
    values = [pay_score(x, PREFS, 96.0) for x in (9, 10, 12, 15, 20, 60, 115, 200)]
    assert values == sorted(values) and values[0] == 0.3 and values[-1] == 1.0
    assert pay_score(None, PREFS, 96.0) == 0.35


def test_triage_reject_has_reason():
    s = run(ex(), assess(), triage=Triage(category="non_technical", keep=False, reason="sales"))
    assert s.bucket == "rejected" and "sales" in s.reject_reason


def test_us_only_remote_rejected():
    assert (
        run(ex(india_eligible="no", visa_sponsorship="not_offered"), assess()).bucket == "rejected"
    )


def test_low_pay_rejected():
    e = ex(salary_min=500_000, salary_max=700_000, salary_currency="INR")
    assert "floor" in hard_reject(KEEP, e, (5.0, 7.0), PREFS)


def test_buckets():
    assert run(ex(), assess()).bucket == "remote_foreign"
    assert run(ex(), assess(), country="IN").bucket == "remote_india"
    assert run(ex(work_mode="hybrid"), assess(), country="IN").bucket == "india_onsite"
    assert run(ex(india_eligible="unclear"), assess()).bucket == "needs_review"
    abroad = ex(work_mode="onsite", india_eligible="no", relocation_abroad_required=True,
                visa_sponsorship="offered")  # fmt: skip
    assert run(abroad, assess(sponsorship_credible="yes")).bucket == "abroad_sponsored"
    assert run(abroad, assess(sponsorship_credible="no")).bucket == "rejected"


def test_remote_beats_onsite_and_dsa_matters():
    remote = run(ex(), assess()).score
    onsite = run(ex(work_mode="onsite"), assess(), country="IN").score
    dsa_heavy = run(ex(), assess(dsa_risk="high")).score
    assert remote > onsite and remote > dsa_heavy


def test_penalties():
    clean = run(ex(), assess()).score
    assert run(ex(red_flags=["996"]), assess()).score == clean - 5
    assert run(ex(), assess(joining_fit="conflict")).score == clean - 10


def test_missing_assessment_needs_review():
    assert run(ex(), None).bucket == "needs_review"
