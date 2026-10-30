"""Which durable memory flow is used, for saving or for recalling."""

from __future__ import annotations

from enum import Enum


class MemorySource(Enum):
    """A durable memory flow: the plain-text conversation log, the knowledge graph, both or none."""

    NONE = "none"
    # state/conversation.jsonl: the recent exchanges plus the summary Gemini keeps of the older ones.
    CONVERSATION_LOG = "conversation_log"
    # state/knowledge_graph.sqlite3: dated entities and relations extracted by Gemini.
    GRAPH = "graph"
    BOTH = "both"

    @property
    def includes_log(self) -> bool:
        return self in (MemorySource.CONVERSATION_LOG, MemorySource.BOTH)

    @property
    def includes_graph(self) -> bool:
        return self in (MemorySource.GRAPH, MemorySource.BOTH)
