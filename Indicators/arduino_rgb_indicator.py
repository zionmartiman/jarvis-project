"""Adaptador serie y receptor local para las luces físicas del Mega."""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from pathlib import Path

import serial

from core.interfaces import AssistantStatus, StatusIndicator

LOGGER = logging.getLogger(__name__)


class ArduinoRgbIndicator(StatusIndicator):
    """Controla el Mega y recibe órdenes locales para la luz de alerta."""

    _STATUS_COMMANDS = {
        AssistantStatus.WAITING: "STATE RED",
        AssistantStatus.LISTENING: "STATE GREEN",
        AssistantStatus.PROCESSING: "STATE BREATHING",
        AssistantStatus.SPEAKING: "STATE YELLOW",
    }

    def __init__(
        self,
        port: str,
        baudrate: int,
        control_socket_path: Path,
        timeout_seconds: float = 2.0,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._control_socket_path = control_socket_path
        self._timeout_seconds = timeout_seconds
        self._serial: serial.Serial | None = None
        self._last_status_command: str | None = None
        self._alert_is_active: bool | None = None
        self._serial_lock = threading.Lock()
        self._control_socket: socket.socket | None = None
        self._control_thread: threading.Thread | None = None
        self._stop_control_receiver = threading.Event()

    def connect(self) -> None:
        """Abre el USB-serie una vez; el Mega se reinicia al abrirlo."""
        with self._serial_lock:
            self._ensure_connected()

    def start_control_receiver(self) -> None:
        """Acepta órdenes locales sin compartir el USB-serie con otro proceso."""
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
        """Activa o desactiva el LED rojo físico de alerta."""
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
                    LOGGER.exception("Error en el receptor de luz de alerta.")
                return

            try:
                message = json.loads(payload.decode("utf-8"))
                is_active = message["alert_active"]
                if type(is_active) is not bool:
                    raise ValueError("alert_active debe ser booleano.")
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as error:
                LOGGER.warning("Orden de luz de alerta rechazada: %s", error)
                continue

            self.set_alert_light(is_active)

    def _send_command(self, command: str) -> bool:
        try:
            with self._serial_lock:
                self._ensure_connected()
                if self._serial is None:
                    return False

                self._serial.write(f"{command}\n".encode("ascii"))
                self._serial.flush()

                response = self._serial.readline().decode(
                    "ascii",
                    errors="replace",
                ).strip()

            if response != "OK":
                LOGGER.warning("Respuesta inesperada del Mega: %s", response)
                return False

            return True
        except (serial.SerialException, OSError) as error:
            LOGGER.warning("Error comunicando con el Mega: %s", error)
            self._close_serial()
            return False

    def _ensure_connected(self) -> None:
        if self._serial is not None and self._serial.is_open:
            return

        try:
            self._serial = serial.Serial(
                self._port,
                self._baudrate,
                timeout=self._timeout_seconds,
                write_timeout=self._timeout_seconds,
            )
            time.sleep(2)
            self._serial.reset_input_buffer()
            self._last_status_command = None
            self._alert_is_active = None
        except (serial.SerialException, OSError) as error:
            LOGGER.warning("Arduino no disponible: %s", error)
            self._close_serial()

    def _close_serial(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None
        self._last_status_command = None
        self._alert_is_active = None

    def close(self) -> None:
        self._stop_control_receiver.set()

        if self._control_socket is not None:
            self._control_socket.close()
            self._control_socket = None

        if self._control_thread is not None:
            self._control_thread.join(timeout=1)
            self._control_thread = None

        self._control_socket_path.unlink(missing_ok=True)

        with self._serial_lock:
            self._close_serial()
