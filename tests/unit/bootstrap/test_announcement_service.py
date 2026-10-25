import json
import unittest
from pathlib import Path

from jarvis.config.settings import AnnouncementSettings
from jarvis.services.announcement_service import AnnouncementService


class FakeSynthesizer:
    def __init__(self, error: Exception | None = None) -> None:
        self.spoken: list[str] = []
        self._error = error
        self.light: FakeAlertLight | None = None

    def speak_with_playback_callbacks(self, text, on_playback_started=None, on_playback_finished=None):
        if self._error is not None:
            raise self._error
        on_playback_started()
        self.spoken.append(text)
        on_playback_finished()


class FakeAlertLight:
    def __init__(self) -> None:
        self.states: list[bool] = []

    def set_alert_active(self, is_active: bool) -> None:
        self.states.append(is_active)


def payload(text: object) -> bytes:
    return json.dumps({"text": text}).encode("utf-8")


class AnnouncementServiceTest(unittest.TestCase):
    def build(self, synthesizer: FakeSynthesizer | None = None):
        self.synthesizer = synthesizer or FakeSynthesizer()
        self.light = FakeAlertLight()
        settings = AnnouncementSettings(
            socket_path=Path("announcer.sock"),
            playback_lock_path=Path("speech.lock"),
            max_characters=20,
        )
        return AnnouncementService(self.synthesizer, self.light, settings)

    def test_speaks_the_text_with_the_alert_light_on_during_playback(self) -> None:
        service = self.build()

        service.handle(payload("  Depósito   lleno. "))

        self.assertEqual(self.synthesizer.spoken, ["Depósito lleno."])
        self.assertEqual(self.light.states, [True, False])

    def test_rejects_invalid_payloads_without_speaking(self) -> None:
        service = self.build()
        invalid = [
            b"\xff\xfe",
            b"not json",
            b"[]",
            json.dumps({}).encode(),
            payload(""),
            payload("   "),
            payload(42),
            payload("x" * 21),
        ]

        for item in invalid:
            with self.subTest(item=item), self.assertLogs(level="WARNING"):
                service.handle(item)

        self.assertEqual(self.synthesizer.spoken, [])
        self.assertEqual(self.light.states, [])

    def test_a_failing_synthesizer_is_logged_and_does_not_raise(self) -> None:
        service = self.build(FakeSynthesizer(error=RuntimeError("azure down")))

        with self.assertLogs("jarvis.services.announcement_service", level="ERROR"):
            service.handle(payload("Hola"))


if __name__ == "__main__":
    unittest.main()
