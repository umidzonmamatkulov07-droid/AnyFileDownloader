"""Local-user single-instance coordination for the desktop application."""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app_settings import user_config_directory

try:
    import fcntl
except ImportError:  # pragma: no cover - Fedora/Linux is the supported integration target.
    fcntl = None


MAX_IPC_MESSAGE_SIZE = 64 * 1024


@dataclass(frozen=True)
class InstancePaths:
    directory: Path
    socket_path: Path
    lock_path: Path


def instance_paths(base_directory: Optional[Path] = None) -> InstancePaths:
    directory = Path(base_directory or user_config_directory()) / "ipc"
    return InstancePaths(directory, directory / "desktop.sock", directory / "desktop.lock")


class InstanceLock:
    """Advisory process lock whose kernel ownership survives stale lock-file text."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._stream = None

    def acquire(self) -> bool:
        if fcntl is None:
            raise RuntimeError("Single-instance locking requires an operating-system file lock")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        stream = self.path.open("a+", encoding="ascii")
        os.chmod(self.path, 0o600)
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            stream.close()
            return False
        stream.seek(0)
        stream.truncate()
        stream.write(str(os.getpid()))
        stream.flush()
        self._stream = stream
        return True

    def release(self) -> None:
        if self._stream is None:
            return
        try:
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._stream.close()
            self._stream = None


def _read_message(connection: socket.socket) -> dict:
    chunks = []
    total = 0
    while True:
        chunk = connection.recv(min(8192, MAX_IPC_MESSAGE_SIZE + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_IPC_MESSAGE_SIZE:
            raise ValueError("IPC message exceeds the size limit")
        if b"\n" in chunk:
            break
    payload = b"".join(chunks).split(b"\n", 1)[0]
    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("IPC message must be an object")
    return message


def _same_user_peer(connection: socket.socket) -> bool:
    if not hasattr(socket, "SO_PEERCRED"):
        return True
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _peer_pid, peer_uid, _peer_gid = struct.unpack("3i", credentials)
    return peer_uid == os.getuid()


class IPCServer:
    """One-message-per-connection Unix socket server owned by the current user."""

    def __init__(self, path: Path, handler: Callable[[dict], dict]):
        self.path = Path(path)
        self.handler = handler
        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()

    def start(self) -> None:
        if not hasattr(socket, "AF_UNIX"):
            raise RuntimeError("Local Unix sockets are unavailable")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.path))
            os.chmod(self.path, 0o600)
            server.listen(16)
            server.settimeout(0.2)
        except Exception:
            server.close()
            raise
        self._socket = server
        self._thread = threading.Thread(target=self._serve, name="afd-ipc", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                connection, _address = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                try:
                    if not _same_user_peer(connection):
                        raise PermissionError("IPC peer belongs to another user")
                    response = self.handler(_read_message(connection))
                    if not isinstance(response, dict):
                        response = {"ok": True}
                except Exception as error:
                    response = {
                        "ok": False,
                        "error": {"code": "ipc_error", "message": type(error).__name__},
                    }
                encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
                try:
                    connection.sendall(encoded)
                except OSError:
                    pass

    def stop(self) -> None:
        self._stopping.set()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def send_ipc_message(message: dict, path: Optional[Path] = None, timeout: float = 0.75) -> dict:
    """Send one bounded message to the running desktop instance."""
    socket_path = Path(path or instance_paths().socket_path)
    encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(encoded) > MAX_IPC_MESSAGE_SIZE:
        raise ValueError("IPC message exceeds the size limit")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(socket_path))
        connection.sendall(encoded)
        response = _read_message(connection)
    return response


class SingleInstanceService:
    """Own the process lock and IPC endpoint as one lifecycle."""

    def __init__(self, handler: Callable[[dict], dict], base_directory: Optional[Path] = None):
        self.paths = instance_paths(base_directory)
        self.lock = InstanceLock(self.paths.lock_path)
        self.server = IPCServer(self.paths.socket_path, handler)

    def start(self) -> bool:
        if not self.lock.acquire():
            return False
        try:
            self.server.start()
        except Exception:
            self.lock.release()
            raise
        return True

    def stop(self) -> None:
        self.server.stop()
        self.lock.release()
