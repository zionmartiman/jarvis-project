import base64
import importlib
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.cli import announce
from jarvis.config.settings import load_settings


class AnnounceCliTest(unittest.TestCase):
    def test_decodes_the_text_and_queues_it_on_the_announcement_socket(self) -> None:
        encoded = base64.b64encode("Prueba de aviso ñ".encode("utf-8")).decode("ascii")

        with patch("jarvis.cli.announce.SocketAnnouncer") as announcer_class:
            announce.main(["--base64", encoded])

        announcer_class.assert_called_once_with(load_settings().announcements.socket_path)
        announcer_class.return_value.announce.assert_called_once_with("Prueba de aviso ñ")

    def test_rejects_text_that_is_not_valid_base64(self) -> None:
        with patch("jarvis.cli.announce.SocketAnnouncer") as announcer_class:
            with self.assertRaises(SystemExit) as raised:
                announce.main(["--base64", "***"])

        self.assertEqual(str(raised.exception), "Invalid announcement payload.")
        announcer_class.assert_not_called()

    def test_rejects_base64_that_is_not_utf8(self) -> None:
        encoded = base64.b64encode(b"\xff\xfe").decode("ascii")

        with self.assertRaises(SystemExit):
            announce.main(["--base64", encoded])


class DeprecatedShimsTest(unittest.TestCase):
    def test_announcement_client_shim_delegates_to_the_new_cli_and_socket_announcer(self) -> None:
        client = importlib.import_module("notifications.announcement_client")

        self.assertIs(client.main, announce.main)
        with patch("notifications.announcement_client.SocketAnnouncer") as announcer_class:
            client.enqueue("Aviso")

        announcer_class.assert_called_once_with(load_settings().announcements.socket_path)
        announcer_class.return_value.announce.assert_called_once_with("Aviso")

    def test_announcement_service_shim_delegates_to_the_new_service(self) -> None:
        service = importlib.import_module("notifications.announcement_service")
        new_service = importlib.import_module("jarvis.services.announcement_service")

        self.assertIs(service.main, new_service.main)

    def test_shims_stay_tiny(self) -> None:
        folder = Path(__file__).resolve().parents[3] / "notifications"

        for name in ("announcement_client.py", "announcement_service.py"):
            with self.subTest(name=name):
                lines = (folder / name).read_text(encoding="utf-8").splitlines()
                self.assertLess(len(lines), 20)
                self.assertIn("Deprecated", lines[0])


if __name__ == "__main__":
    unittest.main()
