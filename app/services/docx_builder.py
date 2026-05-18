import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

from app.schemas.job import ScoredJob


def build_resume_docx(tailored_markdown: str, user_name: str, job: ScoredJob) -> bytes:
    doc = Document()

    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    title_para = doc.add_heading(user_name, level=1)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title_para.runs:
        run.font.size = Pt(14)
        run.font.bold = True

    for line in tailored_markdown.split("\n"):
        line = line.rstrip()
        if line.startswith("## "):
            heading = doc.add_heading(line[3:], level=2)
            for run in heading.runs:
                run.font.size = Pt(13)
                run.font.color.rgb = RGBColor(0x26, 0x4F, 0x78)
        elif line.startswith("# "):
            heading = doc.add_heading(line[2:], level=1)
            for run in heading.runs:
                run.font.size = Pt(14)
        elif line.startswith("- ") or line.startswith("* "):
            para = doc.add_paragraph(line[2:], style="List Bullet")
            for run in para.runs:
                run.font.size = Pt(11)
                run.font.name = "Calibri"
        elif line.startswith("---"):
            doc.add_paragraph()
        elif line.strip():
            para = doc.add_paragraph(line)
            for run in para.runs:
                run.font.size = Pt(11)
                run.font.name = "Calibri"

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
