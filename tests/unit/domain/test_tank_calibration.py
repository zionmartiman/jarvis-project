import unittest

from jarvis.domain.tank import TankCalibration, TankLevel, TankStatus
from jarvis.domain.tank_phrases import STATUS_PHRASES, level_phrase


class TankCalibrationTest(unittest.TestCase):
    calibration = TankCalibration(empty_distance_cm=80.0, full_distance_cm=9.0)

    def test_extremes(self) -> None:
        self.assertEqual(self.calibration.fill_percentage(80.0), 0)
        self.assertEqual(self.calibration.fill_percentage(9.0), 100)

    def test_is_linear_and_rounded(self) -> None:
        self.assertEqual(self.calibration.fill_percentage(44.5), 50)
        self.assertEqual(self.calibration.fill_percentage(70.0), 14)

    def test_is_limited_to_zero_through_hundred(self) -> None:
        self.assertEqual(self.calibration.fill_percentage(200.0), 0)
        self.assertEqual(self.calibration.fill_percentage(1.0), 100)


class TankPhrasesTest(unittest.TestCase):
    def test_every_status_has_a_phrase(self) -> None:
        self.assertEqual(set(STATUS_PHRASES), set(TankStatus))

    def test_status_values_are_the_original_strings(self) -> None:
        self.assertEqual(
            [status.value for status in TankStatus],
            ["full", "nearly_full", "good", "low", "very_low", "empty"],
        )

    def test_phrases_are_unchanged(self) -> None:
        self.assertEqual(STATUS_PHRASES[TankStatus.FULL], "Depósito lleno.")
        self.assertEqual(
            STATUS_PHRASES[TankStatus.VERY_LOW],
            "Niveles de agua muy bajos, se está a punto de quedar sin agua.",
        )
        level = TankLevel(distance_cm=50.0, fill_percentage=42, measured_at_unix_seconds=0.0)
        self.assertEqual(level_phrase(level), "Deposito al 42 por ciento.")


if __name__ == "__main__":
    unittest.main()
