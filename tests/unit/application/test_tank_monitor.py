import unittest

from jarvis.application.tank_monitor import TankMonitor
from jarvis.domain.tank import TankAlertPolicy, TankCalibration, TankLevel, TankStatus
from jarvis.ports.hardware import DistanceSensor
from jarvis.ports.tank import TankStateStore


class FakeDistanceSensor(DistanceSensor):
    def __init__(self, *readings: float | None) -> None:
        self.readings = list(readings)

    def read_distance_cm(self) -> float | None:
        return self.readings.pop(0)


class InMemoryStore(TankStateStore):
    def __init__(self) -> None:
        self.saved: list[TankLevel] = []

    def save(self, level: TankLevel) -> None:
        self.saved.append(level)


class TankMonitorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryStore()
        self.level_alerts: list[int] = []
        self.status_alerts: list[TankStatus] = []
        self.clock = [100.0]

    def monitor(self, *readings: float | None) -> TankMonitor:
        return TankMonitor(
            sensor=FakeDistanceSensor(*readings),
            calibration=TankCalibration(empty_distance_cm=80.0, full_distance_cm=9.0),
            store=self.store,
            alert_policy=TankAlertPolicy(
                min_change_percentage=5,
                min_interval_seconds=5.0,
                on_level_change=lambda level: self.level_alerts.append(level.fill_percentage),
                on_status_change=lambda level, status: self.status_alerts.append(status),
                clock=lambda: self.clock[0],
            ),
            poll_interval_seconds=5.0,
            wall_clock=lambda: 1234.5,
        )

    def test_poll_once_converts_the_distance_into_a_stored_level(self) -> None:
        monitor = self.monitor(44.5)

        monitor.poll_once()

        expected = TankLevel(distance_cm=44.5, fill_percentage=50, measured_at_unix_seconds=1234.5)
        self.assertEqual(monitor.latest_level(), expected)
        self.assertEqual(self.store.saved, [expected])

    def test_there_is_no_level_before_the_first_valid_reading(self) -> None:
        monitor = self.monitor(None)

        monitor.poll_once()

        self.assertIsNone(monitor.latest_level())
        self.assertEqual(self.store.saved, [])

    def test_an_invalid_reading_keeps_the_previous_level(self) -> None:
        monitor = self.monitor(44.5, None)

        monitor.poll_once()
        monitor.poll_once()

        self.assertEqual(monitor.latest_level().fill_percentage, 50)
        self.assertEqual(len(self.store.saved), 1)

    def test_only_the_first_reading_is_logged(self) -> None:
        monitor = self.monitor(44.5, 40.0)

        with self.assertLogs("jarvis.application.tank_monitor", level="INFO") as captured:
            monitor.poll_once()
            monitor.poll_once()

        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Rainwater tank distance: 44.5 cm | fill level: 50%"],
        )

    def test_readings_feed_the_alert_policy(self) -> None:
        # 52 % -> 85 % crosses the "good" threshold and changes more than 5 points.
        monitor = self.monitor(43.0, 20.0)

        monitor.poll_once()
        self.clock[0] = 200.0
        monitor.poll_once()

        self.assertEqual(self.level_alerts, [85])
        self.assertEqual(self.status_alerts, [TankStatus.GOOD])

    def test_the_first_reading_never_alerts(self) -> None:
        monitor = self.monitor(10.0)

        monitor.poll_once()

        self.assertEqual(self.level_alerts, [])
        self.assertEqual(self.status_alerts, [])

    def test_start_and_close_do_not_raise(self) -> None:
        monitor = self.monitor(*([44.5] * 100))

        monitor.start()
        monitor.close()


if __name__ == "__main__":
    unittest.main()
