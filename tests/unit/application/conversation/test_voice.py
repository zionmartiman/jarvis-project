import threading
import unittest

from jarvis.application.conversation.safe_status import SafeStatusIndicator
from jarvis.application.conversation.voice import Voice
from jarvis.domain.assistant_status import AssistantStatus
from jarvis.ports.hardware import StatusIndicator
from tests.fakes import (
    FakeMicrophone,
    FakeSynthesizer,
    InterruptibleSynthesizer,
    RecordingStatusIndicator,
)

LOGGER_NAME = "jarvis.application.conversation.voice"


class FailingSpeakSynthesizer(FakeSynthesizer):
    def speak(self, text: str) -> None:
        raise RuntimeError("no audio")


class FailingInterruptSynthesizer(FakeSynthesizer):
    def interrupt(self) -> None:
        raise RuntimeError("cannot interrupt")


class VoiceTest(unittest.TestCase):
    def build(self, synthesizer: FakeSynthesizer) -> tuple[Voice, FakeMicrophone, list, threading.Event]:
        microphone = FakeMicrophone()
        status = RecordingStatusIndicator()
        shutting_down = threading.Event()
        voice = Voice(synthesizer, microphone, status, shutting_down)
        return voice, microphone, status.statuses, shutting_down

    def test_say_sets_speaking_mutes_the_microphone_and_speaks(self) -> None:
        synthesizer = FakeSynthesizer()
        voice, microphone, statuses, _ = self.build(synthesizer)

        voice.say("Hola")

        self.assertEqual(synthesizer.spoken, ["Hola"])
        self.assertEqual(statuses, [AssistantStatus.SPEAKING])
        self.assertEqual(microphone.stops, 1)

    def test_say_does_nothing_while_shutting_down(self) -> None:
        synthesizer = FakeSynthesizer()
        voice, microphone, statuses, shutting_down = self.build(synthesizer)
        shutting_down.set()

        voice.say("Hola")

        self.assertEqual(synthesizer.spoken, [])
        self.assertEqual(statuses, [])
        self.assertEqual(microphone.stops, 0)

    def test_say_propagates_synthesizer_errors(self) -> None:
        voice, _, _, _ = self.build(FailingSpeakSynthesizer())

        with self.assertRaises(RuntimeError):
            voice.say("Hola")

    def test_say_ignores_synthesizer_errors_once_shutting_down(self) -> None:
        synthesizer = FailingSpeakSynthesizer()
        voice, _, _, shutting_down = self.build(synthesizer)
        original_speak = synthesizer.speak

        def speak_then_shut_down(text: str) -> None:
            shutting_down.set()
            original_speak(text)

        synthesizer.speak = speak_then_shut_down  # type: ignore[method-assign]

        voice.say("Hola")

    def test_interrupt_forwards_to_the_synthesizer(self) -> None:
        synthesizer = FakeSynthesizer()
        voice, _, _, _ = self.build(synthesizer)

        voice.interrupt()

        self.assertEqual(synthesizer.interruptions, 1)

    def test_interrupt_logs_instead_of_raising(self) -> None:
        voice, _, _, _ = self.build(FailingInterruptSynthesizer())

        with self.assertLogs(LOGGER_NAME, level="ERROR"):
            voice.interrupt()

    def test_say_last_words_speaks_even_while_shutting_down(self) -> None:
        synthesizer = FakeSynthesizer()
        voice, _, statuses, shutting_down = self.build(synthesizer)
        shutting_down.set()

        voice.say_last_words("Adiós")

        self.assertEqual(synthesizer.spoken, ["Adiós"])
        self.assertEqual(synthesizer.interruptions, 1)
        self.assertEqual(statuses, [AssistantStatus.SPEAKING])

    def test_say_last_words_logs_a_speech_failure(self) -> None:
        voice, _, _, _ = self.build(FailingSpeakSynthesizer())

        with self.assertLogs(LOGGER_NAME, level="ERROR"):
            voice.say_last_words("Adiós")

    def test_say_last_words_interrupts_whoever_is_speaking(self) -> None:
        synthesizer = InterruptibleSynthesizer(blocking_text="largo")
        voice, _, _, _ = self.build(synthesizer)
        talker = threading.Thread(target=voice.say, args=("largo",), daemon=True)
        talker.start()
        self.assertTrue(synthesizer.reply_started.wait(timeout=1))

        voice.say_last_words("Adiós")
        talker.join(timeout=1)

        self.assertFalse(talker.is_alive())
        self.assertEqual(synthesizer.spoken, ["largo", "Adiós"])


class RaisingIndicator(StatusIndicator):
    def set_status(self, status: AssistantStatus) -> None:
        raise OSError("serial gone")


class SafeStatusIndicatorTest(unittest.TestCase):
    def test_forwards_the_status(self) -> None:
        inner = RecordingStatusIndicator()

        SafeStatusIndicator(inner).set_status(AssistantStatus.LISTENING)

        self.assertEqual(inner.statuses, [AssistantStatus.LISTENING])

    def test_logs_instead_of_raising(self) -> None:
        with self.assertLogs("jarvis.application.conversation.safe_status", level="ERROR"):
            SafeStatusIndicator(RaisingIndicator()).set_status(AssistantStatus.WAITING)


if __name__ == "__main__":
    unittest.main()
