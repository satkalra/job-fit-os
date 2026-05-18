import pytest

from app.models.user import UserProfile
from app.pipeline.score import _apply_red_flag_penalties, _compute_weighted_score, _validate_weights


def make_profile(**kwargs):
    profile = UserProfile()
    profile.seniority = kwargs.get("seniority", "senior")
    profile.min_salary = kwargs.get("min_salary", None)
    profile.weight_role_match = kwargs.get("weight_role_match", 0.30)
    profile.weight_skills_match = kwargs.get("weight_skills_match", 0.30)
    profile.weight_experience_level = kwargs.get("weight_experience_level", 0.20)
    profile.weight_compensation = kwargs.get("weight_compensation", 0.10)
    profile.weight_cultural = kwargs.get("weight_cultural", 0.10)
    return profile


def test_compute_weighted_score_default_weights():
    scores = {"roleMatch": 5, "skillsMatch": 5, "experienceLevel": 5, "compensation": 5, "cultural": 5}
    assert _compute_weighted_score(scores, make_profile()) == pytest.approx(100.0, abs=0.1)


def test_compute_weighted_score_custom_weights():
    scores = {"roleMatch": 5, "skillsMatch": 5, "experienceLevel": 1, "compensation": 1, "cultural": 1}
    profile = make_profile(
        weight_role_match=0.5,
        weight_skills_match=0.5,
        weight_experience_level=0.0,
        weight_compensation=0.0,
        weight_cultural=0.0,
    )
    assert _compute_weighted_score(scores, profile) == pytest.approx(100.0, abs=0.1)


def test_red_flag_penalty_high():
    assert _apply_red_flag_penalties(80, [{"severity": "high"}]) == 65


def test_red_flag_penalty_mixed():
    assert _apply_red_flag_penalties(80, [{"severity": "low"}, {"severity": "med"}]) == 73


def test_weights_invalid_sum_raises():
    profile = make_profile(weight_role_match=0.5, weight_skills_match=0.5)
    with pytest.raises(ValueError, match="weights"):
        _validate_weights(profile)
