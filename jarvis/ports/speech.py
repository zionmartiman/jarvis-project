"""Speech recognition and synthesis ports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class SpeechRecognizer(ABC):
    """Converts captured voice into text."""

    @abstractmethod
    def wait_for_wake_word(self) -> None:
        """Block until the wake word is detected."""
        raise NotImplementedError

    @abstractmethod
    def listen_for_sentence(self) -> str:
        """Block until a complete sentence is heard and return it."""
        raise NotImplementedError


class SpeechSynthesizer(ABC):
    """Converts text into voice and plays it through the speakers."""

    @abstractmethod
    def speak(self, text: str) -> None:
        """Synthesize and play ``text``. Blocks until it finishes."""
        raise NotImplementedError

    def interrupt(self) -> None:
        """Stop the current playback, if the synthesizer supports it."""
        return None


class PlaybackAwareSynthesizer(SpeechSynthesizer):
    """A synthesizer that reports when audio actually starts and stops playing."""

    @abstractmethod
    def speak_with_playback_callbacks(
        self,
        text: str,
        on_playback_started: Callable[[], None] | None = None,
        on_playback_finished: Callable[[], None] | None = None,
    ) -> None:
        raise NotImplementedError
