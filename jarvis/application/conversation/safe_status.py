"""A status indicator decorator that never raises."""

from __future__ import annotations

import logging

from jarvis.domain.assistant_status import AssistantStatus
from jarvis.ports.hardware import StatusIndicator

LOGGER = logging.getLogger(__name__)


class SafeStatusIndicator(StatusIndicator):
    """Forwards the status to another indicator and logs, instead of raising, any failure."""

    def __init__(self, indicator: StatusIndicator) -> None:
        self._indicator = indicator

    def set_status(self, status: AssistantStatus) -> None:
        try:
            self._indicator.set_status(status)
        except Exception as error:
            LOGGER.error("Unable to update the status light: %s", error)
