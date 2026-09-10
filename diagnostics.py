"""Privacy-conscious rotating diagnostics for recovery development."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

from app_settings import user_config_directory


LOG_FILENAME = "anyfiledownloader.log"
_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
_SENSITIVE_HEADER_PATTERN = re.compile(
    r"(?im)^(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*.*$"
)
_SENSITIVE_PARAMETER_PATTERN = re.compile(
    r"(?i)\b(token|signature|auth|key|expires)=([^\s&;]+)"
)
_SAFE_FIELD_NAMES = {
    "category",
    "content_type",
    "detected_type",
    "event",
    "hls_kind",
    "mime_type",
    "reason",
    "source",
    "status_code",
}


def default_log_path() -> Path:
    return user_config_directory() / "logs" / LOG_FILENAME


def redact_url(url: str) -> str:
    """Retain routing information but never log query values or fragments."""
    try:
        parts = urlsplit(url)
    except (TypeError, ValueError):
        return "<invalid-url>"
    if not parts.scheme or not parts.netloc:
        return "<invalid-url>"
    query_marker = "query-redacted" if parts.query else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query_marker, ""))


def redact_urls_in_text(text: str, limit: int = 2000) -> str:
    return _URL_PATTERN.sub(lambda match: redact_url(match.group(0)), text or "")[:limit]


def redact_diagnostic(text: str, limit: int = 2000) -> str:
    redacted = redact_urls_in_text(text, limit * 2)
    redacted = _SENSITIVE_HEADER_PATTERN.sub(lambda match: f"{match.group(1)}: <redacted>", redacted)
    redacted = _SENSITIVE_PARAMETER_PATTERN.sub(lambda match: f"{match.group(1)}=<redacted>", redacted)
    return redacted[:limit]


def safe_event_fields(url: str = "", context: Optional[dict] = None, **fields: Any) -> Dict[str, Any]:
    context = context or {}
    safe: Dict[str, Any] = {}
    if url:
        safe["url"] = redact_url(url)
        try:
            safe["host"] = urlsplit(url).hostname or ""
            safe["has_query"] = bool(urlsplit(url).query)
        except ValueError:
            safe["host"] = ""
            safe["has_query"] = False
    safe["has_referer"] = bool(context.get("referer") or context.get("page_url"))
    safe["has_origin"] = bool(context.get("origin"))
    safe["has_user_agent"] = bool(context.get("user_agent"))
    for name, value in fields.items():
        if name in _SAFE_FIELD_NAMES and value not in (None, ""):
            safe[name] = value
    return safe


def log_event(logger: logging.Logger, event: str, url: str = "", context: Optional[dict] = None, **fields: Any) -> None:
    details = safe_event_fields(url, context, event=event, **fields)
    logger.info("%s", details)


def configure_logging(
    logger_name: str,
    log_path: Optional[Path] = None,
    include_stderr: bool = False,
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    if getattr(logger, "_afd_configured", False):
        if include_stderr and not any(getattr(handler, "_afd_stderr", False) for handler in logger.handlers):
            stderr_handler = logging.StreamHandler()
            stderr_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
            stderr_handler._afd_stderr = True
            logger.addHandler(stderr_handler)
        return logger

    target = log_path or default_log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            target,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(file_handler)
    except OSError:
        # Logging must never prevent downloads or break native-message framing.
        pass

    if include_stderr:
        stderr_handler = logging.StreamHandler()
        stderr_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        stderr_handler._afd_stderr = True
        logger.addHandler(stderr_handler)

    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger._afd_configured = True
    return logger
