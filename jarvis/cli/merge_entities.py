"""Merge a duplicate entity into another: ``python -m jarvis.cli.merge_entities ana_garcia ana``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TextIO

from jarvis.config.settings import load_settings
from jarvis.infrastructure.knowledge.sqlite_store import SqliteKnowledgeGraph


def main(argv: Sequence[str] | None = None, output: TextIO | None = None) -> None:
    out = output if output is not None else sys.stdout
    parser = argparse.ArgumentParser(description="Merge two entities of the knowledge graph.")
    parser.add_argument("source", help="key or alias of the entity that disappears")
    parser.add_argument("target", help="key or alias of the entity that receives everything")
    arguments = parser.parse_args(argv)

    store = SqliteKnowledgeGraph(load_settings().knowledge.path)
    try:
        events = store.merge_entities(arguments.source, arguments.target)
    except ValueError as error:
        raise SystemExit(f"Cannot merge: {error}") from error
    for event in events:
        data = json.dumps(event.data, ensure_ascii=False)
        out.write(f"{event.version} {event.op} {data}\n")


if __name__ == "__main__":
    main()
