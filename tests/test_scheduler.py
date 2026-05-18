from datetime import datetime, timezone

import pytz

from app.models.user import UserProfile
from app.services.scheduler import is_user_due


def make_profile(briefing_time: str, tz: str) -> UserProfile:
    profile = UserProfile()
    profile.briefing_time = briefing_time
    profile.timezone = tz
    return profile


def test_user_due_when_utc_matches():
    eastern = pytz.timezone("America/New_York")
    local_dt = eastern.localize(datetime(2026, 1, 15, 8, 0, 0))
    assert is_user_due(make_profile("08:00", "America/New_York"), local_dt.astimezone(pytz.utc)) is True


def test_user_not_due_when_utc_differs():
    now_utc = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert is_user_due(make_profile("08:00", "America/New_York"), now_utc) is False


def test_user_due_respects_timezone():
    now_utc = datetime(2026, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
    assert is_user_due(make_profile("07:00", "America/Los_Angeles"), now_utc) is True
