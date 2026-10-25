"""Physical buttons of the Arduino Mega."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jarvis.infrastructure.arduino import protocol
from jarvis.ports.hardware import ButtonPanel, ButtonPress

if TYPE_CHECKING:
    from jarvis.infrastructure.arduino.serial_connection import SerialRequester

_PRESSES = {
    protocol.BUTTON_SHUTDOWN: ButtonPress.SHUTDOWN,
    protocol.BUTTON_INTERRUPT: ButtonPress.INTERRUPT,
}


class ArduinoButtonPanel(ButtonPanel):
    """Asks the Arduino whether a button was pressed since the last query."""

    def __init__(self, arduino: SerialRequester) -> None:
        self._arduino = arduino

    def read_pending_press(self) -> ButtonPress | None:
        response = self._arduino.request(protocol.BUTTON_STATUS)
        return _PRESSES.get(response) if response is not None else None
