"""Conversation data: messages, the context sent to an assistant and the short-term history."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    text: str


@dataclass(frozen=True)
class ConversationContext:
    """What an assistant receives besides the new message."""

    messages: tuple[ChatMessage, ...] = ()
    summary: str | None = None
    knowledge: str | None = None


class ShortTermHistory:
    """The last few messages of the active conversation, discarded on standby."""

    def __init__(self, max_messages: int) -> None:
        if max_messages < 1:
            raise ValueError("max_messages must be at least 1")
        self._max_messages = max_messages
        self._messages: list[ChatMessage] = []

    def add_exchange(self, user_text: str, reply: str) -> None:
        self._messages.append(ChatMessage(Role.USER, user_text))
        self._messages.append(ChatMessage(Role.ASSISTANT, reply))
        del self._messages[: -self._max_messages]

    def as_context(self) -> ConversationContext:
        return ConversationContext(messages=tuple(self._messages))
