"""Polls the distance sensor and turns each reading into a published tank level."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from jarvis.application.periodic_task import PeriodicTask
from jarvis.domain.tank import TankAlertPolicy, TankCalibration, TankLevel
from jarvis.ports.hardware import DistanceSensor
from jarvis.ports.tank import TankStateStore

LOGGER = logging.getLogger(__name__)


class TankMonitor:
    """Reads the sensor, stores the latest level and lets the alert policy decide what to say."""

    def __init__(
        self,
        sensor: DistanceSensor,
        calibration: TankCalibration,
        store: TankStateStore,
        alert_policy: TankAlertPolicy,
        poll_interval_seconds: float,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._sensor = sensor
        self._calibration = calibration
        self._store = store
        self._alert_policy = alert_policy
        self._wall_clock = wall_clock
        self._latest_level: TankLevel | None = None
        self._latest_level_lock = threading.Lock()
        self._has_logged_first_level = False
        self._task = PeriodicTask("rainwater-tank-meter", poll_interval_seconds, self.poll_once)

    def start(self) -> None:
        """Measure and publish the tank level every polling interval."""
        self._task.start()

    def close(self) -> None:
        self._task.close(timeout=1.0)

    def latest_level(self) -> TankLevel | None:
        """Return the most recent valid level for in-process consumers."""
        with self._latest_level_lock:
            return self._latest_level

    def poll_once(self) -> None:
        """Take one measurement; invalid readings are skipped."""
        distance_cm = self._sensor.read_distance_cm()
        if distance_cm is None:
            return
        self.publish(
            TankLevel(
                distance_cm=distance_cm,
                fill_percentage=self._calibration.fill_percentage(distance_cm),
                measured_at_unix_seconds=self._wall_clock(),
            )
        )

    def publish(self, level: TankLevel) -> None:
        """Make ``level`` the latest one, persist it and let the alert policy observe it."""
        with self._latest_level_lock:
            self._latest_level = level
        self._store.save(level)
        if not self._has_logged_first_level:
            self._has_logged_first_level = True
            LOGGER.info(
                "Rainwater tank distance: %.1f cm | fill level: %d%%",
                level.distance_cm,
                level.fill_percentage,
            )
        self._alert_policy.observe(level)
