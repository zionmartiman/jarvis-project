"""Rainwater tank rules: levels, calibration and the policy that decides what to announce."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

LOGGER = logging.getLogger(__name__)

# Fill percentages that trigger a status announcement.
_FULL = 100
_NEARLY_FULL = 90
_GOOD = 80
_LOW = 20
_VERY_LOW = 10
_EMPTY = 5
# A status is armed again only after the level moves this far from its threshold.
_REARM_MARGIN = 3


@dataclass(frozen=True)
class TankLevel:
    """One valid tank measurement. Field names are part of the JSON file and the API."""

    distance_cm: float
    fill_percentage: int
    measured_at_unix_seconds: float


@dataclass(frozen=True)
class TankCalibration:
    """Sensor distances that correspond to an empty and to a full tank."""

    empty_distance_cm: float
    full_distance_cm: float

    def fill_percentage(self, distance_cm: float) -> int:
        """Linear fill level between the two distances, rounded and limited to 0..100."""
        raw_percentage = (
            (self.empty_distance_cm - distance_cm)
            / (self.empty_distance_cm - self.full_distance_cm)
            * 100
        )
        return round(max(0.0, min(100.0, raw_percentage)))


class TankStatus(str, Enum):
    FULL = "full"
    NEARLY_FULL = "nearly_full"
    GOOD = "good"
    LOW = "low"
    VERY_LOW = "very_low"
    EMPTY = "empty"


class TankAlertPolicy:
    """Decides when a new level is worth announcing: percentage changes and status crossings."""

    def __init__(
        self,
        min_change_percentage: int,
        min_interval_seconds: float,
        on_level_change: Callable[[TankLevel], None],
        on_status_change: Callable[[TankLevel, TankStatus], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_change_percentage = min_change_percentage
        self._min_interval_seconds = min_interval_seconds
        self._on_level_change = on_level_change
        self._on_status_change = on_status_change
        self._clock = clock
        self._last_announced_fill_percentage: int | None = None
        self._last_level_change_at: float | None = None
        self._previous_fill_percentage: int | None = None
        self._announced_statuses: set[TankStatus] = set()
        self._has_observed_first_level = False

    def observe(self, level: TankLevel) -> None:
        """Notify percentage changes and only directional status threshold crossings."""
        previous_percentage = self._previous_fill_percentage

        if not self._has_observed_first_level:
            self._has_observed_first_level = True
            self._last_announced_fill_percentage = level.fill_percentage
            self._previous_fill_percentage = level.fill_percentage
            return

        if previous_percentage is None:
            self._previous_fill_percentage = level.fill_percentage
            return

        self._notify_level_change(level)
        self._notify_status_transition(previous_percentage, level)
        self._previous_fill_percentage = level.fill_percentage

    def _notify_level_change(self, level: TankLevel) -> None:
        last_percentage = self._last_announced_fill_percentage
        if last_percentage is None:
            self._last_announced_fill_percentage = level.fill_percentage
            return

        if abs(level.fill_percentage - last_percentage) < self._min_change_percentage:
            return

        now = self._clock()
        if (
            self._last_level_change_at is not None
            and now - self._last_level_change_at < self._min_interval_seconds
        ):
            return

        try:
            self._on_level_change(level)
        except Exception:
            LOGGER.exception("Unable to announce rainwater tank level change.")
            return

        self._last_announced_fill_percentage = level.fill_percentage
        self._last_level_change_at = now

    def _notify_status_transition(self, previous_percentage: int, level: TankLevel) -> None:
        """Notify each directional status once, with hysteresis against sensor noise."""
        current_percentage = level.fill_percentage
        self._rearm_statuses(current_percentage)

        status: TankStatus | None = None
        if current_percentage > previous_percentage:
            if previous_percentage < _FULL <= current_percentage:
                status = TankStatus.FULL
            elif previous_percentage < _NEARLY_FULL <= current_percentage:
                status = TankStatus.NEARLY_FULL
            elif previous_percentage < _GOOD <= current_percentage:
                status = TankStatus.GOOD
        elif current_percentage < previous_percentage:
            if previous_percentage >= _EMPTY > current_percentage:
                status = TankStatus.EMPTY
            elif previous_percentage > _VERY_LOW >= current_percentage:
                status = TankStatus.VERY_LOW
            elif previous_percentage > _LOW >= current_percentage:
                status = TankStatus.LOW

        if status is None or status in self._announced_statuses:
            return

        try:
            self._on_status_change(level, status)
        except Exception:
            LOGGER.exception("Unable to announce rainwater tank status transition.")
            return
        self._announced_statuses.add(status)

    def _rearm_statuses(self, fill_percentage: int) -> None:
        """Rearm a status only after leaving its threshold by the rearm margin."""
        if fill_percentage >= _LOW + _REARM_MARGIN:
            self._announced_statuses.discard(TankStatus.LOW)
        if fill_percentage >= _VERY_LOW + _REARM_MARGIN:
            self._announced_statuses.discard(TankStatus.VERY_LOW)
        if fill_percentage >= _EMPTY + _REARM_MARGIN:
            self._announced_statuses.discard(TankStatus.EMPTY)
        if fill_percentage <= _GOOD - _REARM_MARGIN:
            self._announced_statuses.discard(TankStatus.GOOD)
        if fill_percentage <= _NEARLY_FULL - _REARM_MARGIN:
            self._announced_statuses.discard(TankStatus.NEARLY_FULL)
        if fill_percentage <= _FULL - _REARM_MARGIN:
            self._announced_statuses.discard(TankStatus.FULL)
