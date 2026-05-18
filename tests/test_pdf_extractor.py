from unittest.mock import MagicMock, patch

import pytest

from app.services.pdf_extractor import extract_resume_text


def test_rejects_too_short_text():
    with pytest.raises(ValueError, match="scanned"):
        extract_resume_text(b"not a real pdf")


def test_normalizes_whitespace():
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Python   Engineer\n\n\n\nExperience " + ("word " * 30)
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]
    with patch("pdfplumber.open", return_value=mock_pdf):
        result = extract_resume_text(b"%PDF-fake")
    assert "Python" in result
    assert "\n\n\n" not in result
