"""Physical RGB and alert-light indicator driven by the Arduino Mega.

Legacy facade over the jarvis.infrastructure adapters; it disappears in phase 6 when
main.py builds those adapters directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from core.interfaces import AssistantStatus, StatusIndicator
from jarvis.infrastructure.arduino.alert_light import ArduinoAlertLight
from jarvis.infrastructure.arduino.status_light import ArduinoStatusLight
from jarvis.infrastructure.ipc.alert_light_server import AlertLightControlServer

if TYPE_CHECKING:
    from jarvis.infrastructure.arduino.serial_connection import SerialRequester


class ArduinoRgbIndicator(StatusIndicator):
    """Controls only the physical RGB and alert lights on the Arduino Mega."""

    def __init__(
        self,
        arduino: SerialRequester,
        control_socket_path: Path,
    ) -> None:
        self._status_light = ArduinoStatusLight(arduino)
        self._alert_light = ArduinoAlertLight(arduino)
        self._control_server = AlertLightControlServer(self._alert_light, control_socket_path)

    def start_control_receiver(self) -> None:
        """Accept local alert-light commands."""
        self._control_server.start()

    def set_status(self, status: AssistantStatus) -> None:
        self._status_light.set_status(status)

    def set_alert_light(self, is_active: bool) -> None:
        """Set the physical red alert light."""
        self._alert_light.set_alert_active(is_active)

    def close(self) -> None:
        self._control_server.close()
