"""The dedicated logger for the spoken dialogue (``Yo: ...`` / ``Gemini: ...`` lines)."""

from __future__ import annotations

import logging

TRANSCRIPT_LOGGER_NAME = "jarvis.transcript"

TRANSCRIPT = logging.getLogger(TRANSCRIPT_LOGGER_NAME)
