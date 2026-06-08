import logging
from html.parser import HTMLParser

import httpx

logger = logging.getLogger(__name__)

_MIN_TEXT_LENGTH = 100


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def text(self) -> str:
        return " ".join(self._parts)


async def fetch_job_description(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            response = await client.get(url)
        if response.status_code >= 400:
            logger.info("scraper http_error url=%s status=%s", url, response.status_code)
            return None

        parser = _TextExtractor()
        parser.feed(response.text)
        text = parser.text()
        if len(text) < _MIN_TEXT_LENGTH:
            logger.info("scraper text_too_short url=%s chars=%s", url, len(text))
            return None

        logger.info("scraper success url=%s chars=%s", url, len(text))
        return text
    except Exception as exc:
        logger.info("scraper failed url=%s error=%s", url, exc)
        return None
