"""
Síntesis de voz con Azure Speech.

Implementa la interfaz SpeechSynthesizer. Si en el futuro quieres usar
otro proveedor (ElevenLabs, Google Cloud TTS, Piper en local...), crea
una nueva clase que implemente SpeechSynthesizer y sustitúyela en
main.py; el resto del programa no cambia.
"""

from __future__ import annotations

import azure.cognitiveservices.speech as speechsdk

from audio.player import RawPcmPlayer
from config.settings import AzureCredentials
from core.interfaces import SpeechSynthesizer


class _AzureStreamAdapter(speechsdk.audio.PushAudioOutputStreamCallback):
    """
    Adapta el callback de streaming de Azure a un RawPcmPlayer genérico.

    Azure llama a write() cada vez que genera un fragmento de audio.
    En lugar de esperar a que termine y guardar un WAV completo,
    delegamos cada fragmento directamente al reproductor.
    """

    def __init__(self, player: RawPcmPlayer):
        super().__init__()
        self._player = player

    def write(self, audio_buffer) -> int:
        self._player.write(audio_buffer)
        # Azure espera que devolvamos el número de bytes recibidos.
        return audio_buffer.nbytes

    def close(self) -> None:
        self._player.close()


class AzureSpeechSynthesizer(SpeechSynthesizer):
    """Convierte texto en voz con Azure y lo reproduce en streaming."""

    def __init__(
        self,
        credentials: AzureCredentials,
        voice_name: str,
        output_device: str,
    ):
        self._output_device = output_device

        self._speech_config = speechsdk.SpeechConfig(
            subscription=credentials.key,
            region=credentials.region,
        )
        self._speech_config.speech_synthesis_voice_name = voice_name

        # Forzamos PCM sin cabecera para enviarlo directamente a aplay.
        self._speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm
        )

    def speak(self, text: str) -> None:
        text = text.strip()

        if not text:
            return

        player = RawPcmPlayer(self._output_device)
        adapter = _AzureStreamAdapter(player)
        push_stream = speechsdk.audio.PushAudioOutputStream(adapter)
        audio_config = speechsdk.audio.AudioOutputConfig(stream=push_stream)

        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=self._speech_config,
            audio_config=audio_config,
        )

        result = None

        try:
            # La reproducción comienza cuando Azure entrega los
            # primeros fragmentos; no espera a un audio completo.
            result = synthesizer.speak_text_async(text).get()
        finally:
            # Esperamos a que el altavoz termine antes de devolver el
            # control (y por tanto, antes de volver a escuchar).
            player.finish()

        if (
            result is None
            or result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted
        ):
            details = getattr(result, "cancellation_details", None)
            error_details = getattr(details, "error_details", "")

            raise RuntimeError(
                f"Azure Speech no pudo generar la respuesta. {error_details}"
            )
