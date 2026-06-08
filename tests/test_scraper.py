from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.scraper import fetch_job_description


@pytest.mark.asyncio
async def test_fetch_returns_text_on_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = (
        "<html><body><script>ignore me</script><p>We are hiring a Senior Engineer "
        "with Python API experience, distributed systems work, and ownership of backend services. "
        "This role partners closely with product teams.</p></body></html>"
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("app.utils.scraper.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_job_description("https://example.com/job/123")

    assert result is not None
    assert "Senior Engineer" in result
    assert "ignore me" not in result
    assert "<html>" not in result


@pytest.mark.asyncio
async def test_fetch_returns_none_on_http_error():
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("app.utils.scraper.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_job_description("https://example.com/job/404")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_exception():
    import httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch("app.utils.scraper.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_job_description("https://example.com/job/slow")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_returns_none_when_text_too_short():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body><p>Hi</p></body></html>"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("app.utils.scraper.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_job_description("https://example.com/job/tiny")

    assert result is None
