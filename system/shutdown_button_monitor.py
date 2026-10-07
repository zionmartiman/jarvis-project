"""Monitors the Arduino shutdown button independently of tank measurements."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Arduino.arduino_mega_connection import ArduinoMegaConnection

LOGGER = logging.getLogger(__name__)


class ShutdownButtonMonitor:
    """Polls the Arduino button status and reports each latched press."""

    _BUTTON_COMMAND = "BUTTON STATUS"
    _PRESSED_RESPONSE = "BUTTON_SHUTDOWN"

    def __init__(
        self,
        arduino: ArduinoMegaConnection,
        on_pressed: Callable[[], None],
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self._arduino = arduino
        self._on_pressed = on_pressed
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_monitoring = threading.Event()
        self._monitoring_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._monitoring_thread is not None and self._monitoring_thread.is_alive():
            return
        self._stop_monitoring.clear()
        self._monitoring_thread = threading.Thread(
            target=self._monitor_button,
            name="shutdown-button-monitor",
            daemon=True,
        )
        self._monitoring_thread.start()

    def close(self) -> None:
        self._stop_monitoring.set()
        if self._monitoring_thread is not None:
            self._monitoring_thread.join(timeout=3)
            self._monitoring_thread = None

    def _monitor_button(self) -> None:
        while not self._stop_monitoring.is_set():
            response = self._arduino.request(self._BUTTON_COMMAND)
            if response == self._PRESSED_RESPONSE:
                print("Botón físico de apagado detectado por Arduino.", flush=True)
                try:
                    self._on_pressed()
                except Exception:
                    LOGGER.exception("Unable to handle shutdown button press.")
            self._stop_monitoring.wait(self._poll_interval_seconds)