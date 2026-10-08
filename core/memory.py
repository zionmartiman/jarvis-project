"""Durable, bounded conversation memory with replaceable storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
from typing import Callable, Iterable

_LOGGER = logging.getLogger(__name__)
_VALID_ROLES = {"user", "assistant", "summary"}


@dataclass(frozen=True)
class MemoryEntry:
    timestamp: str
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"timestamp": self.timestamp, "role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, value: object) -> "MemoryEntry":
        if not isinstance(value, dict):
            raise ValueError("Cada línea de memoria debe ser un objeto JSON")
        timestamp = value.get("timestamp")
        role = value.get("role")
        content = value.get("content")
        if not all(isinstance(item, str) for item in (timestamp, role, content)):
            raise ValueError("La memoria requiere timestamp, role y content de tipo texto")
        if role not in _VALID_ROLES:
            raise ValueError(f"Rol de memoria no válido: {role}")
        return cls(timestamp=timestamp, role=role, content=content)


class MemoryBackend(ABC):
    """Storage contract; alternate implementations can use a graph database."""

    @abstractmethod
    def read_all(self) -> list[MemoryEntry]:
        """Return entries in chronological order."""

    @abstractmethod
    def append_many(self, entries: Iterable[MemoryEntry]) -> None:
        """Durably append entries in chronological order."""

    @abstractmethod
    def replace_all(self, entries: Iterable[MemoryEntry]) -> None:
        """Atomically replace all entries where the backend supports it."""

    @abstractmethod
    def backup(self) -> None:
        """Create a durable recovery copy before destructive compaction."""

    @abstractmethod
    def size_bytes(self) -> int:
        """Return the current on-disk storage size."""


class JsonlMemoryBackend(MemoryBackend):
    """JSON Lines backend with fsync and atomic full-file replacement."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self._lock = threading.RLock()

    def read_all(self) -> list[MemoryEntry]:
        with self._lock:
            return self._read_all_unlocked()

    def _read_all_unlocked(self) -> list[MemoryEntry]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return []
        if not raw:
            return []

        chunks = raw.splitlines(keepends=True)
        entries: list[MemoryEntry] = []
        for index, chunk in enumerate(chunks):
            is_last = index == len(chunks) - 1
            terminated = chunk.endswith(b"\n")
            line = chunk.rstrip(b"\r\n")
            try:
                value = json.loads(line.decode("utf-8"))
                entry = MemoryEntry.from_dict(value)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                if is_last and not terminated:
                    self._write_entries_atomic(entries)
                    return entries
                raise ValueError(f"Memoria JSONL corrupta en la línea {index + 1}") from error
            entries.append(entry)

        if not raw.endswith(b"\n"):
            self._write_entries_atomic(entries)
        return entries

    def append_many(self, entries: Iterable[MemoryEntry]) -> None:
        serialized = b"".join(self._encode_entry(entry) for entry in entries)
        if not serialized:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                remaining = memoryview(serialized)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("No se pudo completar la escritura de memoria")
                    remaining = remaining[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def replace_all(self, entries: Iterable[MemoryEntry]) -> None:
        serialized = b"".join(self._encode_entry(entry) for entry in entries)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write_bytes_atomic(serialized)

    def backup(self) -> None:
        with self._lock:
            if not self.path.exists():
                return
            self.backup_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_bytes_atomic(self.path.read_bytes(), self.backup_path)

    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    @staticmethod
    def _encode_entry(entry: MemoryEntry) -> bytes:
        return (json.dumps(entry.as_dict(), ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")

    def _write_entries_atomic(self, entries: Iterable[MemoryEntry]) -> None:
        self._write_bytes_atomic(b"".join(self._encode_entry(entry) for entry in entries))

    def _write_bytes_atomic(self, data: bytes, destination: Path | None = None) -> None:
        target = destination or self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, target)
            self._sync_directory(target.parent)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        if os.name != "posix":
            return
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class ConversationMemory:
    """Persist exchanges and expose a summary plus a strict complete-turn window."""

    def __init__(
        self,
        backend: MemoryBackend,
        summarizer: Callable[[str], str] | None = None,
        max_size_bytes: int = 4096,
        compact_after_records: int = 10,
        recent_interactions: int = 5,
    ):
        if max_size_bytes <= 0 or compact_after_records <= 0 or recent_interactions <= 0:
            raise ValueError("Los límites de memoria deben ser positivos")
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

    def get_context(self) -> list[dict[str, str]]:
        """Return an optional long-term summary and the last complete exchanges."""
        with self._lock:
            entries = self._backend.read_all()
        summaries = [entry for entry in entries if entry.role == "summary"]
        messages = [entry for entry in entries if entry.role != "summary"]
        context: list[dict[str, str]] = []
        if summaries:
            context.append({"role": "summary", "text": summaries[-1].content})
        pairs = self._complete_pairs(messages)
        for pair in pairs[-self._recent_interactions :]:
            context.extend({"role": entry.role, "text": entry.content} for entry in pair)
        return context

    def record_exchange(self, user_text: str, assistant_text: str) -> None:
        """Durably append one exchange and schedule compaction when limits are crossed."""
        if not isinstance(user_text, str) or not isinstance(assistant_text, str):
            raise TypeError("Los mensajes de conversación deben ser texto")
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
                summaries = [entry for entry in snapshot if entry.role == "summary"]
                messages = [entry for entry in snapshot if entry.role != "summary"]
                preserved_count = self._recent_interactions * 2
                old_messages = messages[:-preserved_count]
                if not old_messages:
                    return False
                recent_messages = messages[-preserved_count:]

            prompt = self._build_summary_prompt(summaries, old_messages)
            summary_text = self._summarizer(prompt).strip()
            if not summary_text:
                raise ValueError("El sintetizador devolvió un resumen vacío")
            summary = MemoryEntry(
                timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                role="summary",
                content=summary_text,
            )

            with self._lock:
                current = self._backend.read_all()
                if current[: len(snapshot)] != snapshot:
                    return False
                appended = current[len(snapshot) :]
                recent_messages.extend(entry for entry in appended if entry.role != "summary")
                recent_messages = recent_messages[-preserved_count:]
                self._backend.backup()
                self._backend.replace_all([summary, *recent_messages])
            return True

    def _schedule_compaction_if_needed(self) -> None:
        entries = self._backend.read_all()
        if not self._needs_compaction(entries) or self._summarizer is None or self._compaction_running:
            return
        self._compaction_running = True
        threading.Thread(target=self._run_background_compaction, name="conversation-memory-compaction", daemon=True).start()

    def _run_background_compaction(self) -> None:
        try:
            self.compact()
        except Exception:
            _LOGGER.exception("No se pudo compactar la memoria; se conserva el historial original")
        finally:
            with self._lock:
                self._compaction_running = False

    def _needs_compaction(self, entries: list[MemoryEntry]) -> bool:
        message_count = sum(entry.role != "summary" for entry in entries)
        return message_count > self._compact_after_records or self._backend.size_bytes() > self._max_size_bytes

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

    @staticmethod
    def _build_summary_prompt(summaries: list[MemoryEntry], old_messages: list[MemoryEntry]) -> str:
        lines = [
            "Actualiza la memoria duradera del usuario en un único párrafo conciso en español.",
            "Conserva nombres, entidades, preferencias, decisiones y tareas pendientes; no inventes datos.",
        ]
        if summaries:
            lines.extend(["Resumen existente:", summaries[-1].content])
        lines.append("Interacciones antiguas por integrar:")
        lines.extend(f"{entry.role}: {entry.content}" for entry in old_messages)
        return "\n".join(lines)