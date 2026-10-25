import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.infrastructure.ipc.alert_light_client import AlertLightClient
from jarvis.infrastructure.ipc.alert_light_server import AlertLightControlServer
from jarvis.infrastructure.ipc.announcer import SocketAnnouncer
from jarvis.infrastructure.ipc.unix_datagram import UnixDatagramServer, send_datagram
from jarvis.ports.hardware import AlertLight

has_unix_sockets = unittest.skipUnless(
    hasattr(socket, "AF_UNIX"), "Unix datagram sockets are only available on Linux"
)


class RecordingAlertLight(AlertLight):
    def __init__(self) -> None:
        self.states: list[bool] = []
        self.changed = threading.Event()

    def set_alert_active(self, is_active: bool) -> None:
        self.states.append(is_active)
        self.changed.set()


def socket_directory(test: unittest.TestCase) -> Path:
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    return Path(directory.name)


@has_unix_sockets
class UnixDatagramServerTest(unittest.TestCase):
    def test_delivers_each_datagram_to_the_handler_and_removes_the_socket_on_close(self) -> None:
        path = socket_directory(self) / "run" / "test.sock"
        received: list[bytes] = []
        arrived = threading.Event()

        def handler(payload: bytes) -> None:
            received.append(payload)
            arrived.set()

        server = UnixDatagramServer(path, 64, handler, "test-datagram")
        server.start()
        self.addCleanup(server.close)

        send_datagram(path, b"hola")

        self.assertTrue(arrived.wait(timeout=2))
        self.assertEqual(received, [b"hola"])
        server.close()
        self.assertFalse(path.exists())

    def test_a_failing_handler_does_not_stop_the_receiver(self) -> None:
        path = socket_directory(self) / "test.sock"
        received: list[bytes] = []
        second_arrived = threading.Event()

        def handler(payload: bytes) -> None:
            received.append(payload)
            if payload == b"first":
                raise ValueError("boom")
            second_arrived.set()

        server = UnixDatagramServer(path, 64, handler, "test-datagram")
        server.start()
        self.addCleanup(server.close)

        with self.assertLogs("jarvis.infrastructure.ipc.unix_datagram", level="ERROR"):
            send_datagram(path, b"first")
            send_datagram(path, b"second")
            self.assertTrue(second_arrived.wait(timeout=2))

        self.assertEqual(received, [b"first", b"second"])

    def test_send_to_a_missing_socket_raises_oserror(self) -> None:
        with self.assertRaises(OSError):
            send_datagram(socket_directory(self) / "missing.sock", b"x")


@has_unix_sockets
class AlertLightControlServerTest(unittest.TestCase):
    def start(self) -> tuple[RecordingAlertLight, Path]:
        path = socket_directory(self) / "control.sock"
        light = RecordingAlertLight()
        server = AlertLightControlServer(light, path)
        server.start()
        self.addCleanup(server.close)
        return light, path

    def test_valid_commands_switch_the_light(self) -> None:
        light, path = self.start()

        AlertLightClient(path).set_alert_active(True)
        self.assertTrue(light.changed.wait(timeout=2))
        light.changed.clear()
        AlertLightClient(path).set_alert_active(False)
        self.assertTrue(light.changed.wait(timeout=2))

        self.assertEqual(light.states, [True, False])

    def test_invalid_commands_are_rejected_with_a_warning(self) -> None:
        light, path = self.start()
        invalid = [b"not json", b'{"alert_active": "yes"}', b'{"other": true}', b"[1]", b"\xff"]

        with self.assertLogs("jarvis.infrastructure.ipc.alert_light_server", level="WARNING") as logs:
            for payload in invalid:
                send_datagram(path, payload)
            send_datagram(path, json.dumps({"alert_active": True}).encode("utf-8"))
            self.assertTrue(light.changed.wait(timeout=2))

        self.assertEqual(light.states, [True])
        self.assertEqual(len(logs.output), len(invalid))


class AlertLightClientTest(unittest.TestCase):
    def test_sends_the_alert_state_as_json(self) -> None:
        with patch("jarvis.infrastructure.ipc.alert_light_client.send_datagram") as send:
            AlertLightClient(Path("/tmp/control.sock")).set_alert_active(True)

        send.assert_called_once_with(Path("/tmp/control.sock"), b'{"alert_active": true}')

    def test_an_unavailable_light_is_only_a_warning(self) -> None:
        with patch(
            "jarvis.infrastructure.ipc.alert_light_client.send_datagram", side_effect=OSError("gone")
        ):
            with self.assertLogs("jarvis.infrastructure.ipc.alert_light_client", level="WARNING"):
                AlertLightClient(Path("/tmp/control.sock")).set_alert_active(False)


class SocketAnnouncerTest(unittest.TestCase):
    def test_sends_the_text_as_utf8_json(self) -> None:
        with patch("jarvis.infrastructure.ipc.announcer.send_datagram") as send:
            SocketAnnouncer(Path("/tmp/announcer.sock")).announce("Depósito lleno.")

        path, payload = send.call_args.args
        self.assertEqual(path, Path("/tmp/announcer.sock"))
        self.assertEqual(json.loads(payload.decode("utf-8")), {"text": "Depósito lleno."})
        self.assertIn("Depósito".encode("utf-8"), payload)

    def test_a_missing_service_logs_one_warning_line_without_traceback(self) -> None:
        with patch("jarvis.infrastructure.ipc.announcer.send_datagram", side_effect=OSError("refused")):
            with self.assertLogs("jarvis.infrastructure.ipc.announcer", level="WARNING") as logs:
                SocketAnnouncer(Path("/tmp/announcer.sock")).announce("Hola")

        self.assertEqual(len(logs.records), 1)
        self.assertIsNone(logs.records[0].exc_info)
        self.assertIn("refused", logs.output[0])


if __name__ == "__main__":
    unittest.main()
