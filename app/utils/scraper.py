import ipaddress
import logging
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_MIN_TEXT_LENGTH = 100


def _is_safe_url(url: str) -> bool:
    """Reject non-http(s) URLs and URLs that resolve to private/internal IPs (SSRF guard)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname
        if not host:
            return False
        for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
            ip = ipaddress.ip_address(info[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_unspecified
                or ip.is_multicast
            ):
                logger.warning("scraper ssrf_blocked url=%s ip=%s", url, ip)
                return False
        return True
    except Exception:
        return False


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
    if not _is_safe_url(url):
        logger.warning("scraper rejected unsafe url=%s", url)
        return None
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
            response = await client.get(url)
        # Follow one level of redirect only if target also passes SSRF check
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            if location and _is_safe_url(location):
                async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
                    response = await client.get(location)
            else:
                logger.info("scraper redirect_blocked url=%s location=%s", url, location)
                return None
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
