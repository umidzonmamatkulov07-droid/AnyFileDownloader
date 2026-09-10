"""Chrome native-messaging bridge for AnyFileDownloader.

Standard output is reserved exclusively for framed native-messaging responses.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, Optional
from urllib.parse import urlparse


MAX_MESSAGE_SIZE = 16 * 1024 * 1024
LOGGER = logging.getLogger("anyfiledownloader.native_host")


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
    if parsed_url is None or parsed_url.scheme.lower() not in {"http", "https", "ftp"} or not parsed_url.netloc:
        raise ValueError("A valid HTTP, HTTPS, or FTP URL is required")

    request = {"action": "download", "url": url}
    for field in ("page_url", "title"):
        value = message.get(field, "")
        request[field] = value if isinstance(value, str) else ""
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
    if request["page_url"]:
        command.extend(["--page-url", request["page_url"]])
    if request["title"]:
        command.extend(["--title", request["title"]])
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


def run(input_stream: BinaryIO, output_stream: BinaryIO) -> None:
    while True:
        try:
            message = read_message(input_stream)
            if message is None:
                return
            request = validate_download_request(message)
            process_id = forward_download_request(request)
            send_message(output_stream, {"ok": True, "action": "download", "pid": process_id})
        except Exception as error:
            LOGGER.exception("Native messaging request failed")
            send_message(output_stream, {"ok": False, "error": str(error)})


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    run(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
