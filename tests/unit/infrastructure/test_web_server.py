import hashlib
import http.client
import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from jarvis.application.knowledge.graph_memory import KnowledgeGraphMemory
from jarvis.domain.knowledge_graph import (
    EntityProposal,
    EntityType,
    GraphDelta,
    GraphSnapshot,
    RelationProposal,
)
from jarvis.domain.tank import TankLevel
from jarvis.infrastructure.knowledge.sqlite_store import SqliteKnowledgeGraph
from jarvis.infrastructure.web.web_server import _PAGES, STATIC_DIR, JarvisWebServer
from jarvis.ports.knowledge_graph import GraphExtractor, KnowledgeGraphFeed


class WebServerTestCase(unittest.TestCase):
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
        self.server = server
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
            response = urllib.request.urlopen(url, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        self.addCleanup(response.close)
        return response


class WebServerTest(WebServerTestCase):
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

    def test_the_memory_page_assets_are_served(self) -> None:
        base = self.start_packaged()
        page = self.get(base + "/memoria").read().decode("utf-8")

        for path in (
            "/static/vendor/force-graph-1.52.0.min.js",
            "/static/memoria/graph_state.js",
            "/static/memoria/memoria.js",
        ):
            with self.subTest(path=path):
                self.assertIn(path, page)
                response = self.get(base + path)
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    response.headers["Content-Type"], "text/javascript; charset=utf-8"
                )

    def test_the_vendored_force_graph_is_the_audited_release(self) -> None:
        digest = hashlib.sha256(
            (STATIC_DIR / "vendor" / "force-graph-1.52.0.min.js").read_bytes()
        ).hexdigest()

        self.assertEqual(
            digest, "f59db59ba92ff5a76ed93d7a4d77a703b176260e5d9cd29f4f8eb4f6c369a629"
        )

    def test_vendor_notes_and_licence_are_not_served(self) -> None:
        base = self.start_packaged()

        for path in ("/static/vendor/README.md", "/static/vendor/force-graph.LICENSE.txt"):
            with self.subTest(path=path):
                self.assertEqual(self.get(base + path).status, 404)

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

    def test_the_memory_stream_is_unavailable_without_a_feed(self) -> None:
        base = self.start_packaged(memory_feed=None)

        response = self.get(base + "/api/memory/stream")

        self.assertEqual(response.status, 503)


class NoExtraction(GraphExtractor):
    def extract(self, prompt: str) -> GraphDelta:
        raise AssertionError("The web tests never run the worker")


def person(key: str, name: str) -> EntityProposal:
    return EntityProposal(key=key, name=name, type=EntityType.PERSONA)


class FailingFeed(KnowledgeGraphFeed):
    def snapshot(self) -> GraphSnapshot:
        raise RuntimeError("database is gone")

    def events_since(self, version, limit):
        raise RuntimeError("database is gone")

    def current_version(self) -> int:
        raise RuntimeError("database is gone")

    def graph_id(self) -> str:
        raise RuntimeError("database is gone")

    def wait_for_change(self, after_version: int, timeout: float) -> None:
        time.sleep(timeout)


class EventStream:
    """A raw SSE connection that reads one message at a time."""

    def __init__(self, port: int, path: str, headers: dict[str, str] | None = None) -> None:
        self.connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        self.connection.request("GET", path, headers=headers or {})
        self.response = self.connection.getresponse()

    def close(self) -> None:
        self.connection.close()

    def next_message(self) -> dict[str, str]:
        """Fields of the next message that has data, skipping comments and ``retry:``."""
        fields: dict[str, str] = {}
        while True:
            line = self.response.fp.readline()
            if not line:
                raise EOFError("The stream ended")
            text = line.decode("utf-8").rstrip("\n")
            if text == "":
                if "data" in fields:
                    return fields
                fields = {}
            elif not text.startswith(":"):
                name, _, value = text.partition(": ")
                fields[name] = value


class MemoryRoutesTest(WebServerTestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = SqliteKnowledgeGraph(Path(directory.name) / "graph.sqlite3")
        self.memory = KnowledgeGraphMemory(
            self.store, NoExtraction(), extraction_enabled=False, retrieval_enabled=False
        )
        self.base = self.start_packaged(memory_feed=self.memory)
        self.port = int(self.base.rsplit(":", 1)[1])

    def apply(self, delta: GraphDelta) -> None:
        self.store.apply(delta, "2026-10-25T18:00:00+00:00")

    def apply_ana(self) -> None:
        self.apply(
            GraphDelta(
                entities=(person("ana", "Ana"),),
                relations=(RelationProposal("ana", "usuario", "hermana_de", "Ana es hermana"),),
            )
        )

    def open_stream(self, path: str, headers: dict[str, str] | None = None) -> EventStream:
        stream = EventStream(self.port, path, headers)
        self.addCleanup(stream.close)
        return stream

    def test_the_graph_is_returned_as_a_snapshot(self) -> None:
        self.apply_ana()

        response = self.get(self.base + "/api/memory/graph")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        body = json.loads(response.read())
        self.assertEqual(body["graph_id"], self.store.graph_id())
        self.assertEqual(body["version"], self.store.current_version())
        self.assertEqual([node["key"] for node in body["nodes"]], ["usuario", "ana"])
        self.assertEqual(len(body["links"]), 1)
        self.assertEqual(body["links"][0]["type"], "hermana_de")

    def test_non_ascii_text_is_sent_as_utf8_not_escaped(self) -> None:
        self.apply(GraphDelta(entities=(person("maria", "María Núñez"),)))

        raw = self.get(self.base + "/api/memory/graph").read()

        self.assertIn("María Núñez".encode("utf-8"), raw)

    def test_events_are_paged(self) -> None:
        self.apply_ana()
        total = self.store.current_version()
        self.assertGreaterEqual(total, 2)

        first = json.loads(self.get(self.base + "/api/memory/events?since=0&limit=1").read())
        second = json.loads(
            self.get(self.base + f"/api/memory/events?since={first['next']}&limit=500").read()
        )

        self.assertEqual(first["graph_id"], self.store.graph_id())
        self.assertEqual([event["version"] for event in first["events"]], [1])
        self.assertEqual(set(first["events"][0]), {"version", "ts", "op", "data"})
        self.assertEqual(first["next"], 1)
        self.assertEqual(
            [event["version"] for event in second["events"]], list(range(2, total + 1))
        )
        self.assertEqual(second["next"], total)

    def test_an_events_page_past_the_end_is_empty_and_keeps_the_cursor(self) -> None:
        self.apply_ana()
        total = self.store.current_version()

        page = json.loads(self.get(self.base + f"/api/memory/events?since={total}").read())

        self.assertEqual(page["events"], [])
        self.assertEqual(page["next"], total)

    def test_the_events_limit_is_capped(self) -> None:
        for batch in range(5):
            self.apply(
                GraphDelta(
                    entities=tuple(person(f"p{batch}_{i}", f"P{batch} {i}") for i in range(10))
                )
            )
        total = self.store.current_version()
        self.assertGreater(total, 50)

        page = json.loads(self.get(self.base + "/api/memory/events?since=0&limit=999999").read())

        self.assertEqual(len(page["events"]), total)

    def test_invalid_event_parameters_are_a_400(self) -> None:
        for query in ("since=abc", "since=-1", "limit=0", "limit=x"):
            with self.subTest(query=query):
                response = self.get(self.base + f"/api/memory/events?{query}")
                self.assertEqual(response.status, 400)
                self.assertEqual(response.read(), b'{"error":"bad_request"}')

    def test_an_unknown_memory_route_is_a_404(self) -> None:
        response = self.get(self.base + "/api/memory/nope")

        self.assertEqual(response.status, 404)

    def test_a_failing_feed_is_a_500_and_the_server_keeps_working(self) -> None:
        base = self.start_packaged(memory_feed=FailingFeed())

        for path in ("/api/memory/graph", "/api/memory/events"):
            with self.subTest(path=path):
                with self.assertLogs("jarvis.infrastructure.web.web_server", "ERROR"):
                    response = self.get(base + path)
                self.assertEqual(response.status, 500)
                self.assertEqual(response.read(), b'{"error":"memory_error"}')
        self.assertEqual(self.get(base + "/api/rainwater-tank/current-level").status, 200)

    def test_the_stream_sends_new_events_as_they_happen(self) -> None:
        stream = self.open_stream(f"/api/memory/stream?since={self.store.current_version()}")
        self.assertEqual(stream.response.status, 200)
        self.assertEqual(
            stream.response.headers["Content-Type"], "text/event-stream; charset=utf-8"
        )
        self.assertEqual(stream.response.headers["Cache-Control"], "no-store")
        first_new_version = self.store.current_version() + 1
        started = time.monotonic()
        self.apply_ana()

        message = stream.next_message()

        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(message["event"], "graph")
        self.assertEqual(message["id"], str(first_new_version))
        event = json.loads(message["data"])
        self.assertEqual(event["version"], first_new_version)
        self.assertEqual(event["op"], "entity_created")
        self.assertEqual(event["data"]["key"], "ana")

    def test_the_stream_starts_after_the_since_version(self) -> None:
        self.apply_ana()
        total = self.store.current_version()

        stream = self.open_stream(f"/api/memory/stream?since={total - 1}")

        self.assertEqual(stream.next_message()["id"], str(total))

    def test_last_event_id_resumes_where_it_left_off(self) -> None:
        self.apply_ana()
        total = self.store.current_version()

        stream = self.open_stream(
            "/api/memory/stream?since=0", headers={"Last-Event-ID": str(total - 1)}
        )

        self.assertEqual(stream.next_message()["id"], str(total))

    def test_a_since_version_in_the_future_gets_a_reset(self) -> None:
        stream = self.open_stream("/api/memory/stream?since=99")

        message = stream.next_message()

        self.assertEqual(message["event"], "reset")
        self.assertEqual(message["data"], "{}")
        self.assertNotIn("id", message)
        with self.assertRaises(EOFError):
            stream.next_message()

    def test_an_invalid_since_is_a_400(self) -> None:
        response = self.get(self.base + "/api/memory/stream?since=abc")

        self.assertEqual(response.status, 400)

    def test_the_ninth_stream_is_refused(self) -> None:
        for _ in range(8):
            self.assertEqual(self.open_stream("/api/memory/stream").response.status, 200)

        response = self.get(self.base + "/api/memory/stream")

        self.assertEqual(response.status, 503)
        self.assertEqual(response.read(), b'{"error":"too_many_streams"}')

    def test_closing_the_server_ends_open_streams_quickly(self) -> None:
        stream = self.open_stream("/api/memory/stream")
        self.assertEqual(stream.response.status, 200)

        started = time.monotonic()
        self.server.close()

        self.assertLess(time.monotonic() - started, 2.0)
        deadline = time.monotonic() + 3
        with self.assertRaises(EOFError):
            while time.monotonic() < deadline:
                stream.next_message()


if __name__ == "__main__":
    unittest.main()
