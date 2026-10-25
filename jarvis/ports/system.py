"""Operating system port."""

from __future__ import annotations

from abc import ABC, abstractmethod


class PowerController(ABC):
    """Privileged power actions on the host."""

    @abstractmethod
    def shutdown(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def reboot(self) -> None:
        raise NotImplementedError
