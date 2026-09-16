"""Local HTTP read API for the rainwater tank level."""

from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

class RainwaterTankHttpServer:
    def __init__(self, latest_level, host="0.0.0.0", port=8765):
        self._latest_level = latest_level
        self._host = host
        self._port = port
        self._server = None
        self._thread = None

    def start(self):
        if self._server is not None:
            return

        latest_level = self._latest_level

        class RequestHandler(BaseHTTPRequestHandler):
            def _send_json(self, status, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.end_headers()

            def do_GET(self):
                if self.path != "/api/rainwater-tank/current-level":
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return

                level = latest_level()
                if level is None:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {"error": "measurement_unavailable"},
                    )
                    return

                self._send_json(HTTPStatus.OK, asdict(level))

            def log_message(self, format, *args):
                return

        self._server = ThreadingHTTPServer(
            (self._host, self._port),
            RequestHandler,
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()

    def close(self):
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()
        self._server = None