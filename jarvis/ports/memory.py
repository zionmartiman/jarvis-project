"""Durable conversation memory port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from collections.abc import Iterable

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
