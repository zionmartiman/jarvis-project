"""Rainwater tank distance measurements provided by the Arduino Mega."""

from __future__ import annotations

import logging
import threading

from Arduino.arduino_mega_connection import ArduinoMegaConnection

LOGGER = logging.getLogger(__name__)


class RainwaterTankMeter:
    """Reads and reports the water-surface distance for a rainwater tank."""

    _DISTANCE_COMMAND = "SENSOR DISTANCE"
    _DISTANCE_PREFIX = "DISTANCE_CM "

    def __init__(
        self,
        arduino: ArduinoMegaConnection,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self._arduino = arduino
        self._poll_interval_seconds = poll_interval_seconds
        self._polling_thread: threading.Thread | None = None
        self._stop_polling = threading.Event()

    def start_polling(self) -> None:
        """Log one distance measurement every polling interval."""
        if self._polling_thread is not None:
            return

        self._stop_polling.clear()
        self._polling_thread = threading.Thread(
            target=self._poll_distances,
            name="rainwater-tank-meter",
            daemon=True,
        )
        self._polling_thread.start()

    def read_distance_cm(self) -> float | None:
        """Return the sensor-to-water distance in centimetres."""
        response = self._arduino.request(self._DISTANCE_COMMAND)
        if response is None:
            return None
        if not response.startswith(self._DISTANCE_PREFIX):
            LOGGER.warning("Unexpected rainwater tank response: %s", response)
            return None

        try:
            distance_cm = float(response.removeprefix(self._DISTANCE_PREFIX))
        except ValueError:
            LOGGER.warning("Invalid rainwater tank distance: %s", response)
            return None

        if distance_cm <= 0:
            LOGGER.warning("Rainwater tank distance unavailable: %s", response)
            return None
        return distance_cm

    def close(self) -> None:
        self._stop_polling.set()
        if self._polling_thread is not None:
            self._polling_thread.join(timeout=1)
            self._polling_thread = None

    def _poll_distances(self) -> None:
        while not self._stop_polling.is_set():
            distance_cm = self.read_distance_cm()
            if distance_cm is not None:
                print(f"Rainwater tank distance: {distance_cm:.1f} cm", flush=True)
            self._stop_polling.wait(self._poll_interval_seconds)
