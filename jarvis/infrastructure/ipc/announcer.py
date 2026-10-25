"""Queues spoken announcements for the independent announcement service."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from jarvis.infrastructure.ipc.unix_datagram import send_datagram
from jarvis.ports.notifications import Announcer

LOGGER = logging.getLogger(__name__)


class SocketAnnouncer(Announcer):
    """Sends each text to the announcement service socket."""

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = socket_path

    def announce(self, text: str) -> None:
        payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")

        try:
            send_datagram(self._socket_path, payload)
        except OSError as error:
            LOGGER.warning("Announcement service is not listening: %s", error)
