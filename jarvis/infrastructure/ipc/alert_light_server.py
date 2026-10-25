"""Receives alert-light requests from other local processes and applies them."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from jarvis.infrastructure.ipc.unix_datagram import UnixDatagramServer
from jarvis.ports.hardware import AlertLight

LOGGER = logging.getLogger(__name__)

_MAX_MESSAGE_BYTES = 256


class AlertLightControlServer:
    """Owns the control socket; the process that owns the USB serial port runs it."""

    def __init__(self, alert_light: AlertLight, socket_path: Path) -> None:
        self._alert_light = alert_light
        self._server = UnixDatagramServer(
            socket_path,
            _MAX_MESSAGE_BYTES,
            self._handle,
            thread_name="arduino-light-control",
        )

    def start(self) -> None:
        self._server.start()

    def close(self) -> None:
        self._server.close()

    def _handle(self, payload: bytes) -> None:
        try:
            message = json.loads(payload.decode("utf-8"))
            is_active = message["alert_active"]
            if type(is_active) is not bool:
                raise ValueError("alert_active must be boolean")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError, TypeError) as error:
            LOGGER.warning("Rejected alert-light command: %s", error)
            return

        self._alert_light.set_alert_active(is_active)
