"""Queue the JSONL memory for graph extraction: ``python -m jarvis.cli.rebuild_graph``.

Options: ``--reset`` backs the database up and starts an empty graph, ``--process`` empties the
queue in this process and ``--retry-failed`` makes failed items pending again (instead of
queueing the JSONL, so nothing is extracted twice).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TextIO

from jarvis.application.knowledge.graph_memory import KnowledgeGraphMemory, KnowledgeLimits
from jarvis.bootstrap.assistants import build_graph_extractor
from jarvis.bootstrap.logging_setup import configure_logging
from jarvis.config.settings import load_settings
from jarvis.domain.knowledge_graph import format_timestamp
from jarvis.infrastructure.knowledge.sqlite_store import SqliteKnowledgeGraph, backup_and_remove
from jarvis.infrastructure.memory.jsonl_backend import JsonlMemoryBackend
from jarvis.ports.memory import MemoryEntry


def main(argv: Sequence[str] | None = None, output: TextIO | None = None) -> None:
    out = output if output is not None else sys.stdout
    parser = argparse.ArgumentParser(description="Rebuild the Jarvis knowledge graph.")
    parser.add_argument("--reset", action="store_true", help="back up and start an empty graph")
    parser.add_argument("--process", action="store_true", help="extract the queue now")
    parser.add_argument(
        "--retry-failed", action="store_true", help="retry failed items instead of the JSONL"
    )
    arguments = parser.parse_args(argv)
    settings = load_settings()
    path = settings.knowledge.path

    if arguments.reset:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.{stamp}.bak")
        if backup_and_remove(path, backup):
            _write(out, f"Backup written to {backup}; starting an empty graph.")

    store = SqliteKnowledgeGraph(path)
    memory = KnowledgeGraphMemory(
        store,
        build_graph_extractor(settings),
        # A long summary becomes one queue item per topic: do not let the live limit drop any.
        KnowledgeLimits(max_pending=100_000),
        extraction_enabled=True,
        retrieval_enabled=False,
    )

    if arguments.retry_failed:
        _write(out, f"{store.retry_failed()} failed item(s) are pending again.")
    else:
        queued = _queue_jsonl(memory, JsonlMemoryBackend(settings.memory.path).read_all())
        _write(out, f"Queued {queued} item(s) from {settings.memory.path}.")

    if arguments.process:
        processed = 0
        while memory.process_pending_once():
            processed += 1
            _write(out, f"Processed {processed}; {store.pending_count()} still pending.")
    _write(out, f"{store.pending_count()} item(s) pending; version {store.current_version()}.")


def _queue_jsonl(memory: KnowledgeGraphMemory, entries: list[MemoryEntry]) -> int:
    """The last summary, then every complete exchange, each with its own timestamp."""
    queued = 0
    summaries = [entry for entry in entries if entry.role == "summary"]
    if summaries:
        queued += memory.enqueue_summary(summaries[-1].content, _observed_at(summaries[-1]))
    messages = [entry for entry in entries if entry.role != "summary"]
    index = 0
    while index + 1 < len(messages):
        user, assistant = messages[index : index + 2]
        if user.role == "user" and assistant.role == "assistant":
            memory.enqueue_exchange(user.content, assistant.content, _observed_at(user))
            queued += 1
            index += 2
        else:
            index += 1
    return queued


def _observed_at(entry: MemoryEntry) -> str:
    try:
        return format_timestamp(datetime.fromisoformat(entry.timestamp))
    except ValueError:
        return format_timestamp(datetime.now(timezone.utc))


def _write(out: TextIO, line: str) -> None:
    out.write(line + "\n")


if __name__ == "__main__":
    configure_logging()
    main()
