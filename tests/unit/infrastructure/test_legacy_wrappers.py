"""The legacy facades that keep the pre-refactor app running on the new adapters."""

import unittest
from pathlib import Path

from bridge.legacy_context import history_to_context
from Indicators.arduino_rgb_indicator import ArduinoRgbIndicator
from jarvis.domain.assistant_status import AssistantStatus
from jarvis.domain.conversation import ChatMessage, Role
from system.arduino_button_monitor import ArduinoButtonMonitor


class HistoryToContextTest(unittest.TestCase):
    def test_last_summary_becomes_the_context_summary_and_the_rest_are_messages(self) -> None:
        context = history_to_context(
            [
                {"role": "summary", "text": "viejo"},
                {"role": "summary", "text": "Prefiere el té."},
                {"role": "user", "text": "Hola"},
                {"role": "assistant", "text": "Buenas"},
            ]
        )

        self.assertEqual(context.summary, "Prefiere el té.")
        self.assertEqual(
            context.messages, (ChatMessage(Role.USER, "Hola"), ChatMessage(Role.ASSISTANT, "Buenas"))
        )

    def test_empty_history_has_no_summary(self) -> None:
        context = history_to_context([])

        self.assertEqual(context.messages, ())
        self.assertIsNone(context.summary)


class FakeSerial:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.commands: list[str] = []

    def request(self, command: str) -> str | None:
        self.commands.append(command)
        return self.responses.pop(0) if self.responses else "OK"


class ArduinoRgbIndicatorTest(unittest.TestCase):
    def test_status_and_alert_light_use_the_arduino_commands(self) -> None:
        serial = FakeSerial()
        indicator = ArduinoRgbIndicator(serial, Path("/tmp/control.sock"))

        indicator.set_status(AssistantStatus.PROCESSING)
        indicator.set_alert_light(True)

        self.assertEqual(serial.commands, ["STATE BREATHING", "LIGHT ALERT ON"])


class ArduinoButtonMonitorTest(unittest.TestCase):
    def test_presses_are_dispatched_to_their_callbacks(self) -> None:
        calls: list[str] = []
        serial = FakeSerial("BUTTON_SHUTDOWN", "BUTTON_INTERRUPT", "BUTTON_IDLE")
        monitor = ArduinoButtonMonitor(
            serial,
            on_shutdown_pressed=lambda: calls.append("shutdown"),
            on_response_interrupt_pressed=lambda: calls.append("interrupt"),
        )

        for _ in range(3):
            monitor._monitor.poll_once()

        self.assertEqual(calls, ["shutdown", "interrupt"])


if __name__ == "__main__":
    unittest.main()
