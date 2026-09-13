"""Background receiver that speaks incoming Jarvis announcements in order."""

from __future__ import annotations

import json
import logging
import os
import socket

from config import settings
from speech.azure_synthesizer import AzureSpeechSynthesizer

LOGGER = logging.getLogger(__name__)


def _normalise_text(value: object) -> str:
    """Validate one announcement payload."""
    if not isinstance(value, str):
        raise ValueError("Announcement text must be a string.")

    text = " ".join(value.split())
    if not text:
        raise ValueError("Announcement text cannot be empty.")
    if len(text) > settings.MAX_ANNOUNCEMENT_CHARACTERS:
        raise ValueError("Announcement text is too long.")

    return text


class AnnouncementService:
    """Consumes local datagrams sequentially and sends them to Azure Speech."""

    def __init__(self, synthesizer: AzureSpeechSynthesizer) -> None:
        self._synthesizer = synthesizer
        self._socket_path = settings.ANNOUNCEMENT_SOCKET_PATH

    def run_forever(self) -> None:
        self._socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._socket_path.unlink(missing_ok=True)

        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as listener:
            listener.bind(str(self._socket_path))
            os.chmod(self._socket_path, 0o600)
            LOGGER.info("Announcement receiver ready.")

            try:
                while True:
                    payload, _ = listener.recvfrom(
                        settings.MAX_ANNOUNCEMENT_DATAGRAM_BYTES
                    )
                    self._handle(payload)
            finally:
                self._socket_path.unlink(missing_ok=True)

    def _handle(self, payload: bytes) -> None:
        try:
            message = json.loads(payload.decode("utf-8"))
            text = _normalise_text(message.get("text"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            LOGGER.warning("Rejected invalid announcement: %s", error)
            return

        try:
            # The shared playback lock waits for any current Jarvis reply.
            self._synthesizer.speak(text)
            LOGGER.info("Announcement spoken.")
        except Exception:
            LOGGER.exception("Unable to speak announcement.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    synthesizer = AzureSpeechSynthesizer(
        credentials=settings.load_azure_credentials(),
        voice_name=settings.AZURE_VOICE,
        output_device=settings.OUTPUT_DEVICE,
    )
    AnnouncementService(synthesizer).run_forever()


if __name__ == "__main__":
    main()
