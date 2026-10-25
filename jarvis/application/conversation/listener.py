"""Listens for one spoken instruction."""

from __future__ import annotations

from jarvis.application.conversation.transcript import TRANSCRIPT
from jarvis.domain.assistant_status import AssistantStatus
from jarvis.ports.hardware import StatusIndicator
from jarvis.ports.speech import SpeechRecognizer


class SentenceListener:
    """Opens the listening state, waits for a sentence and logs what the user said."""

    def __init__(self, recognizer: SpeechRecognizer, status: StatusIndicator) -> None:
        self._recognizer = recognizer
        self._status = status

    def listen(self) -> str:
        self._status.set_status(AssistantStatus.LISTENING)
        sentence = self._recognizer.listen_for_sentence()
        TRANSCRIPT.info("Yo: %s", sentence)
        return sentence
