import threading
import unittest

from jarvis.application.conversation.emergency_shutdown import EmergencyShutdown
from tests.fakes import ConversationHarness, InterruptibleSynthesizer


class ReplyInterruptGateTest(unittest.TestCase):
    def test_request_is_ignored_without_an_open_cycle(self) -> None:
        harness = ConversationHarness()

        harness.gate.request()

        self.assertFalse(harness.gate.is_requested)

    def test_request_marks_the_cycle_without_cutting_the_voice_while_waiting(self) -> None:
        harness = ConversationHarness()
        harness.gate.begin()

        harness.gate.request()

        self.assertTrue(harness.gate.is_requested)
        self.assertEqual(harness.synthesizer.interruptions, 0)

    def test_request_cuts_the_voice_while_the_reply_is_spoken(self) -> None:
        harness = ConversationHarness()
        harness.gate.begin()

        with harness.gate.speaking():
            harness.gate.request()

        self.assertTrue(harness.gate.is_requested)
        self.assertEqual(harness.synthesizer.interruptions, 1)

    def test_speaking_flag_is_cleared_when_the_block_ends(self) -> None:
        harness = ConversationHarness()
        harness.gate.begin()
        with harness.gate.speaking():
            pass

        harness.gate.request()

        self.assertEqual(harness.synthesizer.interruptions, 0)

    def test_begin_forgets_a_previous_request_and_end_closes_the_cycle(self) -> None:
        harness = ConversationHarness()
        harness.gate.begin()
        harness.gate.request()

        harness.gate.begin()
        self.assertFalse(harness.gate.is_requested)

        harness.gate.request()
        harness.gate.end()
        self.assertFalse(harness.gate.is_requested)
        harness.gate.request()
        self.assertFalse(harness.gate.is_requested)

    def test_request_is_ignored_while_shutting_down(self) -> None:
        harness = ConversationHarness()
        harness.gate.begin()
        harness.shutting_down.set()

        harness.gate.request()

        self.assertFalse(harness.gate.is_requested)


class EmergencyShutdownTest(unittest.TestCase):
    def build(self, harness: ConversationHarness) -> EmergencyShutdown:
        return EmergencyShutdown(
            harness.voice, harness.microphone, harness.power, harness.shutting_down
        )

    def test_announces_then_powers_off(self) -> None:
        harness = ConversationHarness()
        emergency = self.build(harness)

        emergency.trigger()

        self.assertTrue(harness.power.shutdown_called.wait(timeout=2))
        self.assertTrue(harness.shutting_down.is_set())
        self.assertEqual(
            harness.synthesizer.spoken,
            ["Apagado manual accionado!, apagando sistemas. Venga, chao!"],
        )
        self.assertGreaterEqual(harness.microphone.stops, 1)

    def test_a_second_trigger_does_nothing(self) -> None:
        harness = ConversationHarness()
        emergency = self.build(harness)

        emergency.trigger()
        emergency.trigger()
        self.assertTrue(harness.power.shutdown_called.wait(timeout=2))
        for thread in threading.enumerate():
            if thread.name == "emergency-shutdown":
                thread.join(timeout=2)

        self.assertEqual(harness.power.calls, ["shutdown"])
        self.assertEqual(len(harness.synthesizer.spoken), 1)

    def test_cuts_whatever_is_being_said_before_the_announcement(self) -> None:
        synthesizer = InterruptibleSynthesizer(blocking_text="largo")
        harness = ConversationHarness(synthesizer=synthesizer)
        talker = threading.Thread(target=harness.voice.say, args=("largo",), daemon=True)
        talker.start()
        self.assertTrue(synthesizer.reply_started.wait(timeout=1))

        self.build(harness).trigger()

        self.assertTrue(harness.power.shutdown_called.wait(timeout=2))
        talker.join(timeout=1)
        self.assertEqual(
            synthesizer.spoken,
            ["largo", "Apagado manual accionado!, apagando sistemas. Venga, chao!"],
        )

    def test_a_failing_power_controller_is_logged(self) -> None:
        harness = ConversationHarness()
        done = threading.Event()

        def failing_shutdown() -> None:
            done.set()
            raise PermissionError("sudo not allowed")

        harness.power.shutdown = failing_shutdown  # type: ignore[method-assign]

        with self.assertLogs("jarvis.application.conversation.emergency_shutdown", "ERROR"):
            self.build(harness).trigger()
            self.assertTrue(done.wait(timeout=2))
            for thread in threading.enumerate():
                if thread.name == "emergency-shutdown":
                    thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
