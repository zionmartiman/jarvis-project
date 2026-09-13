"""PCM audio playback through aplay with process-wide serialization."""

from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path


class PlaybackLock:
    """Serializes speaker access between voice replies and announcements."""

    _PATH = Path("/run/user") / str(os.getuid()) / "jarvis-speech.lock"

    def __enter__(self) -> None:
        self._PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._handle = self._PATH.open("a+", encoding="utf-8")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()


class RawPcmPlayer:
    """Reproduces raw PCM audio by streaming it directly to aplay."""

    def __init__(
        self,
        output_device: str,
        sample_rate: int = 24000,
        channels: int = 1,
    ):
        self.process = subprocess.Popen(
            [
                "aplay", "-q", "-D", output_device, "-t", "raw",
                "-f", "S16_LE", "-r", str(sample_rate),
                "-c", str(channels),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=None,
            bufsize=0,
        )
        self.closed = False
        self.write_error: Exception | None = None

    def write(self, audio_buffer) -> int:
        if self.closed or self.process.stdin is None:
            return 0
        try:
            self.process.stdin.write(audio_buffer)
            return len(audio_buffer)
        except (BrokenPipeError, OSError) as error:
            self.write_error = error
            return 0

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.process.stdin and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass

    def finish(self) -> None:
        self.close()
        return_code = self.process.wait()
        if self.write_error:
            raise RuntimeError(f"Error sending audio to aplay: {self.write_error}")
        if return_code != 0:
            raise RuntimeError(f"aplay exited with code {return_code}")
