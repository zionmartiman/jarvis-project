"""HC-SR04 ultrasonic distance sensor read through the Arduino Mega."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from jarvis.infrastructure.arduino import protocol
from jarvis.ports.hardware import DistanceSensor

if TYPE_CHECKING:
    from jarvis.infrastructure.arduino.serial_connection import SerialRequester

LOGGER = logging.getLogger(__name__)


class ArduinoDistanceSensor(DistanceSensor):
    """Requests one distance measurement and validates the Arduino response."""

    def __init__(self, arduino: SerialRequester) -> None:
        self._arduino = arduino

    def read_distance_cm(self) -> float | None:
        response = self._arduino.request(protocol.SENSOR_DISTANCE)
        if response is None:
            return None
        if not response.startswith(protocol.DISTANCE_PREFIX):
            LOGGER.warning("Unexpected rainwater tank response: %s", response)
            return None
        try:
            distance_cm = float(response.removeprefix(protocol.DISTANCE_PREFIX))
        except ValueError:
            LOGGER.warning("Invalid rainwater tank distance: %s", response)
            return None
        if distance_cm <= 0:
            LOGGER.warning("Rainwater tank distance unavailable: %s", response)
            return None
        return distance_cm
