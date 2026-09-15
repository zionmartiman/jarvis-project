"""Thread-safe serial connection to the Arduino Mega."""

from __future__ import annotations

import logging
import threading
import time

import serial

LOGGER = logging.getLogger(__name__)


class ArduinoMegaConnection:
    """Owns the single USB serial connection to the Arduino Mega."""

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
        self._serial_lock = threading.Lock()

    def connect(self) -> None:
        """Open the USB serial connection once."""
        with self._serial_lock:
            self._ensure_connected()

    def request(self, command: str) -> str | None:
        """Send one line command and return its one line response."""
        try:
            with self._serial_lock:
                self._ensure_connected()
                if self._serial is None:
                    return None

                self._serial.write(f"{command}\n".encode("ascii"))
                self._serial.flush()
                return self._serial.readline().decode(
                    "ascii",
                    errors="replace",
                ).strip()
        except (serial.SerialException, OSError) as error:
            LOGGER.warning("Arduino Mega communication error: %s", error)
            self._close_serial()
            return None

    def close(self) -> None:
        with self._serial_lock:
            self._close_serial()

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
        except (serial.SerialException, OSError) as error:
            LOGGER.warning("Arduino Mega unavailable: %s", error)
            self._close_serial()

    def _close_serial(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None
