import uuid

import pytest

from app.utils.token import generate_rewrite_token, verify_token


def test_roundtrip():
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    token = generate_rewrite_token(user_id, job_id)
    payload = verify_token(token)
    assert payload["user_id"] == str(user_id)
    assert payload["job_id"] == str(job_id)


def test_tampered_token_raises():
    token = generate_rewrite_token(uuid.uuid4(), uuid.uuid4())
    bad_token = token[:-5] + "XXXXX"
    with pytest.raises(Exception):
        verify_token(bad_token)
