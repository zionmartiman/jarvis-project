"""RGB status light of the Arduino Mega."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from jarvis.domain.assistant_status import AssistantStatus
from jarvis.infrastructure.arduino import protocol
from jarvis.ports.hardware import StatusIndicator

if TYPE_CHECKING:
    from jarvis.infrastructure.arduino.serial_connection import SerialRequester

LOGGER = logging.getLogger(__name__)

_STATUS_COMMANDS = {
    AssistantStatus.WAITING: protocol.STATE_RED,
    AssistantStatus.LISTENING: protocol.STATE_GREEN,
    AssistantStatus.PROCESSING: protocol.STATE_BREATHING,
    AssistantStatus.SPEAKING: protocol.STATE_YELLOW,
}


class ArduinoStatusLight(StatusIndicator):
    """Shows the assistant status on the RGB light, skipping repeated commands."""

    def __init__(self, arduino: SerialRequester) -> None:
        self._arduino = arduino
        self._last_command: str | None = None

    def set_status(self, status: AssistantStatus) -> None:
        command = _STATUS_COMMANDS[status]
        if command == self._last_command:
            return

        response = self._arduino.request(command)
        if response != protocol.OK:
            LOGGER.warning("Unexpected Arduino Mega response: %s", response)
            return
        self._last_command = command
