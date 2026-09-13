"""
Acciones privilegiadas sobre la Raspberry: apagar y reiniciar.

Implementa SystemController. Los permisos especiales de sudo (ver
README.md) deben apuntar al proceso que ejecuta main.py, que es quien
termina invocando estas funciones.
"""

from __future__ import annotations

import subprocess

from core.interfaces import SystemController


class RaspberryPowerController(SystemController):
    """Apaga o reinicia la Raspberry usando sudo sin contraseña."""

    def shutdown(self) -> None:
        subprocess.run(["sudo", "-n", "/usr/sbin/poweroff"], check=True)

    def reboot(self) -> None:
        subprocess.run(["sudo", "-n", "/usr/sbin/reboot"], check=True)
