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
from pathlib import Path

from vosk import KaldiRecognizer, Model

from audio.microphone_stream import MicrophoneStream
from core.interfaces import SpeechRecognizer


class VoskSpeechRecognizer(SpeechRecognizer):
    """Detecta la palabra de activación y transcribe frases con Vosk."""

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

        Vosk detecta el final cuando encuentra suficiente silencio
        después de que hayas hablado. No existe un límite fijo.
        """

        recognizer = KaldiRecognizer(self._model, self._sample_rate)

        self._microphone.start_capture()

        try:
            while True:
                audio = self._microphone.read_chunk()

                if recognizer.AcceptWaveform(audio):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").strip()

                    # Vosk puede marcar un silencio sin texto como
                    # final. En ese caso continuamos esperando.
                    if text:
                        return text
        finally:
            self._microphone.stop_capture()
