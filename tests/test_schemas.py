import pytest
from pydantic import ValidationError

from app.schemas.user import WeightsUpdate


def test_weights_valid():
    weights = WeightsUpdate(
        weight_role_match=0.30,
        weight_skills_match=0.30,
        weight_experience_level=0.20,
        weight_compensation=0.10,
        weight_cultural=0.10,
    )
    assert weights.weight_role_match == 0.30


def test_weights_invalid_sum():
    with pytest.raises(ValidationError) as exc:
        WeightsUpdate(
            weight_role_match=0.40,
            weight_skills_match=0.40,
            weight_experience_level=0.20,
            weight_compensation=0.10,
            weight_cultural=0.10,
        )
    assert "sum to 1.0" in str(exc.value)


def test_weights_tolerance():
    weights = WeightsUpdate(
        weight_role_match=0.301,
        weight_skills_match=0.300,
        weight_experience_level=0.200,
        weight_compensation=0.100,
        weight_cultural=0.100,
    )
    assert weights is not None
