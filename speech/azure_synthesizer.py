"""Azure Speech implementation shared by replies and incoming announcements."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import azure.cognitiveservices.speech as speechsdk

from audio.player import PlaybackLock, RawPcmPlayer
from config.settings import AzureCredentials
from core.interfaces import SpeechSynthesizer

LOGGER = logging.getLogger(__name__)


class _AzureStreamAdapter(speechsdk.audio.PushAudioOutputStreamCallback):
    """Streams Azure PCM fragments to the generic player."""

    def __init__(self, player: RawPcmPlayer):
        super().__init__()
        self._player = player

    def write(self, audio_buffer) -> int:
        self._player.write(audio_buffer)
        return audio_buffer.nbytes

    def close(self) -> None:
        self._player.close()


class AzureSpeechSynthesizer(SpeechSynthesizer):
    """Converts text into Azure Speech and plays it through ALSA."""

    def __init__(
        self,
        credentials: AzureCredentials,
        voice_name: str,
        output_device: str,
    ):
        self._output_device = output_device
        self._active_lock = threading.Lock()
        self._active_generation = 0
        self._active_player: RawPcmPlayer | None = None
        self._active_synthesizer = None
        self._speech_config = speechsdk.SpeechConfig(
            subscription=credentials.key,
            region=credentials.region,
        )
        self._speech_config.speech_synthesis_voice_name = voice_name
        self._speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm
        )

    def speak(self, text: str) -> None:
        self.speak_with_playback_callbacks(text)

    def interrupt(self) -> None:
        """Stop current Azure synthesis and terminate its active audio player."""
        with self._active_lock:
            self._active_generation += 1
            player = self._active_player
            synthesizer = self._active_synthesizer

        if player is not None:
            player.interrupt()
        if synthesizer is not None:
            synthesizer.stop_speaking_async().get()

    def speak_with_playback_callbacks(
        self,
        text: str,
        on_playback_started: Callable[[], None] | None = None,
        on_playback_finished: Callable[[], None] | None = None,
    ) -> None:
        """Reproduce texto y notifica solo durante la reproducción real."""
        text = text.strip()
        if not text:
            return

        with PlaybackLock():
            self._run_callback(on_playback_started)
            try:
                self._speak_while_locked(text)
            finally:
                self._run_callback(on_playback_finished)

    def _speak_while_locked(self, text: str) -> None:
        with self._active_lock:
            generation = self._active_generation

        player = RawPcmPlayer(self._output_device)
        adapter = _AzureStreamAdapter(player)
        push_stream = speechsdk.audio.PushAudioOutputStream(adapter)
        audio_config = speechsdk.audio.AudioOutputConfig(stream=push_stream)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=self._speech_config,
            audio_config=audio_config,
        )
        with self._active_lock:
            if generation != self._active_generation:
                player.interrupt()
                return
            self._active_player = player
            self._active_synthesizer = synthesizer
        result = None

        try:
            result = synthesizer.speak_text_async(text).get()
        finally:
            try:
                player.finish()
            finally:
                with self._active_lock:
                    if self._active_player is player:
                        self._active_player = None
                        self._active_synthesizer = None

        with self._active_lock:
            was_interrupted = generation != self._active_generation
        if was_interrupted:
            return

        if (
            result is None
            or result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted
        ):
            details = getattr(result, "cancellation_details", None)
            error_details = getattr(details, "error_details", "")
            raise RuntimeError(
                "Azure Speech could not synthesize the response. "
                f"{error_details}"
            )

    @staticmethod
    def _run_callback(callback: Callable[[], None] | None) -> None:
        if callback is None:
            return

        try:
            callback()
        except Exception:
            LOGGER.exception("Playback state callback failed.")
