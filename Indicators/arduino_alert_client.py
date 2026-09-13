"""Cliente local para solicitar la luz física de alerta al proceso de voz."""

from __future__ import annotations

import json
import logging
import socket
from pathlib import Path

from core.interfaces import AlertLight

LOGGER = logging.getLogger(__name__)


class ArduinoAlertClient(AlertLight):
    """Envía al proceso dueño del USB la orden de controlar el LED de alerta."""

    def __init__(self, control_socket_path: Path) -> None:
        self._control_socket_path = control_socket_path

    def set_alert_active(self, is_active: bool) -> None:
        payload = json.dumps({"alert_active": is_active}).encode("utf-8")

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
                client.sendto(payload, str(self._control_socket_path))
        except OSError as error:
            # Una alerta hablada nunca debe fallar por un LED desconectado.
            LOGGER.warning("Luz de alerta no disponible: %s", error)
