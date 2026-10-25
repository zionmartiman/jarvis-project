"""Converts the legacy ``list[dict]`` history into a ConversationContext.

Temporary adapter: it disappears with the old conversation code in phase 5.
"""

from __future__ import annotations

from jarvis.domain.conversation import ChatMessage, ConversationContext, Role


def history_to_context(history: list[dict]) -> ConversationContext:
    """The last ``summary`` item becomes the context summary; every other item is a message."""
    summaries = [str(item.get("text", "")) for item in history if item.get("role") == "summary" and item.get("text")]
    messages = tuple(
        ChatMessage(Role.ASSISTANT if item.get("role") == "assistant" else Role.USER, str(item.get("text", "")))
        for item in history
        if item.get("role") != "summary"
    )
    return ConversationContext(messages=messages, summary=summaries[-1] if summaries else None)
