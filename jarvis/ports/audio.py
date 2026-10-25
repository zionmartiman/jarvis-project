"""Audio input port."""

from __future__ import annotations

from abc import ABC, abstractmethod


class AudioInput(ABC):
    """A source of 16-bit mono PCM audio chunks (the microphone)."""

    @abstractmethod
    def start_capture(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop_capture(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        """Discard the audio that is still pending."""
        raise NotImplementedError

    @abstractmethod
    def read_chunk(self, timeout: float | None = None) -> bytes:
        raise NotImplementedError
