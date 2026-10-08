import tempfile
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import ModuleType

arduino_package = ModuleType("Arduino")
arduino_package.__path__ = []
arduino_connection = ModuleType("Arduino.arduino_mega_connection")
arduino_connection.ArduinoMegaConnection = object
sys.modules.setdefault("Arduino", arduino_package)
sys.modules.setdefault("Arduino.arduino_mega_connection", arduino_connection)

from Sensors.rainwater_tank_meter import RainwaterTankLevel, RainwaterTankMeter


class RainwaterTankMeterTest(unittest.TestCase):
    def test_only_first_level_is_logged_but_updates_and_notifications_continue(self) -> None:
        percentage_notifications: list[RainwaterTankLevel] = []
        status_notifications: list[tuple[RainwaterTankLevel, str]] = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            meter = RainwaterTankMeter(
                arduino=None,
                state_path=Path(temporary_directory) / "tank.json",
                on_fill_level_changed=percentage_notifications.append,
                on_fill_level_status_changed=lambda level, status: status_notifications.append((level, status)),
            )
            first_level = RainwaterTankLevel(23.3, 70, 1.0)
            next_level = RainwaterTankLevel(18.0, 85, 2.0)
            output = StringIO()

            with redirect_stdout(output):
                meter._publish(first_level)
                meter._publish(next_level)

            self.assertEqual(output.getvalue().splitlines(), [
                "Rainwater tank distance: 23.3 cm | fill level: 70%",
            ])
            self.assertEqual(meter.latest_level(), next_level)
            self.assertEqual(percentage_notifications, [next_level])
            self.assertEqual(status_notifications, [(next_level, "good")])


if __name__ == "__main__":
    unittest.main()