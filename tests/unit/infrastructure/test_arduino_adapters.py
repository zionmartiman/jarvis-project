import unittest

from jarvis.domain.assistant_status import AssistantStatus
from jarvis.infrastructure.arduino import protocol
from jarvis.infrastructure.arduino.alert_light import ArduinoAlertLight
from jarvis.infrastructure.arduino.button_panel import ArduinoButtonPanel
from jarvis.infrastructure.arduino.distance_sensor import ArduinoDistanceSensor
from jarvis.infrastructure.arduino.status_light import ArduinoStatusLight
from jarvis.ports.hardware import ButtonPress


class FakeSerial:
    """Answers each command with the next scripted response and records the commands."""

    def __init__(self, *responses: str | None) -> None:
        self.responses = list(responses)
        self.commands: list[str] = []

    def request(self, command: str) -> str | None:
        self.commands.append(command)
        return self.responses.pop(0) if self.responses else protocol.OK


class ArduinoStatusLightTest(unittest.TestCase):
    def test_each_status_sends_its_command(self) -> None:
        serial = FakeSerial()
        light = ArduinoStatusLight(serial)

        for status in AssistantStatus:
            light.set_status(status)

        self.assertEqual(
            serial.commands,
            ["STATE RED", "STATE GREEN", "STATE BREATHING", "STATE YELLOW"],
        )

    def test_repeated_status_is_sent_once(self) -> None:
        serial = FakeSerial()
        light = ArduinoStatusLight(serial)

        light.set_status(AssistantStatus.WAITING)
        light.set_status(AssistantStatus.WAITING)

        self.assertEqual(serial.commands, ["STATE RED"])

    def test_a_failed_command_is_retried_and_logged(self) -> None:
        serial = FakeSerial(None, protocol.OK)
        light = ArduinoStatusLight(serial)

        with self.assertLogs("jarvis.infrastructure.arduino.status_light", level="WARNING"):
            light.set_status(AssistantStatus.WAITING)
        light.set_status(AssistantStatus.WAITING)

        self.assertEqual(serial.commands, ["STATE RED", "STATE RED"])


class ArduinoAlertLightTest(unittest.TestCase):
    def test_on_and_off_commands(self) -> None:
        serial = FakeSerial()
        light = ArduinoAlertLight(serial)

        light.set_alert_active(True)
        light.set_alert_active(False)

        self.assertEqual(serial.commands, ["LIGHT ALERT ON", "LIGHT ALERT OFF"])

    def test_repeated_state_is_sent_once(self) -> None:
        serial = FakeSerial()
        light = ArduinoAlertLight(serial)

        light.set_alert_active(False)
        light.set_alert_active(False)
        light.set_alert_active(True)
        light.set_alert_active(True)

        self.assertEqual(serial.commands, ["LIGHT ALERT OFF", "LIGHT ALERT ON"])

    def test_a_failed_command_is_retried_and_logged(self) -> None:
        serial = FakeSerial("ERR", protocol.OK)
        light = ArduinoAlertLight(serial)

        with self.assertLogs("jarvis.infrastructure.arduino.alert_light", level="WARNING"):
            light.set_alert_active(True)
        light.set_alert_active(True)

        self.assertEqual(serial.commands, ["LIGHT ALERT ON", "LIGHT ALERT ON"])


class ArduinoButtonPanelTest(unittest.TestCase):
    def test_responses_become_button_presses(self) -> None:
        cases = {
            "BUTTON_SHUTDOWN": ButtonPress.SHUTDOWN,
            "BUTTON_INTERRUPT": ButtonPress.INTERRUPT,
            "BUTTON_IDLE": None,
            "": None,
            None: None,
            "garbage": None,
        }
        for response, expected in cases.items():
            with self.subTest(response=response):
                serial = FakeSerial(response)

                self.assertIs(ArduinoButtonPanel(serial).read_pending_press(), expected)
                self.assertEqual(serial.commands, ["BUTTON STATUS"])


class ArduinoDistanceSensorTest(unittest.TestCase):
    def read(self, response: str | None) -> tuple[float | None, FakeSerial]:
        serial = FakeSerial(response)
        return ArduinoDistanceSensor(serial).read_distance_cm(), serial

    def test_valid_response_returns_the_distance(self) -> None:
        distance, serial = self.read("DISTANCE_CM 23.3")

        self.assertEqual(distance, 23.3)
        self.assertEqual(serial.commands, ["SENSOR DISTANCE"])

    def test_no_response_returns_none_without_warning(self) -> None:
        with self.assertNoLogs("jarvis.infrastructure.arduino.distance_sensor", level="WARNING"):
            distance, _ = self.read(None)

        self.assertIsNone(distance)

    def test_invalid_responses_return_none_and_warn(self) -> None:
        for response in ("OK", "", "DISTANCE_CM abc", "DISTANCE_CM 0", "DISTANCE_CM -1"):
            with self.subTest(response=response):
                with self.assertLogs("jarvis.infrastructure.arduino.distance_sensor", level="WARNING"):
                    distance, _ = self.read(response)

                self.assertIsNone(distance)


if __name__ == "__main__":
    unittest.main()
