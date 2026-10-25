"""Shutdown and reboot of the Raspberry Pi.

The sudo rule that allows these commands must be granted to the user that runs
main.py (see docs/CONTEXTO_DEL_PROYECTO.md).
"""

from __future__ import annotations

import subprocess

from jarvis.ports.system import PowerController


class SudoPowerController(PowerController):
    """Powers the host off or reboots it through passwordless sudo."""

    def shutdown(self) -> None:
        subprocess.run(["sudo", "-n", "/usr/sbin/poweroff"], check=True)

    def reboot(self) -> None:
        subprocess.run(["sudo", "-n", "/usr/sbin/reboot"], check=True)
