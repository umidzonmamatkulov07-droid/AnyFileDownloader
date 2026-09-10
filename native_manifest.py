"""Generate Chrome native-messaging host manifests safely."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
import sys
from pathlib import Path
from typing import Dict


HOST_NAME = "com.anyfiledownloader.native_host"
EXTENSION_ID_PATTERN = re.compile(r"^[a-p]{32}$")


def build_host_manifest(extension_id: str, host_path: Path) -> Dict[str, object]:
    if not EXTENSION_ID_PATTERN.fullmatch(extension_id):
        raise ValueError("Chrome extension ID must be 32 lowercase letters from a through p")
    resolved_host = host_path.expanduser().resolve()
    if not resolved_host.is_file():
        raise ValueError(f"Native host does not exist: {resolved_host}")

    return {
        "name": HOST_NAME,
        "description": "AnyFileDownloader native messaging bridge",
        "path": str(resolved_host),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }


def write_host_manifest(extension_id: str, host_path: Path, output_path: Path) -> None:
    manifest = build_host_manifest(extension_id, host_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        temporary_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_launcher(python_path: Path, host_path: Path, output_path: Path) -> None:
    resolved_python = python_path.expanduser().resolve()
    resolved_host = host_path.expanduser().resolve()
    if not resolved_python.is_file():
        raise ValueError(f"Python interpreter does not exist: {resolved_python}")
    if not resolved_host.is_file():
        raise ValueError(f"Native host does not exist: {resolved_host}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    command = f"exec {shlex.quote(str(resolved_python))} {shlex.quote(str(resolved_host))}"
    try:
        temporary_path.write_text(f"#!/bin/sh\n{command}\n", encoding="utf-8")
        temporary_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Generate an AnyFileDownloader Chrome native-host manifest")
    parser.add_argument("--extension-id", required=True)
    parser.add_argument("--host-path", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--launcher-output", type=Path)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    manifest_host = arguments.host_path
    if arguments.launcher_output:
        write_launcher(Path(sys.executable), arguments.host_path, arguments.launcher_output)
        manifest_host = arguments.launcher_output
    write_host_manifest(arguments.extension_id, manifest_host, arguments.output)


if __name__ == "__main__":
    main()
