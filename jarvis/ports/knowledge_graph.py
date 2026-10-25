"""Knowledge-graph memory ports: the store with its extraction queue, the extractor and the web feed."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from jarvis.domain.knowledge_graph import Entity, GraphDelta, GraphEvent, GraphSnapshot, Relation


class TransientExtractionError(RuntimeError):
    """Retryable failure (no network, 429, 5xx). Any other exception counts as a failed attempt."""


@dataclass(frozen=True)
class PendingExtraction:
    id: int
    kind: str
    user_text: str
    assistant_text: str
    observed_at: str
    attempts: int


class KnowledgeGraphStore(ABC):
    """Durable graph plus the persistent queue of exchanges waiting to be extracted."""

    @abstractmethod
    def apply(self, delta: GraphDelta, observed_at: str) -> list[GraphEvent]:
        """Apply a delta in one transaction and return the events it produced, in order."""

    @abstractmethod
    def entities_by_alias_keys(self, alias_keys: Iterable[str]) -> list[Entity]:
        """Current (non-merged) entities whose key or alias matches one of the given keys."""

    @abstractmethod
    def recent_entities(self, limit: int, exclude_ids: Collection[int] = ()) -> list[Entity]:
        """Most recently updated current entities."""

    @abstractmethod
    def active_relations(self, entity_ids: Collection[int], limit: int) -> list[Relation]:
        """Current relations touching the entities: both ends first, then one, then newest."""

    @abstractmethod
    def entities_by_ids(self, ids: Collection[int]) -> list[Entity]:
        """The entities with these ids, ordered by id."""

    @abstractmethod
    def merge_entities(self, source_key: str, target_key: str) -> list[GraphEvent]:
        """Move everything from one entity to another and mark the first one as merged."""

    @abstractmethod
    def snapshot(self) -> GraphSnapshot:
        """Current entities and every relation between them, expired ones included."""

    @abstractmethod
    def events_since(self, version: int, limit: int) -> list[GraphEvent]:
        """Events with a version greater than ``version``, oldest first."""

    @abstractmethod
    def current_version(self) -> int:
        """Version of the newest event (0 if there is none)."""

    @abstractmethod
    def graph_id(self) -> str:
        """Identifier of this graph; it changes when the database is rebuilt from scratch."""

    @abstractmethod
    def enqueue(
        self, kind: str, user_text: str, assistant_text: str, observed_at: str, max_pending: int
    ) -> None:
        """Queue an exchange or summary; drops the oldest pending item beyond ``max_pending``."""

    @abstractmethod
    def claim_next(self, now: str, claim_timeout_seconds: float) -> PendingExtraction | None:
        """Atomically take the next due item; a claim older than the timeout can be taken again."""

    @abstractmethod
    def complete(self, item_id: int, delta: GraphDelta) -> list[GraphEvent]:
        """Apply the delta and remove the item in the same transaction."""

    @abstractmethod
    def fail(self, item_id: int, error: str, retry_at: str | None) -> None:
        """Release the item for a retry at ``retry_at``, or mark it as failed when it is None."""

    @abstractmethod
    def retry_failed(self) -> int:
        """Make every failed item pending again with its attempts reset; return how many."""

    @abstractmethod
    def pending_count(self) -> int:
        """Number of items still pending (failed ones are not counted)."""


class GraphExtractor(ABC):
    """Turns an extraction prompt into a graph delta."""

    @abstractmethod
    def extract(self, prompt: str) -> GraphDelta:
        raise NotImplementedError


class KnowledgeGraphFeed(ABC):
    """What the web needs; KnowledgeGraphMemory implements it."""

    @abstractmethod
    def snapshot(self) -> GraphSnapshot:
        raise NotImplementedError

    @abstractmethod
    def events_since(self, version: int, limit: int) -> list[GraphEvent]:
        raise NotImplementedError

    @abstractmethod
    def current_version(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def graph_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def wait_for_change(self, after_version: int, timeout: float) -> None:
        """Return when a version newer than ``after_version`` is known, or after ``timeout``."""
