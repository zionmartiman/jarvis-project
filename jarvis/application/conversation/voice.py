"""Everything Jarvis says out loud goes through here."""

from __future__ import annotations

import logging
import threading

from jarvis.domain.assistant_status import AssistantStatus
from jarvis.ports.audio import AudioInput
from jarvis.ports.hardware import StatusIndicator
from jarvis.ports.speech import SpeechSynthesizer

LOGGER = logging.getLogger(__name__)

_LOCK_POLL_SECONDS = 0.05


class Voice:
    """Speaks one text at a time, with the SPEAKING status and the microphone muted."""

    def __init__(
        self,
        synthesizer: SpeechSynthesizer,
        microphone: AudioInput,
        status: StatusIndicator,
        shutting_down: threading.Event,
    ) -> None:
        self._synthesizer = synthesizer
        self._microphone = microphone
        self._status = status
        self._shutting_down = shutting_down
        self._lock = threading.Lock()

    def say(self, text: str) -> None:
        """Speak ``text`` and block until done; silent once the system is shutting down."""
        if self._shutting_down.is_set():
            return
        with self._lock:
            if self._shutting_down.is_set():
                return
            self._status.set_status(AssistantStatus.SPEAKING)
            self._microphone.stop_capture()
            try:
                self._synthesizer.speak(text)
            except Exception:
                if not self._shutting_down.is_set():
                    raise

    def interrupt(self) -> None:
        """Cut the current playback; a failing synthesizer is only logged."""
        try:
            self._synthesizer.interrupt()
        except Exception as error:
            LOGGER.error("Unable to interrupt the voice: %s", error)

    def say_last_words(self, text: str) -> None:
        """Take the speaker from whoever is talking and speak ``text`` even while shutting down."""
        while not self._lock.acquire(timeout=_LOCK_POLL_SECONDS):
            self.interrupt()
        try:
            self._synthesizer.interrupt()
            self._status.set_status(AssistantStatus.SPEAKING)
            self._synthesizer.speak(text)
        except Exception as error:
            LOGGER.error("Unable to play the shutdown announcement: %s", error)
        finally:
            self._lock.release()
