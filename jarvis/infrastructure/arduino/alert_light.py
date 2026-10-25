"""Independent alert light of the Arduino Mega."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from jarvis.infrastructure.arduino import protocol
from jarvis.ports.hardware import AlertLight

if TYPE_CHECKING:
    from jarvis.infrastructure.arduino.serial_connection import SerialRequester

LOGGER = logging.getLogger(__name__)


class ArduinoAlertLight(AlertLight):
    """Switches the physical alert light, skipping repeated commands."""

    def __init__(self, arduino: SerialRequester) -> None:
        self._arduino = arduino
        self._is_active: bool | None = None

    def set_alert_active(self, is_active: bool) -> None:
        if is_active == self._is_active:
            return

        command = protocol.LIGHT_ALERT_ON if is_active else protocol.LIGHT_ALERT_OFF
        response = self._arduino.request(command)
        if response != protocol.OK:
            LOGGER.warning("Unexpected Arduino Mega response: %s", response)
            return
        self._is_active = is_active
