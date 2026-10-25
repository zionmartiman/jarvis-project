import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Sensors.rainwater_tank_meter import RainwaterTankLevel, RainwaterTankMeter


def level(percentage: int) -> RainwaterTankLevel:
    return RainwaterTankLevel(distance_cm=50.0, fill_percentage=percentage, measured_at_unix_seconds=0.0)


class TankAlertsTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.percentage_alerts: list[int] = []
        self.status_alerts: list[tuple[int, str]] = []
        self.clock = [1000.0]
        self.meter = RainwaterTankMeter(
            arduino=None,
            state_path=Path(directory.name) / "tank.json",
            on_fill_level_changed=lambda lvl: self.percentage_alerts.append(lvl.fill_percentage),
            on_fill_level_status_changed=lambda lvl, status: self.status_alerts.append(
                (lvl.fill_percentage, status)
            ),
        )
        monotonic_patch = patch("Sensors.rainwater_tank_meter.time.monotonic", side_effect=lambda: self.clock[0])
        monotonic_patch.start()
        self.addCleanup(monotonic_patch.stop)

    def feed(self, *percentages: int) -> None:
        for percentage in percentages:
            self.meter._monitor.publish(level(percentage))

    def statuses(self) -> list[str]:
        return [status for _, status in self.status_alerts]

    def test_first_reading_never_alerts(self) -> None:
        for percentage in (0, 4, 50, 100):
            with self.subTest(percentage=percentage):
                self.setUp()
                self.feed(percentage)
                self.assertEqual(self.percentage_alerts, [])
                self.assertEqual(self.status_alerts, [])

    def test_rising_thresholds(self) -> None:
        for before, after, expected in ((79, 80, "good"), (89, 90, "nearly_full"), (99, 100, "full")):
            with self.subTest(before=before, after=after):
                self.setUp()
                self.feed(before, after)
                self.assertEqual(self.statuses(), [expected])

    def test_falling_thresholds(self) -> None:
        for before, after, expected in ((21, 20, "low"), (11, 10, "very_low"), (5, 4, "empty")):
            with self.subTest(before=before, after=after):
                self.setUp()
                self.feed(before, after)
                self.assertEqual(self.statuses(), [expected])

    def test_rising_status_is_not_repeated_until_rearmed_three_points_away(self) -> None:
        self.feed(79, 80, 79, 80)
        self.assertEqual(self.statuses(), ["good"])

        self.feed(77, 80)
        self.assertEqual(self.statuses(), ["good", "good"])

    def test_falling_status_is_not_repeated_until_rearmed_three_points_away(self) -> None:
        self.feed(21, 20, 21, 20)
        self.assertEqual(self.statuses(), ["low"])

        self.feed(23, 20)
        self.assertEqual(self.statuses(), ["low", "low"])

    def test_status_is_not_announced_when_callback_fails(self) -> None:
        attempts: list[str] = []

        def failing_callback(lvl: RainwaterTankLevel, status: str) -> None:
            attempts.append(status)
            if len(attempts) == 1:
                raise RuntimeError("announcer down")

        self.meter._on_fill_level_status_changed = failing_callback

        with self.assertLogs("jarvis.domain.tank", level="ERROR"):
            self.feed(79, 80)
        self.feed(79, 80)

        self.assertEqual(attempts, ["good", "good"])

    def test_percentage_alert_needs_five_points_change(self) -> None:
        self.feed(50, 54)
        self.assertEqual(self.percentage_alerts, [])

        self.feed(55)
        self.assertEqual(self.percentage_alerts, [55])

    def test_percentage_alert_needs_five_seconds_since_previous_alert(self) -> None:
        self.feed(50)

        self.clock[0] = 1100.0
        self.feed(55)
        self.assertEqual(self.percentage_alerts, [55])

        self.clock[0] = 1102.0
        self.feed(60)
        self.assertEqual(self.percentage_alerts, [55])

        self.clock[0] = 1105.0
        self.feed(60)
        self.assertEqual(self.percentage_alerts, [55, 60])

    def test_percentage_change_is_measured_from_last_announced_level(self) -> None:
        self.feed(50, 53, 56)
        self.assertEqual(self.percentage_alerts, [56])

    def test_percentage_not_marked_as_announced_when_callback_fails(self) -> None:
        attempts: list[int] = []

        def failing_callback(lvl: RainwaterTankLevel) -> None:
            attempts.append(lvl.fill_percentage)
            if len(attempts) == 1:
                raise RuntimeError("announcer down")

        self.meter._on_fill_level_changed = failing_callback

        self.feed(50)
        with self.assertLogs("jarvis.domain.tank", level="ERROR"):
            self.feed(56)
        self.feed(56)

        self.assertEqual(attempts, [56, 56])


if __name__ == "__main__":
    unittest.main()
