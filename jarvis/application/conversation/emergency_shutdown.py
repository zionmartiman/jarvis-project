"""The master shutdown button: say goodbye and power off, whatever Jarvis is doing."""

from __future__ import annotations

import logging
import threading

from jarvis.application.conversation.voice import Voice
from jarvis.domain import phrases
from jarvis.ports.audio import AudioInput
from jarvis.ports.system import PowerController

LOGGER = logging.getLogger(__name__)


class EmergencyShutdown:
    """Silences Jarvis, announces the shutdown and powers the host off, once."""

    def __init__(
        self,
        voice: Voice,
        microphone: AudioInput,
        power_controller: PowerController,
        shutting_down: threading.Event,
    ) -> None:
        self._voice = voice
        self._microphone = microphone
        self._power_controller = power_controller
        self._shutting_down = shutting_down
        self._lock = threading.Lock()

    def trigger(self) -> None:
        """Start the shutdown in its own thread; later calls do nothing."""
        with self._lock:
            if self._shutting_down.is_set():
                return
            self._shutting_down.set()
        threading.Thread(target=self._run, name="emergency-shutdown", daemon=True).start()

    def _run(self) -> None:
        LOGGER.info("Shutdown button: interrupting Jarvis and powering off.")
        self._microphone.stop_capture()
        self._voice.say_last_words(phrases.EMERGENCY_SHUTDOWN)
        try:
            self._power_controller.shutdown()
        except Exception as error:
            LOGGER.error("Unable to power off the system: %s", error)
