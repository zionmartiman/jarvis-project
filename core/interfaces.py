"""Legacy interface module.

Most contracts now live in jarvis.ports and are re-exported here so the pre-refactor
code keeps working until phase 7. AssistantBridge keeps its legacy ``history`` signature
until the conversation code is rewritten (phase 5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from jarvis.domain.assistant_status import AssistantStatus
from jarvis.ports.hardware import AlertLight, StatusIndicator
from jarvis.ports.speech import SpeechRecognizer, SpeechSynthesizer
from jarvis.ports.system import PowerController as SystemController

__all__ = [
    "AlertLight",
    "AssistantBridge",
    "AssistantStatus",
    "SpeechRecognizer",
    "SpeechSynthesizer",
    "StatusIndicator",
    "SystemController",
]


class AssistantBridge(ABC):
    """Envía mensajes de texto al asistente de IA y recibe su respuesta."""

    @abstractmethod
    def ask(self, message: str, history: list[dict]) -> str:
        """Envía `message` junto al `history` y devuelve la respuesta."""
        raise NotImplementedError
