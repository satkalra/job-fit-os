from app.schemas.job import RawJob
from app.utils.scoring import gate_filter


def _job(title="Engineer", description="", location=None, salary_max=None):
    return RawJob(title=title, company="Acme", description=description, location=location,
                  salary_max=salary_max, source="ats")


# --- two-way seniority gate ---

def test_junior_candidate_drops_senior_title():
    job = _job(title="Senior Software Engineer")
    assert len(gate_filter([job], seniority="junior")) == 0


def test_junior_candidate_drops_staff_title():
    job = _job(title="Staff Engineer")
    assert len(gate_filter([job], seniority="junior")) == 0


def test_junior_candidate_keeps_matching_title():
    job = _job(title="Junior Software Engineer")
    assert len(gate_filter([job], seniority="junior")) == 1


def test_mid_candidate_drops_principal_but_not_senior():
    principal = _job(title="Principal Engineer")
    senior = _job(title="Senior Engineer")
    kept = gate_filter([principal, senior], seniority="mid")
    assert [j.title for j in kept] == ["Senior Engineer"]


def test_junior_candidate_passes_high_years_no_salary():
    # No salary info → can't confirm senior level; let scorer judge instead of hard-block.
    job = _job(title="Software Engineer", description="We need 7+ years of experience.")
    assert len(gate_filter([job], seniority="junior")) == 1


def test_junior_candidate_keeps_low_years_requirement():
    job = _job(title="Software Engineer", description="2+ years of experience preferred.")
    assert len(gate_filter([job], seniority="junior")) == 1


def test_senior_candidate_unaffected_by_high_years():
    job = _job(title="Software Engineer", description="8+ years of experience required.")
    assert len(gate_filter([job], seniority="senior")) == 1


# --- location / country gate ---

def test_drops_location_outside_preferred():
    job = _job(location="Austin, TX")
    assert len(gate_filter([job], preferred_locations=["nyc"])) == 0


def test_keeps_preferred_location():
    job = _job(location="New York, NY")
    assert len(gate_filter([job], preferred_locations=["nyc"])) == 1


def test_keeps_job_in_allowed_country():
    job = _job(location="Bangalore, India")
    assert len(gate_filter([job], countries=["India"])) == 1


def test_drops_job_outside_allowed_country():
    job = _job(location="London, UK")
    assert len(gate_filter([job], countries=["India"])) == 0


def test_keeps_remote_when_prefs_set():
    job = _job(location="Remote")
    assert len(gate_filter([job], preferred_locations=["nyc"])) == 1


def test_no_location_gate_when_unset():
    job = _job(location="Anywhere on Earth")
    assert len(gate_filter([job])) == 1


# --- sponsorship gate ---

def test_drops_no_sponsorship_when_needed():
    job = _job(description="We do not provide visa sponsorship for this role.")
    assert len(gate_filter([job], needs_sponsorship=True)) == 0


def test_drops_citizens_only_when_needed():
    job = _job(description="US citizens only. Must have work authorization.")
    assert len(gate_filter([job], needs_sponsorship=True)) == 0


def test_keeps_sponsorship_offered_when_needed():
    job = _job(description="We are happy to provide visa sponsorship.")
    assert len(gate_filter([job], needs_sponsorship=True)) == 1


def test_ignores_sponsorship_text_when_not_needed():
    job = _job(description="We do not provide visa sponsorship.")
    assert len(gate_filter([job], needs_sponsorship=False)) == 1


# --- salary-adjusted years gate (inflated JD requirements) ---

def test_high_years_blocked_when_salary_confirms_senior():
    # "7+ years" + $200k salary = genuinely senior, block junior
    job = _job(description="7+ years of experience required.", salary_max=200000)
    assert len(gate_filter([job], seniority="junior")) == 0


def test_high_years_passes_when_salary_is_junior_level():
    # "5+ years" but salary $85k = inflated requirement, junior can apply
    job = _job(description="5+ years of experience preferred.", salary_max=85000)
    assert len(gate_filter([job], seniority="junior")) == 1


def test_high_years_passes_when_no_salary_info():
    # No salary info + "5+ years" = can't confirm senior level, don't hard-block
    job = _job(description="5+ years of experience required.", salary_max=None)
    assert len(gate_filter([job], seniority="junior")) == 1


def test_high_years_blocked_when_salary_confirms_mid_for_junior():
    # $130k is confirmed mid-senior range, years gate applies for junior
    job = _job(description="6+ years required.", salary_max=130000)
    assert len(gate_filter([job], seniority="junior")) == 0


def test_mid_candidate_high_years_salary_inflated():
    # "8+ years" but $100k salary = inflated for mid candidate, should pass
    job = _job(description="8+ years required.", salary_max=100000)
    assert len(gate_filter([job], seniority="mid")) == 1
