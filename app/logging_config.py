import logging
import sys

from app.config import settings

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;31m",
}
BASE_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
DATE_FORMAT = "%H:%M:%S"


class ColorFormatter(logging.Formatter):
    def __init__(self, use_color: bool) -> None:
        super().__init__(BASE_FORMAT, datefmt=DATE_FORMAT)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if not self.use_color:
            return super().format(record)

        original_levelname = record.levelname
        color = COLORS.get(record.levelname, "")
        record.levelname = f"{color}{BOLD}{record.levelname:<8}{RESET}"
        rendered = super().format(record)
        record.levelname = original_levelname
        return f"{DIM}{rendered[:8]}{RESET}{rendered[8:]}"


def configure_logging() -> None:
    level_name = settings.LOG_LEVEL.upper()
    level = getattr(logging, level_name, logging.DEBUG)
    use_color = _should_use_color()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(ColorFormatter(use_color))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    logging.getLogger("app").setLevel(level)
    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger(__name__).debug("logging configured level=%s color=%s", level_name, use_color)


def _should_use_color() -> bool:
    value = settings.LOG_COLOR.strip().lower()
    if value in {"1", "true", "yes", "on", "always"}:
        return True
    if value in {"0", "false", "no", "off", "never"}:
        return False
    return sys.stdout.isatty()


def redact_url(url: str) -> str:
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1) if "://" in url else ("", url)
    host = rest.split("@", 1)[1]
    return f"{scheme}://***:***@{host}" if scheme else f"***:***@{host}"
