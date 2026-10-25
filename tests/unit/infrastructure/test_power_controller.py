import unittest
from unittest.mock import patch

from jarvis.infrastructure.system.power_controller import SudoPowerController


class SudoPowerControllerTest(unittest.TestCase):
    def test_shutdown_runs_poweroff_through_passwordless_sudo(self) -> None:
        with patch("subprocess.run") as run:
            SudoPowerController().shutdown()

        run.assert_called_once_with(["sudo", "-n", "/usr/sbin/poweroff"], check=True)

    def test_reboot_runs_reboot_through_passwordless_sudo(self) -> None:
        with patch("subprocess.run") as run:
            SudoPowerController().reboot()

        run.assert_called_once_with(["sudo", "-n", "/usr/sbin/reboot"], check=True)


if __name__ == "__main__":
    unittest.main()
