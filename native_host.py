#!/usr/bin/env python3
"""Chrome native-messaging bridge for AnyFileDownloader.

Standard output is reserved exclusively for framed native-messaging responses.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, Optional
from urllib.parse import urlparse

from diagnostics import configure_logging, log_event


MAX_MESSAGE_SIZE = 16 * 1024 * 1024
LOGGER = configure_logging("anyfiledownloader.native_host")
DETECTED_TYPES = {"HLS", "DASH", "VIDEO", "AUDIO", "DIRECT", "UNKNOWN"}
SOURCES = {"webRequest", "performance", "media_element", "manual"}


def _read_exact(stream: BinaryIO, length: int) -> bytes:
    chunks = []
    bytes_remaining = length
    while bytes_remaining:
        chunk = stream.read(bytes_remaining)
        if not chunk:
            break
        chunks.append(chunk)
        bytes_remaining -= len(chunk)
    return b"".join(chunks)


def read_message(stream: BinaryIO) -> Optional[dict]:
    length_bytes = stream.read(4)
    if not length_bytes:
        return None
    if len(length_bytes) != 4:
        raise ValueError("Incomplete native-message length header")

    message_length = struct.unpack("<I", length_bytes)[0]
    if message_length > MAX_MESSAGE_SIZE:
        raise ValueError("Native message exceeds the size limit")
    payload = _read_exact(stream, message_length)
    if len(payload) != message_length:
        raise ValueError("Incomplete native-message payload")

    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("Native message must be a JSON object")
    return message


def encode_message(message: dict) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


def send_message(stream: BinaryIO, message: dict) -> None:
    stream.write(encode_message(message))
    stream.flush()


def validate_download_request(message: dict) -> dict:
    if message.get("action") != "download":
        raise ValueError("Unsupported action; expected 'download'")

    url = message.get("url")
    parsed_url = urlparse(url) if isinstance(url, str) else None
    if (
        parsed_url is None
        or "\x00" in url
        or len(url) > 8192
        or parsed_url.scheme.lower() not in {"http", "https", "ftp"}
        or not parsed_url.netloc
    ):
        raise ValueError("A valid HTTP, HTTPS, or FTP URL is required")

    request = {"action": "download", "url": url}
    field_limits = {
        "page_url": 8192,
        "title": 512,
        "detected_type": 32,
        "mime_type": 256,
        "source": 32,
        "referer": 8192,
        "origin": 2048,
        "user_agent": 1024,
    }
    for field, maximum_length in field_limits.items():
        value = message.get(field, "")
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        if "\x00" in value:
            raise ValueError(f"{field} contains an invalid null character")
        if len(value) > maximum_length:
            raise ValueError(f"{field} exceeds the size limit")
        request[field] = value

    request["detected_type"] = request["detected_type"].upper() or "UNKNOWN"
    if request["detected_type"] not in DETECTED_TYPES:
        raise ValueError("Unsupported detected_type")
    request["source"] = request["source"] or "manual"
    if request["source"] not in SOURCES:
        raise ValueError("Unsupported source")
    return request


def desktop_command(request: dict) -> list[str]:
    configured_app = os.environ.get("ANYFILEDOWNLOADER_APP")
    if configured_app:
        command = [configured_app]
    elif getattr(sys, "frozen", False):
        executable_name = "AnyFileDownloader.exe" if sys.platform == "win32" else "AnyFileDownloader"
        command = [str(Path(sys.executable).with_name(executable_name))]
    else:
        command = [sys.executable, str(Path(__file__).with_name("downloader.py"))]

    command.extend(["--download-url", request["url"]])
    command_line_fields = {
        "page_url": "--page-url",
        "title": "--title",
        "detected_type": "--detected-type",
        "mime_type": "--mime-type",
        "source": "--source",
        "referer": "--referer",
        "origin": "--origin",
        "user_agent": "--user-agent",
    }
    for field, option in command_line_fields.items():
        if request[field]:
            command.extend([option, request[field]])
    return command


def forward_download_request(request: dict) -> int:
    creation_flags = 0
    popen_options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_options["start_new_session"] = True

    process = subprocess.Popen(desktop_command(request), creationflags=creation_flags, **popen_options)
    return process.pid


def error_response(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def handle_message(message: dict) -> dict:
    if message.get("action") == "ping":
        log_event(LOGGER, "native_ping_received")
        return {"ok": True, "action": "ping", "status": "ready"}
    try:
        request = validate_download_request(message)
    except ValueError as error:
        log_event(LOGGER, "native_request_rejected", category="invalid_request", reason=str(error))
        return error_response("invalid_request", str(error))

    log_event(
        LOGGER,
        "native_request_received",
        request["url"],
        request,
        detected_type=request["detected_type"],
        source=request["source"],
    )

    try:
        process_id = forward_download_request(request)
    except Exception as error:
        log_event(LOGGER, "gui_launch_failed", category="launch_failed", reason=type(error).__name__)
        return error_response("launch_failed", "Could not start the AnyFileDownloader desktop application.")
    log_event(LOGGER, "gui_launched", request["url"], request, detected_type=request["detected_type"])
    return {"ok": True, "action": "download", "status": "accepted", "pid": process_id}


def run(input_stream: BinaryIO, output_stream: BinaryIO) -> None:
    while True:
        try:
            message = read_message(input_stream)
        except Exception as error:
            log_event(LOGGER, "native_frame_rejected", category="invalid_message", reason=type(error).__name__)
            send_message(output_stream, error_response("invalid_message", str(error)))
            return
        if message is None:
            return
        send_message(output_stream, handle_message(message))


def main() -> None:
    configure_logging("anyfiledownloader.native_host", include_stderr=True)
    run(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
