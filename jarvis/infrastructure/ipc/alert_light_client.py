"""Asks the process that owns the USB port to switch the physical alert light."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from jarvis.infrastructure.ipc.unix_datagram import send_datagram
from jarvis.ports.hardware import AlertLight

LOGGER = logging.getLogger(__name__)


class AlertLightClient(AlertLight):
    """Sends the alert-light order to the voice process over its control socket."""

    def __init__(self, control_socket_path: Path) -> None:
        self._control_socket_path = control_socket_path

    def set_alert_active(self, is_active: bool) -> None:
        payload = json.dumps({"alert_active": is_active}).encode("utf-8")

        try:
            send_datagram(self._control_socket_path, payload)
        except OSError as error:
            # A spoken alert must never fail because the light is unavailable.
            LOGGER.warning("Alert light unavailable: %s", error)
