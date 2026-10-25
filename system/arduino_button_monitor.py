"""Monitors physical Arduino buttons independently of tank measurements."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from jarvis.infrastructure.arduino.button_panel import ArduinoButtonPanel
from jarvis.ports.hardware import ButtonPress

if TYPE_CHECKING:
    from jarvis.infrastructure.arduino.serial_connection import SerialRequester

LOGGER = logging.getLogger(__name__)


class ArduinoButtonMonitor:
    """Polls button status and dispatches shutdown and reply-interrupt presses."""

    def __init__(
        self,
        arduino: SerialRequester,
        on_shutdown_pressed: Callable[[], None],
        on_response_interrupt_pressed: Callable[[], None],
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self._panel = ArduinoButtonPanel(arduino)
        self._on_shutdown_pressed = on_shutdown_pressed
        self._on_response_interrupt_pressed = on_response_interrupt_pressed
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_monitoring = threading.Event()
        self._monitoring_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._monitoring_thread is not None and self._monitoring_thread.is_alive():
            return
        self._stop_monitoring.clear()
        self._monitoring_thread = threading.Thread(
            target=self._monitor_buttons,
            name="arduino-button-monitor",
            daemon=True,
        )
        self._monitoring_thread.start()

    def close(self) -> None:
        self._stop_monitoring.set()
        if self._monitoring_thread is not None:
            self._monitoring_thread.join(timeout=3)
            self._monitoring_thread = None

    def _monitor_buttons(self) -> None:
        while not self._stop_monitoring.is_set():
            press = self._panel.read_pending_press()
            callback = None
            if press is ButtonPress.SHUTDOWN:
                print("Botón físico de apagado detectado por Arduino.", flush=True)
                callback = self._on_shutdown_pressed
            elif press is ButtonPress.INTERRUPT:
                print("Botón para interrumpir la respuesta detectado por Arduino.", flush=True)
                callback = self._on_response_interrupt_pressed

            if callback is not None:
                try:
                    callback()
                except Exception:
                    LOGGER.exception("Unable to handle Arduino button press.")

            self._stop_monitoring.wait(self._poll_interval_seconds)
