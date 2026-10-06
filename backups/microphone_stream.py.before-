"""
Captura de audio del micrófono.

Encapsula sounddevice y la cola de audio en una sola clase, en lugar
de usar variables globales como en el fichero original. Cualquier
SpeechRecognizer recibe una instancia de MicrophoneStream y lee
fragmentos de audio con read_chunk(), sin saber nada de sounddevice.
"""

from __future__ import annotations

import queue
import sys
import threading

import sounddevice as sd


class MicrophoneStream:
    """
    Envuelve sounddevice.RawInputStream.

    sounddevice entrega continuamente fragmentos de audio mediante una
    función callback interna. Esta clase los coloca en una cola y
    expone un método bloqueante (read_chunk) para consumirlos.
    """

    def __init__(
        self,
        sample_rate: int,
        device,
        block_size: int = 8000,
        queue_max_size: int = 32,
    ):
        self._sample_rate = sample_rate
        self._device = device
        self._block_size = block_size

        # Se limita el tamaño para que nunca crezca indefinidamente.
        self._queue: queue.Queue = queue.Queue(maxsize=queue_max_size)

        # Mientras Jarvis piensa o habla, no queremos guardar el audio
        # del micrófono. Solo se activa cuando alguien debe escuchar.
        self._capture_enabled = threading.Event()

        self._stream = sd.RawInputStream(
            samplerate=self._sample_rate,
            blocksize=self._block_size,
            device=self._device,
            dtype="int16",
            channels=1,
            callback=self._on_audio,
        )

    def _on_audio(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"Estado del micrófono: {status}", file=sys.stderr)

        if not self._capture_enabled.is_set():
            return

        audio = bytes(indata)

        try:
            self._queue.put_nowait(audio)
        except queue.Full:
            # Si la cola se llena, eliminamos el fragmento más antiguo.
            # Es preferible mantener audio reciente.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self._queue.put_nowait(audio)
            except queue.Full:
                pass

    def clear(self) -> None:
        """Elimina audio antiguo que pudiera quedar pendiente."""

        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def start_capture(self) -> None:
        """Prepara y activa la captura del micrófono."""

        self.clear()
        self._capture_enabled.set()

    def stop_capture(self) -> None:
        """Detiene la captura lógica y descarta el audio pendiente."""

        self._capture_enabled.clear()
        self.clear()

    def read_chunk(self) -> bytes:
        """Bloquea hasta que haya un fragmento de audio disponible."""

        return self._queue.get()

    def __enter__(self) -> "MicrophoneStream":
        self._stream.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._stream.__exit__(exc_type, exc_value, traceback)
