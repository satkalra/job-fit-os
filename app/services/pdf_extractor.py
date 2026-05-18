import io
import re

import pdfplumber


def _normalize(raw: str) -> str:
    raw = raw.replace("–", "-").replace("—", "-").replace("‘", "'").replace("’", "'").replace("•", "*")
    raw = re.sub(r"[^\x20-\x7E\n]", " ", raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def extract_resume_text(pdf_bytes: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text = []
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=2, y_tolerance=3)
                if text:
                    pages_text.append(text)
            raw = "\n\n".join(pages_text)
    except Exception as e:
        raise ValueError(
            f"PDF appears to be scanned image. Please paste your resume as plain text instead. ({e})"
        ) from e

    text = _normalize(raw)
    if len(text) < 100:
        raise ValueError("PDF appears to be scanned image. Please paste your resume as plain text instead.")
    return text
