import io

from docx import Document

from app.schemas.job import ScoredJob
from app.services.docx_builder import build_resume_docx


def make_job():
    return ScoredJob(
        title="Senior ML Engineer",
        company="Anthropic",
        source="ats",
        global_score=82,
        verdict="apply",
        scores={},
        red_flags=[],
        citations=[],
        summary="",
    )


def test_build_returns_bytes():
    result = build_resume_docx("## Summary\n\nGreat engineer.\n\n## Skills\n\nPython, SQL", "Jane Doe", make_job())
    assert isinstance(result, bytes)
    assert len(result) > 100


def test_docx_contains_name():
    result = build_resume_docx("## Summary\n\nGreat engineer.", "Jane Doe", make_job())
    doc = Document(io.BytesIO(result))
    assert "Jane Doe" in " ".join(p.text for p in doc.paragraphs)


def test_docx_contains_section_header():
    result = build_resume_docx("## Experience\n\n- Built stuff", "Jane Doe", make_job())
    doc = Document(io.BytesIO(result))
    assert "Experience" in " ".join(p.text for p in doc.paragraphs)
