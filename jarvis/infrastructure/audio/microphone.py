"""USB microphone capture through sounddevice."""

from __future__ import annotations

import logging
import queue
import threading

import sounddevice as sd

from jarvis.ports.audio import AudioInput

LOGGER = logging.getLogger(__name__)


class SoundDeviceMicrophone(AudioInput):
    """Buffers microphone audio in a bounded queue and serves it chunk by chunk."""

    def __init__(
        self,
        sample_rate: int,
        device: int | str,
        block_size: int = 8000,
        queue_max_size: int = 32,
    ) -> None:
        self._sample_rate = sample_rate
        self._device = device
        self._block_size = block_size

        # The queue is bounded so it never grows indefinitely.
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=queue_max_size)

        # While Jarvis thinks or speaks its own voice must not be recorded:
        # audio is kept only while someone is meant to listen.
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
            LOGGER.warning("Microphone status: %s", status)

        if not self._capture_enabled.is_set():
            return

        audio = bytes(indata)

        try:
            self._queue.put_nowait(audio)
        except queue.Full:
            # Recent audio is worth more than old audio: drop the oldest chunk.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self._queue.put_nowait(audio)
            except queue.Full:
                pass

    def clear(self) -> None:
        """Discard audio that is still pending."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def start_capture(self) -> None:
        self.clear()
        self._capture_enabled.set()

    def stop_capture(self) -> None:
        """Stop capturing and discard the pending audio."""
        self._capture_enabled.clear()
        self.clear()

    def read_chunk(self, timeout: float | None = None) -> bytes:
        """Block until a chunk is available; raises ``queue.Empty`` on timeout."""
        return self._queue.get(timeout=timeout)

    def __enter__(self) -> SoundDeviceMicrophone:
        self._stream.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._stream.__exit__(exc_type, exc_value, traceback)
