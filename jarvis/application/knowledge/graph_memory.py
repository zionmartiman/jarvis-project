"""Knowledge-graph memory: queues each exchange and a worker turns it into graph changes."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jarvis.application.knowledge.extraction_prompt import (
    build_extraction_prompt,
    clip,
    split_summary,
)
from jarvis.domain.knowledge_graph import (
    ROOT_ENTITY_KEY,
    GraphDelta,
    GraphEvent,
    GraphSnapshot,
    KnownGraph,
    format_timestamp,
    is_recall_question,
    normalize_key,
    query_terms,
)
from jarvis.ports.knowledge_graph import (
    GraphExtractor,
    KnowledgeGraphFeed,
    KnowledgeGraphStore,
    PendingExtraction,
    TransientExtractionError,
)

LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class KnowledgeLimits:
    max_candidate_entities: int = 25
    max_candidate_relations: int = 40
    max_context_facts: int = 15
    max_context_chars: int = 1200
    max_pending: int = 200
    max_attempts: int = 5
    retry_delays_seconds: tuple[float, ...] = (30, 120, 600, 1800)
    idle_poll_seconds: float = 30.0
    claim_timeout_seconds: float = 300.0


class KnowledgeGraphMemory(KnowledgeGraphFeed):
    """Never lets a graph failure reach the conversation; the store keeps the pending work."""

    def __init__(
        self,
        store: KnowledgeGraphStore,
        extractor: GraphExtractor,
        limits: KnowledgeLimits = KnowledgeLimits(),
        *,
        extraction_enabled: bool,
        retrieval_enabled: bool,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._extractor = extractor
        self._limits = limits
        self._extraction_enabled = extraction_enabled
        self._retrieval_enabled = retrieval_enabled
        self._clock = clock
        self._wake = threading.Event()
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._changed = threading.Condition()
        self._known_version = 0
        # Entities of the previous extraction, so "ella" or "allí" can be resolved.
        self._last_touched_ids: tuple[int, ...] = ()

    def start(self) -> None:
        """Start the worker; with extraction disabled nothing is queued, so it is not started."""
        if not self._extraction_enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_requested.clear()
        self._thread = threading.Thread(
            target=self._run, name="knowledge-graph-worker", daemon=True
        )
        self._thread.start()

    def close(self, timeout: float = 3.0) -> None:
        self._stop_requested.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def observe_exchange(self, user_text: str, assistant_text: str) -> None:
        """Queue a completed exchange for extraction; never raises."""
        if not self._extraction_enabled:
            return
        try:
            self.enqueue_exchange(user_text, assistant_text, format_timestamp(self._clock()))
        except Exception:
            LOGGER.exception("Unable to queue the exchange for knowledge extraction.")
            return
        self._wake.set()

    def enqueue_exchange(self, user_text: str, assistant_text: str, observed_at: str) -> None:
        self._store.enqueue(
            "exchange", user_text, assistant_text, observed_at, self._limits.max_pending
        )

    def enqueue_summary(self, summary: str, observed_at: str) -> int:
        """Queue the summary one topic at a time (a whole one would be clipped); return how many."""
        sections = split_summary(summary)
        for section in sections:
            self._store.enqueue("summary", section, "", observed_at, self._limits.max_pending)
        return len(sections)

    def context_for(self, query: str) -> str | None:
        """Current facts about the entities the query mentions, as text for Gemini; never raises.

        A question about the conversation itself («¿dónde nos quedamos?») names no entity: it also
        gets the newest facts, after those of any entity it does mention.
        """
        if not self._retrieval_enabled:
            return None
        try:
            limit = self._limits.max_context_facts
            entities = self._store.entities_by_alias_keys(query_terms(query))
            relations = (
                self._store.active_relations([entity.id for entity in entities], limit)
                if entities
                else []
            )
            if is_recall_question(query):
                known = {relation.id for relation in relations}
                relations += [
                    relation
                    for relation in self._store.recent_relations(limit)
                    if relation.id not in known
                ]
                relations = relations[:limit]
            if not relations:
                return None
        except Exception:
            LOGGER.exception("Unable to read the knowledge graph for the query.")
            return None
        lines: list[str] = []
        size = 0
        for relation in relations:
            fact = " ".join(relation.fact.split()).rstrip(".")
            line = f"- {fact}. (desde {relation.valid_from[:10]})"
            size += len(line) + (1 if lines else 0)
            if size > self._limits.max_context_chars:
                break
            lines.append(line)
        if not lines:
            return None
        LOGGER.debug("Knowledge facts sent to the assistant:\n%s", "\n".join(lines))
        return "\n".join(lines)

    def process_pending_once(self) -> bool:
        """Extract the next due item; return False when there was none."""
        now = self._clock()
        item = self._store.claim_next(format_timestamp(now), self._limits.claim_timeout_seconds)
        if item is None:
            return False
        started = time.monotonic()
        try:
            known = self._candidates(item)
            prompt = build_extraction_prompt(known, item.user_text, item.assistant_text, item.kind)
            delta = self._extractor.extract(prompt)
        except TransientExtractionError as error:
            LOGGER.warning(
                "Knowledge extraction %d failed (attempt %d): %s", item.id, item.attempts, error
            )
            self._fail(item, error)
            return True
        except Exception as error:
            LOGGER.exception(
                "Knowledge extraction %d failed unexpectedly (attempt %d).", item.id, item.attempts
            )
            self._fail(item, error)
            return True
        events = self._store.complete(item.id, delta)
        self._publish(events)
        self._remember_touched(delta)
        LOGGER.info(
            "Knowledge extraction took %.1fs, +%d events", time.monotonic() - started, len(events)
        )
        return True

    # KnowledgeGraphFeed

    def snapshot(self) -> GraphSnapshot:
        return self._store.snapshot()

    def events_since(self, version: int, limit: int) -> list[GraphEvent]:
        return self._store.events_since(version, limit)

    def current_version(self) -> int:
        return self._store.current_version()

    def graph_id(self) -> str:
        return self._store.graph_id()

    def wait_for_change(self, after_version: int, timeout: float) -> None:
        """Changes made by this process wake it early; those of other processes wait the timeout."""
        with self._changed:
            self._changed.wait_for(lambda: self._known_version > after_version, timeout)

    # worker

    def _run(self) -> None:
        while not self._stop_requested.is_set():
            try:
                worked = self.process_pending_once()
            except Exception:
                LOGGER.exception("Knowledge graph worker failed.")
                worked = False
            if not worked and not self._stop_requested.is_set():
                self._wake.wait(self._limits.idle_poll_seconds)
                self._wake.clear()

    def _fail(self, item: PendingExtraction, error: Exception) -> None:
        # The clock is read now: the extraction may have taken as long as the Gemini timeout.
        now = self._clock()
        delays = self._limits.retry_delays_seconds
        if item.attempts >= self._limits.max_attempts or not delays:
            retry_at = None
            LOGGER.warning(
                "Knowledge extraction %d gave up after %d attempts; it stays as failed.",
                item.id,
                item.attempts,
            )
        else:
            delay = delays[min(item.attempts - 1, len(delays) - 1)]
            retry_at = format_timestamp(now + timedelta(seconds=delay))
            LOGGER.info("Knowledge extraction %d will be retried at %s.", item.id, retry_at)
        self._store.fail(item.id, f"{type(error).__name__}: {error}", retry_at)

    def _candidates(self, item: PendingExtraction) -> KnownGraph:
        """Entities to show Gemini, found without an LLM: mentions, the root, the last ones."""
        limit = self._limits.max_candidate_entities
        terms = query_terms(clip(item.user_text) + " " + clip(item.assistant_text))
        entities = self._store.entities_by_alias_keys([ROOT_ENTITY_KEY, *terms])
        ids = {entity.id for entity in entities}
        entities += self._store.entities_by_ids(
            [entity_id for entity_id in self._last_touched_ids if entity_id not in ids]
        )
        entities = entities[:limit]
        ids = {entity.id for entity in entities}
        entities += self._store.recent_entities(limit - len(entities), exclude_ids=ids)
        ids = {entity.id for entity in entities}

        relations = self._store.active_relations(ids, self._limits.max_candidate_relations)
        ends = {relation.source_id for relation in relations}
        ends |= {relation.target_id for relation in relations}
        entities += self._store.entities_by_ids(sorted(ends - ids))
        return KnownGraph(entities=tuple(entities), relations=tuple(relations))

    def _remember_touched(self, delta: GraphDelta) -> None:
        # Mentioned entities that did not change produce no event, so the keys are resolved again.
        keys = [proposal.key for proposal in delta.entities]
        for proposal in (*delta.relations, *delta.invalidations):
            keys += [proposal.source, proposal.target]
        entities = self._store.entities_by_alias_keys(normalize_key(key) for key in keys)
        self._last_touched_ids = tuple(entity.id for entity in entities)

    def _publish(self, events: list[GraphEvent]) -> None:
        if not events:
            return
        with self._changed:
            self._known_version = max(self._known_version, events[-1].version)
            self._changed.notify_all()
