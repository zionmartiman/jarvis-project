from __future__ import annotations

import logging
import time
import serial

from core.interfaces import AssistantStatus, StatusIndicator

LOGGER = logging.getLogger(__name__)


class ArduinoRgbIndicator(StatusIndicator):
    """Adaptador USB-serie entre el estado de Jarvis y el LED del Mega."""

    _COMMANDS = {
        AssistantStatus.WAITING: "STATE RED",
        AssistantStatus.LISTENING: "STATE GREEN",
        AssistantStatus.PROCESSING: "STATE BREATHING",
        AssistantStatus.SPEAKING: "STATE YELLOW",
    }

    def __init__(
        self,
        port: str,
        baudrate: int,
        timeout_seconds: float = 2.0,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout_seconds = timeout_seconds
        self._serial: serial.Serial | None = None
        self._last_command: str | None = None

    def connect(self) -> None:
        """Abre el USB-serie una vez, antes de arrancar la conversación."""
        try:
            self._serial = serial.Serial(
                self._port,
                self._baudrate,
                timeout=self._timeout_seconds,
                write_timeout=self._timeout_seconds,
            )

            # El Mega se reinicia al abrir USB-serie.
            time.sleep(2)
            self._serial.reset_input_buffer()

        except (serial.SerialException, OSError) as error:
            LOGGER.warning("Arduino no disponible: %s", error)
            self.close()

    def set_status(self, status: AssistantStatus) -> None:
        command = self._COMMANDS[status]

        if command == self._last_command:
            return

        try:
            if self._serial is None or not self._serial.is_open:
                self.connect()

            if self._serial is None:
                return

            self._serial.write(f"{command}\n".encode("ascii"))
            self._serial.flush()

            response = self._serial.readline().decode(
                "ascii",
                errors="replace",
            ).strip()

            if response != "OK":
                LOGGER.warning("Respuesta inesperada del Mega: %s", response)

            self._last_command = command

        except (serial.SerialException, OSError) as error:
            LOGGER.warning("Error comunicando con el Mega: %s", error)
            self.close()

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None
        self._last_command = None