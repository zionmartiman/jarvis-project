"""Rainwater tank state storage port."""

from __future__ import annotations

from abc import ABC, abstractmethod

from jarvis.domain.tank import TankLevel


class TankStateStore(ABC):
    """Publishes the latest tank level for other processes to read."""

    @abstractmethod
    def save(self, level: TankLevel) -> None:
        raise NotImplementedError
