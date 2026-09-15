"""Rainwater tank measurements and fill-level state provided by the Arduino Mega."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Callable

from Arduino.arduino_mega_connection import ArduinoMegaConnection

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RainwaterTankLevel:
    """One valid rainwater tank measurement."""

    distance_cm: float
    fill_percentage: int
    measured_at_unix_seconds: float


class RainwaterTankMeter:
    """Measures a rainwater tank and exposes its latest fill level."""

    EMPTY_TANK_DISTANCE_CM = 27
    FULL_TANK_DISTANCE_CM = 7.0 
    ALERT_FILL_LEVEL_CHANGE_PERCENTAGE = 5
    MINIMUM_ALERT_INTERVAL_SECONDS = 5.0

    _DISTANCE_COMMAND = "SENSOR DISTANCE"
    _DISTANCE_PREFIX = "DISTANCE_CM "

    def __init__(
        self,
        arduino: ArduinoMegaConnection,
        state_path: Path,
        on_fill_level_changed: Callable[[RainwaterTankLevel], None] | None = None,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self._arduino = arduino
        self._state_path = state_path
        self._on_fill_level_changed = on_fill_level_changed
        self._poll_interval_seconds = poll_interval_seconds
        self._latest_level: RainwaterTankLevel | None = None
        self._latest_level_lock = threading.Lock()
        self._last_announced_fill_percentage: int | None = None
        self._last_announced_at_monotonic: float | None = None
        self._polling_thread: threading.Thread | None = None
        self._stop_polling = threading.Event()

    def start_polling(self) -> None:
        """Measure and publish the tank level every polling interval."""
        if self._polling_thread is not None:
            return
        self._stop_polling.clear()
        self._polling_thread = threading.Thread(
            target=self._poll_levels,
            name="rainwater-tank-meter",
            daemon=True,
        )
        self._polling_thread.start()

    def read_level(self) -> RainwaterTankLevel | None:
        """Return one fresh tank level, constrained to 0..100 percent."""
        distance_cm = self._read_distance_cm()
        if distance_cm is None:
            return None
        return RainwaterTankLevel(
            distance_cm=distance_cm,
            fill_percentage=self._fill_percentage_for(distance_cm),
            measured_at_unix_seconds=time.time(),
        )

    def latest_level(self) -> RainwaterTankLevel | None:
        """Return the most recent valid level for in-process consumers."""
        with self._latest_level_lock:
            return self._latest_level

    def close(self) -> None:
        self._stop_polling.set()
        if self._polling_thread is not None:
            self._polling_thread.join(timeout=1)
            self._polling_thread = None

    def _read_distance_cm(self) -> float | None:
        response = self._arduino.request(self._DISTANCE_COMMAND)
        if response is None:
            return None
        if not response.startswith(self._DISTANCE_PREFIX):
            LOGGER.warning("Unexpected rainwater tank response: %s", response)
            return None
        try:
            distance_cm = float(response.removeprefix(self._DISTANCE_PREFIX))
        except ValueError:
            LOGGER.warning("Invalid rainwater tank distance: %s", response)
            return None
        if distance_cm <= 0:
            LOGGER.warning("Rainwater tank distance unavailable: %s", response)
            return None
        return distance_cm

    @classmethod
    def _fill_percentage_for(cls, distance_cm: float) -> int:
        raw_percentage = (
            (cls.EMPTY_TANK_DISTANCE_CM - distance_cm)
            / (cls.EMPTY_TANK_DISTANCE_CM - cls.FULL_TANK_DISTANCE_CM)
            * 100
        )
        return round(max(0.0, min(100.0, raw_percentage)))

    def _poll_levels(self) -> None:
        while not self._stop_polling.is_set():
            level = self.read_level()
            if level is not None:
                self._publish(level)
            self._stop_polling.wait(self._poll_interval_seconds)

    def _publish(self, level: RainwaterTankLevel) -> None:
        with self._latest_level_lock:
            self._latest_level = level
        self._write_state_file(level)
        print(
            "Rainwater tank distance: "
            f"{level.distance_cm:.1f} cm | fill level: {level.fill_percentage}%",
            flush=True,
        )
        self._notify_fill_level_change(level)

    def _write_state_file(self, level: RainwaterTankLevel) -> None:
        try:
            self._state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary_path = self._state_path.with_suffix(".tmp")
            temporary_path.write_text(
                json.dumps(asdict(level), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary_path, self._state_path)
        except OSError:
            LOGGER.exception("Unable to publish rainwater tank state.")

    def _notify_fill_level_change(self, level: RainwaterTankLevel) -> None:
        """Announce only a real five-point change, at most once every five seconds."""
        now_monotonic = time.monotonic()

        if self._last_announced_fill_percentage is None:
            self._last_announced_fill_percentage = level.fill_percentage
            self._last_announced_at_monotonic = now_monotonic
            return

        percentage_change = abs(
            level.fill_percentage - self._last_announced_fill_percentage
        )
        if percentage_change < self.ALERT_FILL_LEVEL_CHANGE_PERCENTAGE:
            return

        if (
            self._last_announced_at_monotonic is not None
            and now_monotonic - self._last_announced_at_monotonic
            < self.MINIMUM_ALERT_INTERVAL_SECONDS
        ):
            return

        if self._on_fill_level_changed is None:
            return

        try:
            self._on_fill_level_changed(level)
        except Exception:
            LOGGER.exception("Unable to announce rainwater tank level change.")
            return

        self._last_announced_fill_percentage = level.fill_percentage
        self._last_announced_at_monotonic = now_monotonic

