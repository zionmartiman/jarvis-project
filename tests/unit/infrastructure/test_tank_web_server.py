import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from jarvis.domain.tank import TankLevel
from jarvis.infrastructure.web.tank_web_server import DEFAULT_DASHBOARD_PATH, TankWebServer


class TankWebServerTest(unittest.TestCase):
    def start(self, level: TankLevel | None, dashboard: str = "<html>panel</html>") -> str:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        dashboard_path = Path(directory.name) / "dashboard.html"
        dashboard_path.write_text(dashboard, encoding="utf-8")
        server = TankWebServer(lambda: level, "127.0.0.1", 0, dashboard_path)
        server.start()
        self.addCleanup(server.close)
        return f"http://127.0.0.1:{server.port}"

    def get(self, url: str):
        try:
            return urllib.request.urlopen(url, timeout=5)
        except urllib.error.HTTPError as error:
            return error

    def test_dashboard_is_served_at_the_root_and_index(self) -> None:
        base = self.start(None)

        for path in ("/", "/index.html"):
            with self.subTest(path=path):
                response = self.get(base + path)
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")
                self.assertEqual(response.read().decode("utf-8"), "<html>panel</html>")

    def test_current_level_is_returned_as_json(self) -> None:
        base = self.start(TankLevel(23.3, 70, 1.5))

        response = self.get(base + "/api/rainwater-tank/current-level")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(
            json.loads(response.read()),
            {"distance_cm": 23.3, "fill_percentage": 70, "measured_at_unix_seconds": 1.5},
        )

    def test_missing_measurement_is_reported_with_status_200(self) -> None:
        base = self.start(None)

        response = self.get(base + "/api/rainwater-tank/current-level")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.read(), b'{"error":"measurement_unavailable"}')

    def test_unknown_path_is_a_404_with_json(self) -> None:
        base = self.start(None)

        response = self.get(base + "/nope")

        self.assertEqual(response.status, 404)
        self.assertEqual(response.read(), b'{"error":"not_found"}')
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")

    def test_query_string_is_ignored_when_routing(self) -> None:
        base = self.start(TankLevel(1.0, 99, 1.0))

        response = self.get(base + "/api/rainwater-tank/current-level?x=1")

        self.assertEqual(json.loads(response.read())["fill_percentage"], 99)

    def test_the_packaged_dashboard_exists(self) -> None:
        self.assertTrue(DEFAULT_DASHBOARD_PATH.is_file())


if __name__ == "__main__":
    unittest.main()
