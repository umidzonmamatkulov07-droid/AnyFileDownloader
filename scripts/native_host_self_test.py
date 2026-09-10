#!/usr/bin/env python3
"""Exercise native framing and launch preparation without starting the GUI."""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from native_host import desktop_command, encode_message, read_message, validate_download_request


def main() -> None:
    sample = {
        "action": "download",
        "url": "https://media.example/video.mp4?signature=sample",
        "page_url": "https://example.com/watch",
        "title": "Native host self-test",
        "detected_type": "VIDEO",
        "mime_type": "video/mp4",
        "source": "manual",
        "referer": "https://example.com/watch",
        "origin": "https://example.com",
        "user_agent": "AnyFileDownloader self-test",
    }
    framed = encode_message(sample)
    decoded = read_message(io.BytesIO(framed))
    validated = validate_download_request(decoded)
    command = desktop_command(validated)
    result = {
        "framing": "ok",
        "validation": "ok",
        "launch_executable": command[0],
        "download_flag_present": "--download-url" in command,
        "would_launch": False,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
