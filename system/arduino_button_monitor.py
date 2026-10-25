"""Legacy facade over ButtonMonitor, kept until the old entry point is retired."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from jarvis.application.button_monitor import ButtonMonitor
from jarvis.infrastructure.arduino.button_panel import ArduinoButtonPanel
from jarvis.ports.hardware import ButtonPress

if TYPE_CHECKING:
    from jarvis.infrastructure.arduino.serial_connection import SerialRequester


class ArduinoButtonMonitor:
    """Polls button status and dispatches shutdown and reply-interrupt presses."""

    def __init__(
        self,
        arduino: SerialRequester,
        on_shutdown_pressed: Callable[[], None],
        on_response_interrupt_pressed: Callable[[], None],
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self._monitor = ButtonMonitor(
            panel=ArduinoButtonPanel(arduino),
            handlers={
                ButtonPress.SHUTDOWN: on_shutdown_pressed,
                ButtonPress.INTERRUPT: on_response_interrupt_pressed,
            },
            poll_interval_seconds=poll_interval_seconds,
        )

    def start(self) -> None:
        self._monitor.start()

    def close(self) -> None:
        self._monitor.close()
