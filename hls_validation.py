"""Bounded HLS manifest validation without downloading media segments."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from request_headers import media_request_headers


MAX_VALIDATION_BYTES = 64 * 1024
VALIDATION_TIMEOUT_SECONDS = 8
HLS_CONTENT_TYPES = {
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
}


@dataclass(frozen=True)
class HLSValidationResult:
    valid: bool
    status_code: Optional[int]
    final_url: str
    content_type: str
    reason: str
    playlist_type: str = "hls_unknown"
    redirected: bool = False
    drm_protected: bool = False


def request_headers(context: Optional[dict] = None) -> Dict[str, str]:
    context = context or {}
    headers = media_request_headers(context)
    headers.setdefault("Accept", "application/vnd.apple.mpegurl, application/x-mpegURL, audio/mpegurl, */*")
    return headers


def classify_playlist(text: str) -> str:
    upper_text = text.upper()
    if "#EXT-X-STREAM-INF" in upper_text:
        return "hls_master"
    if "#EXTINF" in upper_text:
        return "hls_media"
    return "hls_unknown"


def indicates_drm(text: str) -> bool:
    upper_text = text.upper()
    return (
        "METHOD=SAMPLE-AES" in upper_text
        or "KEYFORMAT=\"COM.APPLE.STREAMINGKEYDELIVERY\"" in upper_text
        or "KEYFORMAT=\"COM.MICROSOFT.PLAYREADY\"" in upper_text
        or "KEYFORMAT=\"URN:UUID:EDEF8BA9" in upper_text
    )


def _content_type(response) -> str:
    return (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()


def _decode_body(response, body: bytes) -> str:
    charset = None
    get_charset = getattr(response.headers, "get_content_charset", None)
    if callable(get_charset):
        charset = get_charset()
    return body.decode(charset or "utf-8", errors="replace")


def validate_hls_url(
    url: str,
    context: Optional[dict] = None,
    opener: Optional[Callable] = None,
    timeout: int = VALIDATION_TIMEOUT_SECONDS,
    max_bytes: int = MAX_VALIDATION_BYTES,
) -> HLSValidationResult:
    """Fetch only an initial bounded response portion and verify #EXTM3U."""
    request = urllib.request.Request(url, headers=request_headers(context))
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
            status_code = getattr(response, "status", None) or response.getcode()
            final_url = response.geturl() or url
            content_type = _content_type(response)
            body = response.read(max_bytes)
            text = _decode_body(response, body)
    except urllib.error.HTTPError as error:
        content_type = (error.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        result = HLSValidationResult(False, error.code, error.geturl() or url, content_type, "http_error")
        error.close()
        return result
    except (urllib.error.URLError, TimeoutError, OSError):
        return HLSValidationResult(False, None, url, "", "network_error")

    redirected = final_url != url
    leading_text = text.lstrip("\ufeff\r\n\t ")
    leading_lower = leading_text[:2048].lower()
    is_html = content_type in {"text/html", "application/xhtml+xml"} or leading_lower.startswith(("<!doctype html", "<html"))
    is_json = content_type in {"application/json", "text/json"} or leading_lower.startswith(("{", "["))
    marker_position = leading_text.upper().find("#EXTM3U")

    if is_html:
        reason = "redirected_to_webpage" if redirected else "html_response"
        return HLSValidationResult(False, status_code, final_url, content_type, reason, redirected=redirected)
    if is_json:
        return HLSValidationResult(False, status_code, final_url, content_type, "json_response", redirected=redirected)
    if marker_position < 0 or marker_position > 1024:
        reason = "redirected_non_playlist" if redirected else "missing_extm3u"
        return HLSValidationResult(False, status_code, final_url, content_type, reason, redirected=redirected)

    playlist_type = classify_playlist(text)
    drm_protected = indicates_drm(text)
    if drm_protected:
        return HLSValidationResult(
            False,
            status_code,
            final_url,
            content_type,
            "drm_protected",
            playlist_type,
            redirected,
            True,
        )

    reason = "valid_playlist" if content_type in HLS_CONTENT_TYPES else "valid_playlist_mime_mismatch"
    return HLSValidationResult(True, status_code, final_url, content_type, reason, playlist_type, redirected, False)
