"""Durable, bounded conversation memory with replaceable storage backends."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from jarvis.application.memory.summary_prompt import build_summary_prompt
from jarvis.domain.conversation import ChatMessage, ConversationContext, Role
from jarvis.ports.memory import MemoryBackend, MemoryEntry

LOGGER = logging.getLogger(__name__)

_SUMMARY_ROLE = "summary"


class ConversationMemory:
    """Persist exchanges and expose a summary plus a strict complete-turn window."""

    def __init__(
        self,
        backend: MemoryBackend,
        summarizer: Callable[[str], str] | None = None,
        max_size_bytes: int = 4096,
        compact_after_records: int = 10,
        recent_interactions: int = 5,
    ) -> None:
        if max_size_bytes <= 0 or compact_after_records <= 0 or recent_interactions <= 0:
            raise ValueError("Memory limits must be positive")
        self._backend = backend
        self._summarizer = summarizer
        self._max_size_bytes = max_size_bytes
        self._compact_after_records = compact_after_records
        self._recent_interactions = recent_interactions
        self._lock = threading.RLock()
        self._compaction_lock = threading.Lock()
        self._compaction_running = False
        with self._lock:
            self._schedule_compaction_if_needed()

    def get_context(self) -> ConversationContext:
        """Return the last long-term summary and the last complete exchanges."""
        with self._lock:
            entries = self._backend.read_all()
        summaries = [entry for entry in entries if entry.role == _SUMMARY_ROLE]
        messages = [entry for entry in entries if entry.role != _SUMMARY_ROLE]
        recent_pairs = self._complete_pairs(messages)[-self._recent_interactions :]
        return ConversationContext(
            messages=tuple(
                ChatMessage(Role(entry.role), entry.content)
                for pair in recent_pairs
                for entry in pair
            ),
            summary=summaries[-1].content if summaries else None,
        )

    def record_exchange(self, user_text: str, assistant_text: str) -> None:
        """Durably append one exchange and schedule compaction when limits are crossed."""
        if not isinstance(user_text, str) or not isinstance(assistant_text, str):
            raise TypeError("Conversation messages must be text")
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entries = [
            MemoryEntry(timestamp=timestamp, role="user", content=user_text),
            MemoryEntry(timestamp=timestamp, role="assistant", content=assistant_text),
        ]
        with self._lock:
            self._backend.append_many(entries)
            self._schedule_compaction_if_needed()

    def compact(self) -> bool:
        """Summarize old entries and atomically replace them; return whether it changed."""
        if self._summarizer is None:
            return False
        with self._compaction_lock:
            with self._lock:
                snapshot = self._backend.read_all()
                if not self._needs_compaction(snapshot):
                    return False
                summaries = [entry for entry in snapshot if entry.role == _SUMMARY_ROLE]
                messages = [entry for entry in snapshot if entry.role != _SUMMARY_ROLE]
                preserved_count = self._recent_interactions * 2
                old_messages = messages[:-preserved_count]
                if not old_messages:
                    return False
                recent_messages = messages[-preserved_count:]

            previous_summary = summaries[-1].content if summaries else None
            prompt = build_summary_prompt(previous_summary, old_messages)
            summary_text = self._summarizer(prompt).strip()
            if not summary_text:
                raise ValueError("The summarizer returned an empty summary")
            summary = MemoryEntry(
                timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                role=_SUMMARY_ROLE,
                content=summary_text,
            )

            with self._lock:
                current = self._backend.read_all()
                if current[: len(snapshot)] != snapshot:
                    return False
                appended = current[len(snapshot) :]
                recent_messages.extend(
                    entry for entry in appended if entry.role != _SUMMARY_ROLE
                )
                recent_messages = recent_messages[-preserved_count:]
                self._backend.backup()
                self._backend.replace_all([summary, *recent_messages])
            return True

    def _schedule_compaction_if_needed(self) -> None:
        entries = self._backend.read_all()
        if (
            not self._needs_compaction(entries)
            or self._summarizer is None
            or self._compaction_running
        ):
            return
        self._compaction_running = True
        threading.Thread(
            target=self._run_background_compaction,
            name="conversation-memory-compaction",
            daemon=True,
        ).start()

    def _run_background_compaction(self) -> None:
        try:
            self.compact()
        except Exception as error:
            LOGGER.warning("Unable to compact the memory; keeping the original history: %s", error)
        finally:
            with self._lock:
                self._compaction_running = False

    def _needs_compaction(self, entries: list[MemoryEntry]) -> bool:
        message_count = sum(entry.role != _SUMMARY_ROLE for entry in entries)
        return (
            message_count > self._compact_after_records
            or self._backend.size_bytes() > self._max_size_bytes
        )

    @staticmethod
    def _complete_pairs(messages: list[MemoryEntry]) -> list[tuple[MemoryEntry, MemoryEntry]]:
        pairs: list[tuple[MemoryEntry, MemoryEntry]] = []
        index = 0
        while index + 1 < len(messages):
            first, second = messages[index : index + 2]
            if first.role == "user" and second.role == "assistant":
                pairs.append((first, second))
                index += 2
            else:
                index += 1
        return pairs
