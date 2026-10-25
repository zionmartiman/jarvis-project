"""JSON Lines storage for the durable conversation memory."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Iterable
from pathlib import Path

from jarvis.ports.memory import MemoryBackend, MemoryEntry


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
        line = json.dumps(entry.as_dict(), ensure_ascii=False, separators=(",", ":"))
        return (line + "\n").encode("utf-8")

    def _write_entries_atomic(self, entries: Iterable[MemoryEntry]) -> None:
        self._write_bytes_atomic(b"".join(self._encode_entry(entry) for entry in entries))

    def _write_bytes_atomic(self, data: bytes, destination: Path | None = None) -> None:
        target = destination or self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
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
