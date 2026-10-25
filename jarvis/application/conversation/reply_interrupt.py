"""Lets the interrupt button cut the wait for, or the playback of, an assistant reply."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from jarvis.application.conversation.voice import Voice


class ReplyInterruptGate:
    """Tracks one assistant reply cycle and whether the button asked to abandon it."""

    def __init__(self, voice: Voice, shutting_down: threading.Event) -> None:
        self._voice = voice
        self._shutting_down = shutting_down
        self._active = threading.Event()
        self._speaking = threading.Event()
        self._requested = threading.Event()

    @property
    def is_requested(self) -> bool:
        return self._requested.is_set()

    def begin(self) -> None:
        """Open a reply cycle: from now on the button can interrupt it."""
        self._requested.clear()
        self._active.set()

    def end(self) -> None:
        """Close the cycle; a later button press is ignored until the next ``begin``."""
        self._active.clear()
        self._speaking.clear()
        self._requested.clear()

    def request(self) -> None:
        """Called by the button: abandon the reply, cutting the voice if it is being spoken."""
        if self._shutting_down.is_set() or not self._active.is_set():
            return
        self._requested.set()
        if self._speaking.is_set():
            self._voice.interrupt()

    @contextmanager
    def speaking(self) -> Iterator[None]:
        """Mark that the reply is being spoken, so ``request`` also cuts the voice."""
        self._speaking.set()
        try:
            yield
        finally:
            self._speaking.clear()
