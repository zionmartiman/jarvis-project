import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.domain.tank import TankLevel
from jarvis.infrastructure.tank.state_file import JsonTankStateFile


class JsonTankStateFileTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state" / "tank.json"

    def test_writes_the_level_fields_as_one_json_line(self) -> None:
        JsonTankStateFile(self.path).save(TankLevel(23.3, 70, 1.5))

        text = self.path.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(
            json.loads(text),
            {"distance_cm": 23.3, "fill_percentage": 70, "measured_at_unix_seconds": 1.5},
        )
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_overwrites_the_previous_level(self) -> None:
        store = JsonTankStateFile(self.path)

        store.save(TankLevel(50.0, 40, 1.0))
        store.save(TankLevel(20.0, 80, 2.0))

        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["fill_percentage"], 80)

    def test_a_write_failure_is_logged_and_not_raised(self) -> None:
        store = JsonTankStateFile(self.path)

        with patch("os.replace", side_effect=OSError("disk full")):
            with self.assertLogs("jarvis.infrastructure.tank.state_file", level="ERROR"):
                store.save(TankLevel(50.0, 40, 1.0))


if __name__ == "__main__":
    unittest.main()
