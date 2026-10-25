"""Polls the physical buttons and dispatches each press to its handler."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from jarvis.application.periodic_task import PeriodicTask
from jarvis.ports.hardware import ButtonPanel, ButtonPress

LOGGER = logging.getLogger(__name__)


class ButtonMonitor:
    """Calls the handler registered for each button press reported by the panel."""

    def __init__(
        self,
        panel: ButtonPanel,
        handlers: Mapping[ButtonPress, Callable[[], None]],
        poll_interval_seconds: float,
    ) -> None:
        self._panel = panel
        self._handlers = dict(handlers)
        self._task = PeriodicTask("arduino-button-monitor", poll_interval_seconds, self.poll_once)

    def start(self) -> None:
        self._task.start()

    def close(self) -> None:
        self._task.close(timeout=3.0)

    def poll_once(self) -> None:
        """Handle at most one pending press; a failing handler never stops the monitor."""
        press = self._panel.read_pending_press()
        if press is None:
            return
        LOGGER.info("Button press detected: %s", press.value)
        handler = self._handlers.get(press)
        if handler is None:
            return
        try:
            handler()
        except Exception:
            LOGGER.exception("Unable to handle Arduino button press.")
