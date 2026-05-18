from app.schemas.job import RawJob
from app.utils.scoring import gate_filter, keyword_overlap_score


def test_overlap_identical_text():
    assert keyword_overlap_score("python fastapi postgres", "python fastapi postgres") > 0.8


def test_overlap_no_match():
    assert keyword_overlap_score("cooking recipes baking", "python fastapi postgres") < 0.1


def test_overlap_short_words_ignored():
    assert keyword_overlap_score("the a an", "the a an") == 0.0


def test_overlap_role_abbreviation_matches_full_form():
    score = keyword_overlap_score("experienced swe developer", "software engineer python fastapi")
    assert score >= 0.08, f"Expected >= 0.08, got {score}"


def test_overlap_ml_abbreviation_matches_full_form():
    score = keyword_overlap_score("ml researcher background", "machine learning engineer role")
    assert score >= 0.08, f"Expected >= 0.08, got {score}"


def test_gate_filter_rejects_intern():
    job = RawJob(title="Intern Software Engineer", company="Acme", source="ats")
    assert len(gate_filter([job], seniority="senior", min_salary=None)) == 0


def test_gate_filter_keeps_senior():
    job = RawJob(title="Senior Software Engineer", company="Acme", source="ats")
    assert len(gate_filter([job], seniority="senior", min_salary=None)) == 1


def test_gate_filter_rejects_low_salary():
    job = RawJob(title="Senior Engineer", company="Acme", salary_max=60000, source="ats")
    assert len(gate_filter([job], seniority="senior", min_salary=None)) == 0


def test_gate_filter_keeps_no_salary_info():
    job = RawJob(title="Senior Engineer", company="Acme", source="ats")
    assert len(gate_filter([job], seniority="senior", min_salary=None)) == 1


def test_gate_filter_rejects_old_posted_date():
    job = RawJob(title="Senior Engineer", company="Acme", posted_date="2025-01-01", source="ats")
    assert len(gate_filter([job], seniority="senior", min_salary=None)) == 0
