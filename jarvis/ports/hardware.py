"""Physical device ports: lights, buttons and the distance sensor."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from jarvis.domain.assistant_status import AssistantStatus


class StatusIndicator(ABC):
    """Shows the assistant status physically."""

    @abstractmethod
    def set_status(self, status: AssistantStatus) -> None:
        raise NotImplementedError


class AlertLight(ABC):
    """The physical light that signals a spoken alert in progress."""

    @abstractmethod
    def set_alert_active(self, is_active: bool) -> None:
        raise NotImplementedError


class ButtonPress(Enum):
    SHUTDOWN = "shutdown"
    INTERRUPT = "interrupt"


class ButtonPanel(ABC):
    """The physical buttons, polled for pending presses."""

    @abstractmethod
    def read_pending_press(self) -> ButtonPress | None:
        raise NotImplementedError


class DistanceSensor(ABC):
    """Measures the distance to the water surface."""

    @abstractmethod
    def read_distance_cm(self) -> float | None:
        """Return the distance in centimetres, or None when there is no valid reading."""
        raise NotImplementedError
