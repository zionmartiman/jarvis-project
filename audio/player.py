"""
Reproducción de audio en streaming mediante aplay.

Cualquier motor de voz que entregue audio PCM crudo (16 bits, mono)
puede usar esta clase para reproducirlo fragmento a fragmento, sin
esperar a tener el audio completo. Mantiene la reproducción
desacoplada del SDK concreto de voz (Azure hoy, otro mañana).
"""

from __future__ import annotations

import subprocess


class RawPcmPlayer:
    """Reproduce audio PCM crudo escribiéndolo directamente a aplay."""

    def __init__(
        self,
        output_device: str,
        sample_rate: int = 24000,
        channels: int = 1,
    ):
        self.process = subprocess.Popen(
            [
                "aplay",
                "-q",
                "-D",
                output_device,
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-r",
                str(sample_rate),
                "-c",
                str(channels),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            # Los errores de aplay aparecerán en la terminal o journal.
            stderr=None,
            # Sin búfer de Python para reducir la latencia.
            bufsize=0,
        )

        self.closed = False
        self.write_error: Exception | None = None

    def write(self, audio_buffer) -> int:
        """Escribe un fragmento de audio. Devuelve los bytes escritos."""

        if self.closed or self.process.stdin is None:
            return 0

        try:
            self.process.stdin.write(audio_buffer)
            return len(audio_buffer)
        except (BrokenPipeError, OSError) as error:
            # No propagamos la excepción dentro de un posible hilo
            # interno del SDK que llame a write(). Se guarda y se
            # notifica desde finish().
            self.write_error = error
            return 0

    def close(self) -> None:
        """Cierra la entrada de aplay; deja de aceptar más audio."""

        if self.closed:
            return

        self.closed = True

        if self.process.stdin and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass

    def finish(self) -> None:
        """
        Espera hasta que aplay haya reproducido todo el audio recibido.

        Quien reproduce audio no debe volver a escuchar al usuario
        hasta que esta función haya terminado.
        """

        self.close()
        return_code = self.process.wait()

        if self.write_error:
            raise RuntimeError(
                f"Error enviando audio a aplay: {self.write_error}"
            )

        if return_code != 0:
            raise RuntimeError(f"aplay terminó con código {return_code}")
