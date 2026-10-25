"""Legacy facade: the memory now lives in jarvis.application.memory.

The old orchestrator still expects the context as ``list[dict]`` with the summary as a first
``{"role": "summary", ...}`` item, so this subclass converts it. Removed with the orchestrator.
"""

from __future__ import annotations

from jarvis.application.memory.conversation_memory import ConversationMemory as _ConversationMemory
from jarvis.infrastructure.memory.jsonl_backend import JsonlMemoryBackend
from jarvis.ports.memory import MemoryBackend, MemoryEntry

__all__ = ["ConversationMemory", "JsonlMemoryBackend", "MemoryBackend", "MemoryEntry"]


class ConversationMemory(_ConversationMemory):
    def get_context(self) -> list[dict[str, str]]:  # type: ignore[override]
        """Return an optional long-term summary and the last complete exchanges."""
        context = super().get_context()
        history: list[dict[str, str]] = []
        if context.summary is not None:
            history.append({"role": "summary", "text": context.summary})
        history.extend({"role": message.role.value, "text": message.text} for message in context.messages)
        return history
