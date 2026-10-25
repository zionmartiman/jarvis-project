"""HTTP server for the rainwater tank dashboard and its JSON API."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from jarvis.domain.tank import TankLevel

DEFAULT_DASHBOARD_PATH = Path(__file__).resolve().parent / "static" / "rainwater_tank.html"

_DASHBOARD_PATHS = ("/", "/index.html")
_LEVEL_PATH = "/api/rainwater-tank/current-level"


class TankWebServer:
    """Serves the dashboard at ``/`` and the latest level at the API path."""

    def __init__(
        self,
        latest_level: Callable[[], TankLevel | None],
        host: str,
        port: int,
        dashboard_path: Path,
    ) -> None:
        self._latest_level = latest_level
        self._host = host
        self._port = port
        self._dashboard_path = dashboard_path
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

        dashboard_html = self._dashboard_path.read_text(encoding="utf-8")
        handler = _build_handler(dashboard_html, self._latest_level)
        self._server = ThreadingHTTPServer((self._host, self._port), handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def _build_handler(
    dashboard_html: str, latest_level: Callable[[], TankLevel | None]
) -> type[BaseHTTPRequestHandler]:
    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in _DASHBOARD_PATHS:
                self._send_html(dashboard_html)
            elif path == _LEVEL_PATH:
                self._send_level()
            else:
                self._send_json(404, b'{"error":"not_found"}')

        def _send_level(self) -> None:
            level = latest_level()
            if level is None:
                self._send_json(200, b'{"error":"measurement_unavailable"}')
            else:
                self._send_json(200, json.dumps(asdict(level)).encode())

        def _send_html(self, html: str) -> None:
            self._send(200, "text/html; charset=utf-8", html.encode())

        def _send_json(self, status: int, body: bytes) -> None:
            self._send(status, "application/json", body)

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    return RequestHandler
