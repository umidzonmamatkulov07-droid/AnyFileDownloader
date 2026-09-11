"""Allowlisted browser request context for media download engines."""

from __future__ import annotations

from typing import Dict, Optional


DEFAULT_USER_AGENT = "Mozilla/5.0 AnyFileDownloader-Recovery"


def _safe_header_value(value) -> str:
    return value if isinstance(value, str) and "\r" not in value and "\n" not in value else ""


def media_request_headers(context: Optional[dict] = None, include_default_user_agent: bool = True) -> Dict[str, str]:
    """Forward only Referer, Origin, and User-Agent; never credentials."""
    context = context or {}
    headers: Dict[str, str] = {}
    user_agent = _safe_header_value(context.get("user_agent")) or (DEFAULT_USER_AGENT if include_default_user_agent else "")
    referer = _safe_header_value(context.get("referer")) or _safe_header_value(context.get("page_url"))
    origin = _safe_header_value(context.get("origin"))
    accept = _safe_header_value(context.get("accept"))
    accept_language = _safe_header_value(context.get("accept_language"))
    if user_agent:
        headers["User-Agent"] = user_agent
    if referer:
        headers["Referer"] = referer
    if origin:
        headers["Origin"] = origin
    if accept:
        headers["Accept"] = accept
    if accept_language:
        headers["Accept-Language"] = accept_language
    return headers
