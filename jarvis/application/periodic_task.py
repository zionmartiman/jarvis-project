"""A background thread that runs one action at a fixed interval."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

LOGGER = logging.getLogger(__name__)


class PeriodicTask:
    """Runs ``action`` in a daemon thread, then waits ``interval_seconds``, until closed."""

    def __init__(self, name: str, interval_seconds: float, action: Callable[[], None]) -> None:
        self._name = name
        self._interval_seconds = interval_seconds
        self._action = action
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_requested.clear()
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def close(self, timeout: float = 3.0) -> None:
        self._stop_requested.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stop_requested.is_set():
            try:
                self._action()
            except Exception:
                LOGGER.exception("Periodic task %s failed.", self._name)
            self._stop_requested.wait(self._interval_seconds)
