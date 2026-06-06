import io
import logging
import re

import pdfplumber

logger = logging.getLogger(__name__)


def _normalize(raw: str) -> str:
    raw = raw.replace("–", "-").replace("—", "-").replace("‘", "'").replace("’", "'").replace("•", "*")
    raw = re.sub(r"[^\x20-\x7E\n]", " ", raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def extract_resume_text(pdf_bytes: bytes) -> str:
    logger.debug("pdf extraction start bytes=%s", len(pdf_bytes))
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text = []
            logger.debug("pdf opened pages=%s", len(pdf.pages))
            for index, page in enumerate(pdf.pages):
                text = page.extract_text(x_tolerance=2, y_tolerance=3)
                if text:
                    pages_text.append(text)
                logger.debug("pdf page extracted index=%s chars=%s", index, len(text or ""))
            raw = "\n\n".join(pages_text)
    except Exception as e:
        logger.exception("pdf extraction failed")
        raise ValueError(
            f"PDF appears to be scanned image. Please paste your resume as plain text instead. ({e})"
        ) from e

    text = _normalize(raw)
    if len(text) < 100:
        logger.info("pdf extraction too_short chars=%s", len(text))
        raise ValueError("PDF appears to be scanned image. Please paste your resume as plain text instead.")
    logger.info("pdf extraction complete chars=%s words=%s", len(text), len(text.split()))
    return text
