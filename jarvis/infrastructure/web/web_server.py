"""HTTP server for Jarvis's web site: pages, static files and the JSON APIs."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from jarvis.domain.knowledge_graph import GraphEvent
from jarvis.domain.tank import TankLevel
from jarvis.ports.knowledge_graph import KnowledgeGraphFeed

LOGGER = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

_PAGES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/deposito": "rainwater_tank.html",
    "/memoria": "memoria.html",
}
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
_STATIC_PREFIX = "/static/"
_LEVEL_PATH = "/api/rainwater-tank/current-level"
_MEMORY_PREFIX = "/api/memory/"
_MEMORY_GRAPH_PATH = _MEMORY_PREFIX + "graph"
_MEMORY_EVENTS_PATH = _MEMORY_PREFIX + "events"
_MEMORY_STREAM_PATH = _MEMORY_PREFIX + "stream"

_DEFAULT_EVENTS_LIMIT = 500
_MAX_EVENTS_LIMIT = 1000
_STREAM_BATCH = 200
_MAX_STREAMS = 8
_KEEPALIVE_SECONDS = 15.0
_STREAM_WAIT_SECONDS = 1.0


class JarvisWebServer:
    """Serves the site's pages and static files, plus the tank and memory APIs."""

    def __init__(
        self,
        host: str,
        port: int,
        static_dir: Path,
        latest_level: Callable[[], TankLevel | None],
        memory_feed: KnowledgeGraphFeed | None,
    ) -> None:
        self._host = host
        self._port = port
        self._static_dir = static_dir
        self._latest_level = latest_level
        self._memory_feed = memory_feed
        self._server: ThreadingHTTPServer | None = None
        self._stop_streams = threading.Event()

    @property
    def port(self) -> int:
        """The bound port; differs from the requested one when that was 0."""
        if self._server is None:
            return self._port
        return self._server.server_address[1]

    def start(self) -> None:
        if self._server is not None:
            return
        self._stop_streams = threading.Event()
        handler = _build_handler(
            self._static_dir, self._latest_level, self._memory_feed, self._stop_streams
        )
        self._server = ThreadingHTTPServer((self._host, self._port), handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        if self._server is not None:
            # Open event streams look at this at least once a second and end on their own.
            self._stop_streams.set()
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def _build_handler(
    static_dir: Path,
    latest_level: Callable[[], TankLevel | None],
    memory_feed: KnowledgeGraphFeed | None,
    stop_streams: threading.Event,
) -> type[BaseHTTPRequestHandler]:
    resolved_static_dir = static_dir.resolve()
    stream_slots = threading.BoundedSemaphore(_MAX_STREAMS)

    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path in _PAGES:
                self._send_page(_PAGES[path])
            elif path.startswith(_STATIC_PREFIX):
                self._send_static(path[len(_STATIC_PREFIX) :])
            elif path == _LEVEL_PATH:
                self._send_level()
            elif path.startswith(_MEMORY_PREFIX):
                self._send_memory(path, parse_qs(parsed.query))
            else:
                self._send_not_found()

        def _send_page(self, filename: str) -> None:
            try:
                html = (static_dir / filename).read_text(encoding="utf-8")
            except OSError:
                self._send_not_found()
                return
            self._send(200, "text/html; charset=utf-8", html.encode("utf-8"), "no-store")

        def _send_static(self, relative_path: str) -> None:
            content_type = _STATIC_TYPES.get(Path(relative_path).suffix.lower())
            candidate = (static_dir / relative_path).resolve()
            if (
                content_type is None
                or not candidate.is_relative_to(resolved_static_dir)
                or not candidate.is_file()
            ):
                self._send_not_found()
                return
            cache = (
                "public, max-age=86400"
                if "vendor" in candidate.relative_to(resolved_static_dir).parts
                else "no-cache"
            )
            self._send(200, content_type, candidate.read_bytes(), cache)

        def _send_level(self) -> None:
            level = latest_level()
            if level is None:
                self._send_json(200, b'{"error":"measurement_unavailable"}')
            else:
                self._send_json(200, json.dumps(asdict(level)).encode())

        def _send_memory(self, path: str, query: dict[str, list[str]]) -> None:
            if memory_feed is None:
                self._send_json(503, b'{"error":"memory_unavailable"}')
            elif path == _MEMORY_GRAPH_PATH:
                self._send_memory_json(lambda: self._memory_graph(memory_feed))
            elif path == _MEMORY_EVENTS_PATH:
                self._send_memory_json(lambda: self._memory_events(memory_feed, query))
            elif path == _MEMORY_STREAM_PATH:
                self._stream_memory(memory_feed, query)
            else:
                self._send_not_found()

        def _send_memory_json(self, build: Callable[[], tuple[int, bytes]]) -> None:
            try:
                status, body = build()
            except Exception:
                LOGGER.exception("Memory request %s failed.", self.path)
                self._send_json(500, b'{"error":"memory_error"}')
                return
            self._send_json(status, body)

        def _memory_graph(self, feed: KnowledgeGraphFeed) -> tuple[int, bytes]:
            snapshot = feed.snapshot()
            return 200, _dump(
                {
                    "graph_id": snapshot.graph_id,
                    "version": snapshot.version,
                    "nodes": list(snapshot.nodes),
                    "links": list(snapshot.links),
                }
            )

        def _memory_events(
            self, feed: KnowledgeGraphFeed, query: dict[str, list[str]]
        ) -> tuple[int, bytes]:
            since = _int_parameter(query, "since", 0, minimum=0)
            limit = _int_parameter(query, "limit", _DEFAULT_EVENTS_LIMIT, minimum=1)
            if since is None or limit is None:
                return 400, b'{"error":"bad_request"}'
            events = feed.events_since(since, min(limit, _MAX_EVENTS_LIMIT))
            return 200, _dump(
                {
                    "graph_id": feed.graph_id(),
                    "events": [_event_json(event) for event in events],
                    "next": events[-1].version if events else since,
                }
            )

        def _stream_memory(self, feed: KnowledgeGraphFeed, query: dict[str, list[str]]) -> None:
            # A reconnecting EventSource sends Last-Event-ID, which wins over ?since=.
            last_event_id = self.headers.get("Last-Event-ID")
            if last_event_id is not None:
                since = _parse_int(last_event_id, minimum=0)
            else:
                since = _int_parameter(query, "since", 0, minimum=0)
            if since is None:
                self._send_json(400, b'{"error":"bad_request"}')
                return
            if not stream_slots.acquire(blocking=False):
                self._send_json(503, b'{"error":"too_many_streams"}')
                return
            try:
                self._run_stream(feed, since)
            except ConnectionError:
                pass  # the browser went away
            except Exception:
                LOGGER.exception("Memory event stream failed.")
            finally:
                stream_slots.release()

        def _run_stream(self, feed: KnowledgeGraphFeed, since: int) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            if since > feed.current_version():  # the database was rebuilt
                self._write_event("reset", None, b"{}")
                return
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            version = since
            last_write = time.monotonic()
            while not stop_streams.is_set():
                events = feed.events_since(version, _STREAM_BATCH)
                for event in events:
                    self._write_event("graph", event.version, _dump(_event_json(event)))
                    version = event.version
                    last_write = time.monotonic()
                if len(events) == _STREAM_BATCH:
                    continue
                if time.monotonic() - last_write >= _KEEPALIVE_SECONDS:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_write = time.monotonic()
                feed.wait_for_change(version, timeout=_STREAM_WAIT_SECONDS)

        def _write_event(self, name: str, event_id: int | None, data: bytes) -> None:
            message = b"" if event_id is None else b"id: %d\n" % event_id
            self.wfile.write(message + b"event: %s\ndata: " % name.encode() + data + b"\n\n")
            self.wfile.flush()

        def _send_not_found(self) -> None:
            self._send_json(404, b'{"error":"not_found"}')

        def _send_json(self, status: int, body: bytes) -> None:
            self._send(status, "application/json", body, "no-store")

        def _send(self, status: int, content_type: str, body: bytes, cache: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    return RequestHandler


def _dump(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _event_json(event: GraphEvent) -> dict:
    return {"version": event.version, "ts": event.ts, "op": event.op, "data": event.data}


def _parse_int(text: str, minimum: int) -> int | None:
    try:
        value = int(text)
    except ValueError:
        return None
    return value if value >= minimum else None


def _int_parameter(
    query: dict[str, list[str]], name: str, default: int, minimum: int
) -> int | None:
    """The integer in the query string, ``default`` if absent, or None if it is not valid."""
    values = query.get(name)
    return default if not values else _parse_int(values[0], minimum)
