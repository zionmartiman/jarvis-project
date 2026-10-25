import unittest

from jarvis.domain.tank import TankAlertPolicy, TankLevel, TankStatus


def level(percentage: int) -> TankLevel:
    return TankLevel(distance_cm=50.0, fill_percentage=percentage, measured_at_unix_seconds=0.0)


class TankAlertPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.percentage_alerts: list[int] = []
        self.status_alerts: list[tuple[int, TankStatus]] = []
        self.clock = [1000.0]
        self.policy = self.make_policy(
            on_level_change=lambda lvl: self.percentage_alerts.append(lvl.fill_percentage),
            on_status_change=lambda lvl, status: self.status_alerts.append(
                (lvl.fill_percentage, status)
            ),
        )

    def make_policy(self, on_level_change, on_status_change) -> TankAlertPolicy:
        return TankAlertPolicy(
            min_change_percentage=5,
            min_interval_seconds=5.0,
            on_level_change=on_level_change,
            on_status_change=on_status_change,
            clock=lambda: self.clock[0],
        )

    def feed(self, *percentages: int) -> None:
        for percentage in percentages:
            self.policy.observe(level(percentage))

    def statuses(self) -> list[TankStatus]:
        return [status for _, status in self.status_alerts]

    def test_first_reading_never_alerts(self) -> None:
        for percentage in (0, 4, 50, 100):
            with self.subTest(percentage=percentage):
                self.setUp()
                self.feed(percentage)
                self.assertEqual(self.percentage_alerts, [])
                self.assertEqual(self.status_alerts, [])

    def test_rising_thresholds(self) -> None:
        cases = (
            (79, 80, TankStatus.GOOD),
            (89, 90, TankStatus.NEARLY_FULL),
            (99, 100, TankStatus.FULL),
        )
        for before, after, expected in cases:
            with self.subTest(before=before, after=after):
                self.setUp()
                self.feed(before, after)
                self.assertEqual(self.statuses(), [expected])

    def test_falling_thresholds(self) -> None:
        cases = (
            (21, 20, TankStatus.LOW),
            (11, 10, TankStatus.VERY_LOW),
            (5, 4, TankStatus.EMPTY),
        )
        for before, after, expected in cases:
            with self.subTest(before=before, after=after):
                self.setUp()
                self.feed(before, after)
                self.assertEqual(self.statuses(), [expected])

    def test_rising_status_is_not_repeated_until_rearmed_three_points_away(self) -> None:
        self.feed(79, 80, 79, 80)
        self.assertEqual(self.statuses(), [TankStatus.GOOD])

        self.feed(77, 80)
        self.assertEqual(self.statuses(), [TankStatus.GOOD, TankStatus.GOOD])

    def test_falling_status_is_not_repeated_until_rearmed_three_points_away(self) -> None:
        self.feed(21, 20, 21, 20)
        self.assertEqual(self.statuses(), [TankStatus.LOW])

        self.feed(23, 20)
        self.assertEqual(self.statuses(), [TankStatus.LOW, TankStatus.LOW])

    def test_status_is_not_marked_as_announced_when_callback_fails(self) -> None:
        attempts: list[TankStatus] = []

        def failing_callback(lvl: TankLevel, status: TankStatus) -> None:
            attempts.append(status)
            if len(attempts) == 1:
                raise RuntimeError("announcer down")

        self.policy = self.make_policy(lambda lvl: None, failing_callback)

        with self.assertLogs("jarvis.domain.tank", level="ERROR"):
            self.feed(79, 80)
        self.feed(79, 80)

        self.assertEqual(attempts, [TankStatus.GOOD, TankStatus.GOOD])

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

        def failing_callback(lvl: TankLevel) -> None:
            attempts.append(lvl.fill_percentage)
            if len(attempts) == 1:
                raise RuntimeError("announcer down")

        self.policy = self.make_policy(failing_callback, lambda lvl, status: None)

        self.feed(50)
        with self.assertLogs("jarvis.domain.tank", level="ERROR"):
            self.feed(56)
        self.feed(56)

        self.assertEqual(attempts, [56, 56])


if __name__ == "__main__":
    unittest.main()
