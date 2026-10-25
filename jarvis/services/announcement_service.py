"""Independent process that speaks incoming Jarvis announcements in order.

Run it with ``python -m jarvis.services.announcement_service``.
"""

from __future__ import annotations

import json
import logging
import threading

from jarvis.config.credentials import load_azure_credentials
from jarvis.config.settings import AnnouncementSettings, load_settings
from jarvis.infrastructure.ipc.alert_light_client import AlertLightClient
from jarvis.infrastructure.ipc.unix_datagram import UnixDatagramServer
from jarvis.ports.hardware import AlertLight
from jarvis.ports.speech import PlaybackAwareSynthesizer

LOGGER = logging.getLogger(__name__)


def _normalise_text(value: object, max_characters: int) -> str:
    """Validate one announcement payload."""
    if not isinstance(value, str):
        raise ValueError("Announcement text must be a string.")

    text = " ".join(value.split())
    if not text:
        raise ValueError("Announcement text cannot be empty.")
    if len(text) > max_characters:
        raise ValueError("Announcement text is too long.")

    return text


class AnnouncementService:
    """Consumes local datagrams sequentially and speaks each one, lighting the alert light."""

    def __init__(
        self,
        synthesizer: PlaybackAwareSynthesizer,
        alert_light: AlertLight,
        server_settings: AnnouncementSettings,
    ) -> None:
        self._synthesizer = synthesizer
        self._alert_light = alert_light
        self._max_characters = server_settings.max_characters
        self._server = UnixDatagramServer(
            server_settings.socket_path,
            server_settings.max_datagram_bytes,
            self.handle,
            thread_name="announcement-receiver",
        )
        self._stopped = threading.Event()

    def run_forever(self) -> None:
        self._server.start()
        LOGGER.info("Announcement receiver ready.")
        try:
            self._stopped.wait()
        finally:
            self._server.close()

    def handle(self, payload: bytes) -> None:
        """Speak one datagram; an invalid one is only logged."""
        try:
            message = json.loads(payload.decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError("Announcement must be a JSON object.")
            text = _normalise_text(message.get("text"), self._max_characters)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            LOGGER.warning("Rejected invalid announcement: %s", error)
            return

        try:
            # The callbacks fire once the speaker lock is held: the light does not blink
            # while the announcement is still queued behind another one.
            self._synthesizer.speak_with_playback_callbacks(
                text,
                on_playback_started=lambda: self._alert_light.set_alert_active(True),
                on_playback_finished=lambda: self._alert_light.set_alert_active(False),
            )
            LOGGER.info("Announcement spoken.")
        except Exception:
            LOGGER.exception("Unable to speak announcement.")


def main() -> None:
    # Imported here so the service class loads where the Azure SDK is not installed.
    from jarvis.infrastructure.speech.azure_synthesizer import AzureSpeechSynthesizer

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    settings = load_settings()
    synthesizer = AzureSpeechSynthesizer(
        credentials=load_azure_credentials(settings.audio.azure_credentials_path),
        voice_name=settings.audio.azure_voice,
        output_device=settings.audio.output_device,
        playback_lock_path=settings.announcements.playback_lock_path,
    )
    alert_light = AlertLightClient(settings.arduino.alert_light_socket_path)
    AnnouncementService(synthesizer, alert_light, settings.announcements).run_forever()


if __name__ == "__main__":
    main()
