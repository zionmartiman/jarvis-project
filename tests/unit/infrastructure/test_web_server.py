import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from jarvis.domain.tank import TankLevel
from jarvis.infrastructure.web.web_server import _PAGES, STATIC_DIR, JarvisWebServer


class WebServerTest(unittest.TestCase):
    def start(
        self,
        static_dir: Path,
        level: TankLevel | None = None,
        memory_feed=None,
    ) -> str:
        server = JarvisWebServer(
            host="127.0.0.1",
            port=0,
            static_dir=static_dir,
            latest_level=lambda: level,
            memory_feed=memory_feed,
        )
        server.start()
        self.addCleanup(server.close)
        return f"http://127.0.0.1:{server.port}"

    def start_packaged(self, level: TankLevel | None = None, memory_feed=None) -> str:
        return self.start(STATIC_DIR, level, memory_feed)

    def start_with_files(self, files: dict[str, str]) -> tuple[str, Path]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        static_dir = Path(directory.name) / "static"
        static_dir.mkdir()
        for relative_path, content in files.items():
            file_path = static_dir / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        return self.start(static_dir), static_dir

    def get(self, url: str):
        try:
            return urllib.request.urlopen(url, timeout=5)
        except urllib.error.HTTPError as error:
            return error

    def test_the_start_page_is_served_at_the_root_and_index(self) -> None:
        base = self.start_packaged()

        for path in ("/", "/index.html"):
            with self.subTest(path=path):
                response = self.get(base + path)
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")
                body = response.read().decode("utf-8")
                self.assertEqual(body, (STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    def test_the_tank_dashboard_is_served_at_deposito(self) -> None:
        base = self.start_packaged()

        response = self.get(base + "/deposito")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(
            response.read().decode("utf-8"),
            (STATIC_DIR / "rainwater_tank.html").read_text(encoding="utf-8"),
        )

    def test_the_memory_page_exists(self) -> None:
        base = self.start_packaged()

        response = self.get(base + "/memoria")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")

    def test_every_page_file_exists_on_disk(self) -> None:
        for filename in _PAGES.values():
            with self.subTest(filename=filename):
                self.assertTrue((STATIC_DIR / filename).is_file())

    def test_a_static_file_is_served_with_its_mime_type(self) -> None:
        base = self.start_packaged()

        response = self.get(base + "/static/site/nav.js")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "text/javascript; charset=utf-8")
        self.assertEqual(
            response.read().decode("utf-8"),
            (STATIC_DIR / "site" / "nav.js").read_text(encoding="utf-8"),
        )

    def test_static_files_are_not_cached_outside_vendor(self) -> None:
        base = self.start_packaged()

        response = self.get(base + "/static/site/nav.js")

        self.assertEqual(response.headers["Cache-Control"], "no-cache")

    def test_vendor_static_files_are_cached(self) -> None:
        base, _ = self.start_with_files({"vendor/lib.js": "var x = 1;"})

        response = self.get(base + "/static/vendor/lib.js")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=86400")

    def test_path_traversal_with_a_literal_dotdot_is_rejected(self) -> None:
        base, static_dir = self.start_with_files({"nav.js": "ok"})
        (static_dir.parent / "outside.py").write_text("secret", encoding="utf-8")

        response = self.get(base + "/static/../outside.py")

        self.assertEqual(response.status, 404)

    def test_path_traversal_with_a_percent_encoded_dotdot_is_rejected(self) -> None:
        base, static_dir = self.start_with_files({"nav.js": "ok"})
        (static_dir.parent / "outside.py").write_text("secret", encoding="utf-8")

        response = self.get(base + "/static/%2e%2e/outside.py")

        self.assertEqual(response.status, 404)

    def test_a_disallowed_extension_is_rejected(self) -> None:
        base, _ = self.start_with_files({"notes.py": "print('hi')"})

        response = self.get(base + "/static/notes.py")

        self.assertEqual(response.status, 404)

    def test_a_missing_static_file_is_a_404(self) -> None:
        base, _ = self.start_with_files({"nav.js": "ok"})

        response = self.get(base + "/static/missing.js")

        self.assertEqual(response.status, 404)

    def test_current_level_is_returned_as_json(self) -> None:
        base = self.start_packaged(TankLevel(23.3, 70, 1.5))

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
        base = self.start_packaged(None)

        response = self.get(base + "/api/rainwater-tank/current-level")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.read(), b'{"error":"measurement_unavailable"}')

    def test_query_string_is_ignored_when_routing(self) -> None:
        base = self.start_packaged(TankLevel(1.0, 99, 1.0))

        response = self.get(base + "/api/rainwater-tank/current-level?x=1")

        self.assertEqual(json.loads(response.read())["fill_percentage"], 99)

    def test_unknown_path_is_a_404_with_json(self) -> None:
        base = self.start_packaged()

        response = self.get(base + "/nope")

        self.assertEqual(response.status, 404)
        self.assertEqual(response.read(), b'{"error":"not_found"}')
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")

    def test_memory_routes_are_unavailable_without_a_feed(self) -> None:
        base = self.start_packaged(memory_feed=None)

        response = self.get(base + "/api/memory/graph")

        self.assertEqual(response.status, 503)
        self.assertEqual(response.read(), b'{"error":"memory_unavailable"}')


if __name__ == "__main__":
    unittest.main()
