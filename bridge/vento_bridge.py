"""Vento bridge for the legacy conversation code.

Wraps jarvis.infrastructure.assistants.vento.VentoAssistant and keeps the legacy
``history: list[dict]`` signature until phase 5.
"""

from __future__ import annotations

from bridge.legacy_context import history_to_context
from config.settings import BridgeCredentials
from core.interfaces import AssistantBridge
from jarvis.infrastructure.assistants.vento import VentoAssistant
from jarvis.infrastructure.assistants.vento_reply_parser import parse_vento_reply


class VentoBridge(AssistantBridge):
    """Envía mensajes al asistente de IA de Vento y devuelve su respuesta."""

    def __init__(
        self,
        credentials: BridgeCredentials,
        history_limit: int,
        timeout_seconds: int = 130,
    ):
        self._assistant = VentoAssistant(credentials, history_limit, timeout_seconds)

    def ask(self, message: str, history: list[dict]) -> str:
        return self._assistant.ask(message, history_to_context(history))

    @staticmethod
    def _extract_reply(body: str, content_type: str) -> str:
        return parse_vento_reply(body, content_type)
