"""Local speech recognition with Vosk. Audio never leaves the Raspberry Pi."""

from __future__ import annotations

import json
import logging
import queue
import time
from pathlib import Path

from vosk import KaldiRecognizer, Model

from jarvis.ports.audio import AudioInput
from jarvis.ports.speech import SpeechRecognizer

LOGGER = logging.getLogger(__name__)


class VoskSpeechRecognizer(SpeechRecognizer):
    """Detects the wake word and transcribes sentences with Vosk."""

    # Extra margin after Vosk detects the end of a sentence. If the person resumes
    # within it, Jarvis keeps listening.
    _CONTINUATION_GRACE_SECONDS = 1.0

    def __init__(
        self,
        microphone: AudioInput,
        model_path: Path,
        sample_rate: int,
        wake_word: str = "jarvis",
    ) -> None:
        self._microphone = microphone
        self._sample_rate = sample_rate
        self._wake_word = wake_word.lower()

        LOGGER.info("Loading local speech model: %s", model_path)
        self._model = Model(str(model_path))

    def wait_for_wake_word(self) -> None:
        """Listen only for the wake word; the audio is processed locally."""
        recognizer = KaldiRecognizer(
            self._model,
            self._sample_rate,
            f'["{self._wake_word}", "[unk]"]',
        )

        self._microphone.start_capture()

        try:
            while True:
                try:
                    audio = self._microphone.read_chunk(timeout=0.2)
                except queue.Empty:
                    continue

                if recognizer.AcceptWaveform(audio):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").lower()

                    if self._wake_word in text:
                        return
        finally:
            self._microphone.stop_capture()

    def listen_for_sentence(self) -> str:
        """Listen for a complete sentence.

        Vosk detects a possible end after a silence. A small extra margin keeps a
        natural pause from sending the instruction too early.
        """
        recognizer = KaldiRecognizer(self._model, self._sample_rate)
        segments: list[str] = []
        silence_started_at: float | None = None

        self._microphone.start_capture()

        try:
            while True:
                audio = self._microphone.read_chunk()
                now = time.monotonic()

                if recognizer.AcceptWaveform(audio):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").strip()

                    # Vosk may mark a silence without text as final. The extra wait
                    # starts only after at least one fragment of the instruction.
                    if text:
                        segments.append(text)
                        silence_started_at = now

                else:
                    partial = json.loads(recognizer.PartialResult())
                    if partial.get("partial", "").strip():
                        # Only nonempty speech resets the silence timer.
                        silence_started_at = None

                if (
                    segments
                    and silence_started_at is not None
                    and now - silence_started_at
                    >= self._CONTINUATION_GRACE_SECONDS
                ):
                    return " ".join(segments)
        finally:
            self._microphone.stop_capture()
