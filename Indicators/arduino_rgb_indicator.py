"""Physical RGB and alert-light indicator driven by the Arduino Mega."""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from pathlib import Path

from Arduino.arduino_mega_connection import ArduinoMegaConnection
from core.interfaces import AssistantStatus, StatusIndicator

LOGGER = logging.getLogger(__name__)


class ArduinoRgbIndicator(StatusIndicator):
    """Controls only the physical RGB and alert lights on the Arduino Mega."""

    _STATUS_COMMANDS = {
        AssistantStatus.WAITING: "STATE RED",
        AssistantStatus.LISTENING: "STATE GREEN",
        AssistantStatus.PROCESSING: "STATE BREATHING",
        AssistantStatus.SPEAKING: "STATE YELLOW",
    }

    def __init__(
        self,
        arduino: ArduinoMegaConnection,
        control_socket_path: Path,
    ) -> None:
        self._arduino = arduino
        self._control_socket_path = control_socket_path
        self._last_status_command: str | None = None
        self._alert_is_active: bool | None = None
        self._control_socket: socket.socket | None = None
        self._control_thread: threading.Thread | None = None
        self._stop_control_receiver = threading.Event()

    def start_control_receiver(self) -> None:
        """Accept local alert-light commands."""
        if self._control_thread is not None:
            return

        self._control_socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._control_socket_path.unlink(missing_ok=True)

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        listener.bind(str(self._control_socket_path))
        os.chmod(self._control_socket_path, 0o600)

        self._control_socket = listener
        self._stop_control_receiver.clear()
        self._control_thread = threading.Thread(
            target=self._receive_control_messages,
            name="arduino-light-control",
            daemon=True,
        )
        self._control_thread.start()

    def set_status(self, status: AssistantStatus) -> None:
        command = self._STATUS_COMMANDS[status]
        if command == self._last_status_command:
            return

        if self._send_command(command):
            self._last_status_command = command

    def set_alert_light(self, is_active: bool) -> None:
        """Set the physical red alert light."""
        if is_active == self._alert_is_active:
            return

        command = "LIGHT ALERT ON" if is_active else "LIGHT ALERT OFF"
        if self._send_command(command):
            self._alert_is_active = is_active

    def _receive_control_messages(self) -> None:
        assert self._control_socket is not None

        while not self._stop_control_receiver.is_set():
            try:
                payload, _ = self._control_socket.recvfrom(256)
            except OSError:
                if not self._stop_control_receiver.is_set():
                    LOGGER.exception("Alert-light receiver error.")
                return

            try:
                message = json.loads(payload.decode("utf-8"))
                is_active = message["alert_active"]
                if type(is_active) is not bool:
                    raise ValueError("alert_active must be boolean")
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as error:
                LOGGER.warning("Rejected alert-light command: %s", error)
                continue

            self.set_alert_light(is_active)

    def _send_command(self, command: str) -> bool:
        response = self._arduino.request(command)
        if response != "OK":
            LOGGER.warning("Unexpected Arduino Mega response: %s", response)
            return False
        return True

    def close(self) -> None:
        self._stop_control_receiver.set()
        if self._control_socket is not None:
            self._control_socket.close()
            self._control_socket = None

        if self._control_thread is not None:
            self._control_thread.join(timeout=1)
            self._control_thread = None

        self._control_socket_path.unlink(missing_ok=True)
