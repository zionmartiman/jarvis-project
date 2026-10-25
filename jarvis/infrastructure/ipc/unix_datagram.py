"""Unix datagram sockets: a threaded receiver and a one-shot sender."""

from __future__ import annotations

import logging
import os
import socket
import threading
from collections.abc import Callable
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def send_datagram(path: Path, payload: bytes) -> None:
    """Send one datagram to the socket at ``path``; raises OSError if nobody listens."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.sendto(payload, str(path))


class UnixDatagramServer:
    """Receives datagrams on a private socket file and hands each one to ``handler``."""

    def __init__(
        self,
        path: Path,
        max_bytes: int,
        handler: Callable[[bytes], None],
        thread_name: str,
    ) -> None:
        self._path = path
        self._max_bytes = max_bytes
        self._handler = handler
        self._thread_name = thread_name
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return

        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._path.unlink(missing_ok=True)

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        listener.bind(str(self._path))
        os.chmod(self._path, 0o600)

        self._socket = listener
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._receive,
            name=self._thread_name,
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
            self._socket = None

        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None

        self._path.unlink(missing_ok=True)

    def _receive(self) -> None:
        listener = self._socket
        assert listener is not None

        while not self._stop.is_set():
            try:
                payload, _ = listener.recvfrom(self._max_bytes)
            except OSError:
                if not self._stop.is_set():
                    LOGGER.exception("Datagram receiver %s failed.", self._thread_name)
                return

            try:
                self._handler(payload)
            except Exception:
                LOGGER.exception("Datagram handler %s failed.", self._thread_name)
