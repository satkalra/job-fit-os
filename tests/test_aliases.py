from app.utils.aliases import expand_location, expand_role, normalize_company


def test_normalize_company_strips_suffix():
    assert normalize_company("Anthropic, Inc.") == "anthropic"


def test_normalize_company_strips_llc():
    assert normalize_company("Acme LLC") == "acme"


def test_normalize_company_no_suffix():
    assert normalize_company("Stripe") == "stripe"


def test_normalize_company_multi_word():
    assert normalize_company("Google Corp") == "google"


def test_expand_location_canonical_key():
    result = expand_location("nyc")
    assert "new york" in result
    assert "manhattan" in result


def test_expand_location_alias_lookup():
    result = expand_location("new york city")
    assert "nyc" in result
    assert "manhattan" in result


def test_expand_location_with_punctuation():
    result = expand_location("New York, NY")
    assert "nyc" in result or "new york" in result


def test_expand_location_unknown_passthrough():
    result = expand_location("Reykjavik")
    assert "reykjavik" in result


def test_expand_role_canonical_key():
    result = expand_role("swe")
    assert "software engineer" in result


def test_expand_role_alias_lookup():
    result = expand_role("software engineer")
    assert "swe" in result


def test_expand_role_unknown_passthrough():
    result = expand_role("glassblower")
    assert "glassblower" in result
