"""
Reconocimiento de voz local con Vosk.

Implementa la interfaz SpeechRecognizer. Todo el procesamiento ocurre
en la Raspberry; el audio nunca sale a Internet en esta fase.

Para cambiar de motor de reconocimiento (un servicio en la nube, u
otro motor local), crea una clase que implemente SpeechRecognizer y
sustitúyela en main.py.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from vosk import KaldiRecognizer, Model

from audio.microphone_stream import MicrophoneStream
from core.interfaces import SpeechRecognizer


class VoskSpeechRecognizer(SpeechRecognizer):
    """Detecta la palabra de activación y transcribe frases con Vosk."""

    # Margen adicional tras el final de frase detectado por Vosk. Si la
    # persona retoma la frase dentro de este tiempo, Jarvis sigue escuchando.
    _CONTINUATION_GRACE_SECONDS = 1.0

    def __init__(
        self,
        microphone: MicrophoneStream,
        model_path: Path,
        sample_rate: int,
        wake_word: str = "jarvis",
    ):
        self._microphone = microphone
        self._sample_rate = sample_rate
        self._wake_word = wake_word.lower()

        print(f"Cargando modelo local: {model_path}", flush=True)
        self._model = Model(str(model_path))

    def wait_for_wake_word(self) -> None:
        """
        Escucha únicamente la palabra de activación.

        El audio se procesa localmente y no sale de la Raspberry.
        """

        recognizer = KaldiRecognizer(
            self._model,
            self._sample_rate,
            f'["{self._wake_word}", "[unk]"]',
        )

        self._microphone.start_capture()

        try:
            while True:
                audio = self._microphone.read_chunk()

                if recognizer.AcceptWaveform(audio):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").lower()

                    if self._wake_word in text:
                        return
        finally:
            self._microphone.stop_capture()

    def listen_for_sentence(self) -> str:
        """
        Escucha una frase completa.

        Vosk detecta un posible final tras un silencio. Conservamos un
        pequeño margen adicional para que una pausa natural al hablar no
        envíe la instrucción antes de tiempo.
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

                    # Vosk puede marcar un silencio sin texto como final.
                    # Solo iniciamos la espera adicional después de haber
                    # reconocido al menos un fragmento de la instrucción.
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
