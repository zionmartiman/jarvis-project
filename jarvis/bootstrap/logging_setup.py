"""Logging configuration for the Jarvis process."""

from __future__ import annotations

import logging
import sys
from typing import TextIO

from jarvis.application.conversation.transcript import TRANSCRIPT_LOGGER_NAME

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(stream: TextIO | None = None) -> None:
    """Log to stdout; the spoken dialogue goes to the same stream as bare ``Yo: ...`` lines."""
    output = stream if stream is not None else sys.stdout
    logging.basicConfig(stream=output, level=logging.INFO, format=_LOG_FORMAT)

    transcript = logging.getLogger(TRANSCRIPT_LOGGER_NAME)
    transcript.setLevel(logging.INFO)
    transcript.propagate = False
    if not transcript.handlers:
        handler = logging.StreamHandler(output)
        handler.setFormatter(logging.Formatter("%(message)s"))
        transcript.addHandler(handler)
