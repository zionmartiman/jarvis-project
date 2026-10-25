"""Legacy facade over TankMonitor, kept until the old entry point is retired."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from jarvis.application.tank_monitor import TankMonitor
from jarvis.config.settings import TankSettings
from jarvis.domain.tank import TankAlertPolicy, TankCalibration, TankLevel, TankStatus
from jarvis.infrastructure.arduino.distance_sensor import ArduinoDistanceSensor
from jarvis.infrastructure.tank.state_file import JsonTankStateFile

if TYPE_CHECKING:
    from jarvis.infrastructure.arduino.serial_connection import SerialRequester

RainwaterTankLevel = TankLevel


class RainwaterTankMeter:
    """Measures a rainwater tank and publishes its current fill level."""

    def __init__(
        self,
        arduino: SerialRequester,
        state_path: Path,
        on_fill_level_changed: Callable[[RainwaterTankLevel], None] | None = None,
        on_fill_level_status_changed: (
            Callable[[RainwaterTankLevel, str], None] | None
        ) = None,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self._on_fill_level_changed = on_fill_level_changed
        self._on_fill_level_status_changed = on_fill_level_status_changed
        defaults = TankSettings(state_path=state_path)
        self._monitor = TankMonitor(
            sensor=ArduinoDistanceSensor(arduino),
            calibration=TankCalibration(defaults.empty_distance_cm, defaults.full_distance_cm),
            store=JsonTankStateFile(state_path),
            alert_policy=TankAlertPolicy(
                min_change_percentage=defaults.min_change_percentage,
                min_interval_seconds=defaults.min_alert_interval_seconds,
                on_level_change=self._level_changed,
                on_status_change=self._status_changed,
                clock=lambda: time.monotonic(),
            ),
            poll_interval_seconds=poll_interval_seconds,
        )

    def start_polling(self) -> None:
        self._monitor.start()

    def latest_level(self) -> RainwaterTankLevel | None:
        return self._monitor.latest_level()

    def close(self) -> None:
        self._monitor.close()

    def _level_changed(self, level: TankLevel) -> None:
        if self._on_fill_level_changed is not None:
            self._on_fill_level_changed(level)

    def _status_changed(self, level: TankLevel, status: TankStatus) -> None:
        if self._on_fill_level_status_changed is not None:
            self._on_fill_level_status_changed(level, status.value)
