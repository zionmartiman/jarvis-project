"""Spoken announcement port."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Announcer(ABC):
    """Queues a text to be spoken by the independent announcement service."""

    @abstractmethod
    def announce(self, text: str) -> None:
        raise NotImplementedError
