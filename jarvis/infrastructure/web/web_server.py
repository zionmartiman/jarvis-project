"""HTTP server for Jarvis's web site: pages, static files and the JSON APIs."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from jarvis.domain.tank import TankLevel
from jarvis.ports.knowledge_graph import KnowledgeGraphFeed

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

    @property
    def port(self) -> int:
        """The bound port; differs from the requested one when that was 0."""
        if self._server is None:
            return self._port
        return self._server.server_address[1]

    def start(self) -> None:
        if self._server is not None:
            return
        handler = _build_handler(self._static_dir, self._latest_level, self._memory_feed)
        self._server = ThreadingHTTPServer((self._host, self._port), handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def _build_handler(
    static_dir: Path,
    latest_level: Callable[[], TankLevel | None],
    memory_feed: KnowledgeGraphFeed | None,
) -> type[BaseHTTPRequestHandler]:
    resolved_static_dir = static_dir.resolve()

    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = unquote(urlparse(self.path).path)
            if path in _PAGES:
                self._send_page(_PAGES[path])
            elif path.startswith(_STATIC_PREFIX):
                self._send_static(path[len(_STATIC_PREFIX) :])
            elif path == _LEVEL_PATH:
                self._send_level()
            elif path.startswith(_MEMORY_PREFIX):
                self._send_memory()
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

        def _send_memory(self) -> None:
            if memory_feed is None:
                self._send_json(503, b'{"error":"memory_unavailable"}')
            else:
                self._send_not_found()

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
