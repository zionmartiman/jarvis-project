"""Durable, bounded conversation memory with replaceable storage backends."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
from typing import Callable

from jarvis.infrastructure.memory.jsonl_backend import JsonlMemoryBackend
from jarvis.ports.memory import MemoryBackend, MemoryEntry

__all__ = ["ConversationMemory", "JsonlMemoryBackend", "MemoryBackend", "MemoryEntry"]

_LOGGER = logging.getLogger(__name__)


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
        except Exception as error:
            _LOGGER.warning("No se pudo compactar la memoria; se conserva el historial original: %s", error)
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
            "Eres el actualizador de una memoria duradera acumulativa. Responde siempre en español.",
            "Devuelve la memoria completa y actualizada, no una explicación ni un resumen de tu proceso.",
            "Organiza el resultado en conceptos independientes con títulos descriptivos: Tema: contenido.",
            "Separa cada concepto con el delimitador literal ||. No escribas un único párrafo que mezcle temas.",
            "Considera el resumen actual como memoria válida y preserva todos sus hechos, nombres, decisiones, preferencias y tareas pendientes.",
            "Integra mensajes nuevos en una sección existente solo si pertenecen claramente al mismo concepto y la actualización es inequívoca.",
            "Si hay duda, conserva intacta la sección anterior y añade otra sección nueva; es preferible acumular que fusionar o perder información.",
            "No infieras relaciones entre temas, no conviertas posibilidades en hechos y no elimines información por brevedad.",
            "Si dos mensajes se contradicen, conserva ambos con una indicación temporal o de cambio; no elijas uno sin evidencia.",
            "No impongas límite de longitud. Mantén secciones legibles y concretas, sin duplicar literalmente información nueva.",
        ]
        if summaries:
            lines.extend(["<MEMORIA_ACTUAL_INMUTABLE_HASTA_ACTUALIZACION>", summaries[-1].content,
                          "</MEMORIA_ACTUAL_INMUTABLE_HASTA_ACTUALIZACION>"])
        lines.append("<CONVERSACIONES_NUEVAS_EVIDENCIA_NO_MEZCLAR>")
        lines.extend(f"{entry.role}: {entry.content}" for entry in old_messages)
        lines.append("</CONVERSACIONES_NUEVAS_EVIDENCIA_NO_MEZCLAR>")
        return "\n".join(lines)