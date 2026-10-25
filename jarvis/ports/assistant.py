"""AI assistant port."""

from __future__ import annotations

from abc import ABC, abstractmethod

from jarvis.domain.conversation import ConversationContext


class AssistantBridge(ABC):
    """Sends a text message to an AI assistant and returns its reply."""

    @abstractmethod
    def ask(self, message: str, context: ConversationContext) -> str:
        raise NotImplementedError
