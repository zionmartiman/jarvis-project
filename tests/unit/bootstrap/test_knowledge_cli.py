import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jarvis.application.knowledge.graph_memory import KnowledgeGraphMemory
from jarvis.bootstrap.app import build_knowledge
from jarvis.cli import merge_entities, rebuild_graph
from jarvis.config.settings import load_settings
from jarvis.domain.knowledge_graph import EntityProposal, EntityType, GraphDelta
from jarvis.infrastructure.knowledge.sqlite_store import SqliteKnowledgeGraph
from jarvis.ports.knowledge_graph import GraphExtractor

SUMMARY_OLD = {"timestamp": "2026-10-01T09:00:00+00:00", "role": "summary", "content": "viejo"}
SUMMARY = {"timestamp": "2026-10-02T09:00:00+00:00", "role": "summary", "content": "Ana vive en Valencia."}
EXCHANGE = [
    {"timestamp": "2026-10-03T10:00:00+00:00", "role": "user", "content": "Mi hermana es Ana"},
    {"timestamp": "2026-10-03T10:00:00+00:00", "role": "assistant", "content": "Vale."},
    {"timestamp": "2026-10-03T11:00:00+00:00", "role": "user", "content": "sin respuesta"},
    {"timestamp": "2026-10-04T12:30:00.123456+00:00", "role": "user", "content": "¿Y Ana?"},
    {"timestamp": "2026-10-04T12:30:00+00:00", "role": "assistant", "content": "En Valencia."},
]


class ListExtractor(GraphExtractor):
    def __init__(self, *deltas: GraphDelta) -> None:
        self.deltas = list(deltas)
        self.prompts: list[str] = []

    def extract(self, prompt: str) -> GraphDelta:
        self.prompts.append(prompt)
        return self.deltas.pop(0) if self.deltas else GraphDelta()


def person(key: str, name: str) -> EntityProposal:
    return EntityProposal(key, name, EntityType.PERSONA)


class KnowledgeCliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.settings = load_settings(self.base)
        self.graph_path = self.settings.knowledge.path
        self.extractor = ListExtractor()
        for target, value in (
            ("jarvis.cli.rebuild_graph.load_settings", self.settings),
            ("jarvis.cli.merge_entities.load_settings", self.settings),
            ("jarvis.cli.rebuild_graph.build_graph_extractor", self.extractor),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_jsonl(self, entries: list[dict]) -> None:
        self.settings.memory.path.parent.mkdir(parents=True, exist_ok=True)
        lines = "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries)
        self.settings.memory.path.write_text(lines, encoding="utf-8")

    def run_rebuild(self, *argv: str) -> str:
        output = io.StringIO()
        rebuild_graph.main(list(argv), output)
        return output.getvalue()

    def queue(self) -> list[tuple]:
        with closing(sqlite3.connect(self.graph_path)) as connection:
            return connection.execute(
                "SELECT kind, user_text, assistant_text, observed_at, status "
                "FROM extraction_queue ORDER BY id"
            ).fetchall()


class RebuildGraphTest(KnowledgeCliTestCase):
    def test_queues_the_last_summary_and_every_complete_exchange_with_its_moment(self) -> None:
        self.write_jsonl([SUMMARY_OLD, SUMMARY, *EXCHANGE])

        output = self.run_rebuild()

        self.assertEqual(
            self.queue(),
            [
                ("summary", "Ana vive en Valencia.", "", "2026-10-02T09:00:00+00:00", "pending"),
                ("exchange", "Mi hermana es Ana", "Vale.", "2026-10-03T10:00:00+00:00", "pending"),
                ("exchange", "¿Y Ana?", "En Valencia.", "2026-10-04T12:30:00+00:00", "pending"),
            ],
        )
        self.assertIn("Queued 3 item(s)", output)
        self.assertEqual(self.extractor.prompts, [])

    def test_without_a_jsonl_nothing_is_queued(self) -> None:
        output = self.run_rebuild()

        self.assertEqual(self.queue(), [])
        self.assertIn("Queued 0 item(s)", output)

    def test_process_empties_the_queue_in_this_process(self) -> None:
        self.write_jsonl([SUMMARY, *EXCHANGE[:2]])
        self.extractor.deltas = [GraphDelta(entities=(person("ana", "Ana"),))]

        output = self.run_rebuild("--process")

        self.assertEqual(self.queue(), [])
        self.assertEqual(len(self.extractor.prompts), 2)
        self.assertIn("Resumen de memoria a analizar:", self.extractor.prompts[0])
        self.assertIn("Processed 2; 0 still pending.", output)
        keys = [node["key"] for node in SqliteKnowledgeGraph(self.graph_path).snapshot().nodes]
        self.assertEqual(keys, ["usuario", "ana"])

    def test_retry_failed_requeues_failed_items_instead_of_the_jsonl(self) -> None:
        self.write_jsonl(EXCHANGE[:2])
        store = SqliteKnowledgeGraph(self.graph_path)
        store.enqueue("exchange", "uno", "vale", "2026-10-01T00:00:00+00:00", 10)
        item = store.claim_next("2999-01-01T00:00:00+00:00", 300)
        store.fail(item.id, "sin red", retry_at=None)

        output = self.run_rebuild("--retry-failed")

        self.assertEqual([row[1:] for row in self.queue()], [("uno", "vale", "2026-10-01T00:00:00+00:00", "pending")])
        self.assertIn("1 failed item(s) are pending again.", output)

    def test_reset_backs_up_the_database_and_starts_an_empty_graph(self) -> None:
        old = SqliteKnowledgeGraph(self.graph_path)
        old.apply(GraphDelta(entities=(person("ana", "Ana"),)), "2026-10-01T00:00:00+00:00")
        old_id = old.snapshot().graph_id

        output = self.run_rebuild("--reset")

        [backup] = self.graph_path.parent.glob("knowledge_graph.sqlite3.*.bak")
        self.assertIn(f"Backup written to {backup}", output)
        self.assertIn("ana", [node["key"] for node in SqliteKnowledgeGraph(backup).snapshot().nodes])
        fresh = SqliteKnowledgeGraph(self.graph_path).snapshot()
        self.assertNotEqual(fresh.graph_id, old_id)
        self.assertEqual([node["key"] for node in fresh.nodes], ["usuario"])

    def test_reset_without_a_database_just_starts_one(self) -> None:
        output = self.run_rebuild("--reset")

        self.assertNotIn("Backup", output)
        self.assertTrue(self.graph_path.exists())


class MergeEntitiesCliTest(KnowledgeCliTestCase):
    def test_prints_the_events_of_the_merge(self) -> None:
        store = SqliteKnowledgeGraph(self.graph_path)
        store.apply(
            GraphDelta(entities=(person("ana", "Ana"), person("ana_garcia", "Ana García"))),
            "2026-10-01T00:00:00+00:00",
        )
        output = io.StringIO()

        merge_entities.main(["ana_garcia", "ana"], output)

        [line] = output.getvalue().splitlines()
        version, op, data = line.split(" ", 2)
        self.assertEqual(op, "entity_merged")
        self.assertEqual(int(version), store.current_version())
        self.assertEqual(json.loads(data)["into"]["key"], "ana")
        self.assertIn("Ana García", data)

    def test_an_impossible_merge_is_reported_as_an_error(self) -> None:
        SqliteKnowledgeGraph(self.graph_path)

        for argv in (["nadie", "usuario"], ["usuario", "yo"]):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as raised:
                    merge_entities.main(argv, io.StringIO())
                self.assertIn("Cannot merge", str(raised.exception))


class BuildKnowledgeTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = load_settings(Path(directory.name))

    def test_builds_the_memory_with_both_switches_off(self) -> None:
        knowledge = build_knowledge(self.settings)

        self.assertIsInstance(knowledge, KnowledgeGraphMemory)
        self.assertTrue(self.settings.knowledge.path.exists())
        knowledge.observe_exchange("Hola", "Hola")
        self.assertEqual(knowledge.snapshot().version, 1)
        self.assertEqual(SqliteKnowledgeGraph(self.settings.knowledge.path).pending_count(), 0)

    def test_switches_reach_the_memory(self) -> None:
        settings = replace(
            self.settings, knowledge=replace(self.settings.knowledge, extraction_enabled=True)
        )
        knowledge = build_knowledge(settings)

        knowledge.observe_exchange("Hola", "Hola")

        self.assertEqual(SqliteKnowledgeGraph(settings.knowledge.path).pending_count(), 1)

    def test_an_unreadable_database_leaves_jarvis_without_graph_memory(self) -> None:
        path = self.settings.knowledge.path
        path.parent.mkdir(parents=True)
        path.write_bytes(b"esto no es una base de datos " * 100)

        with self.assertLogs("jarvis.bootstrap.app", "ERROR") as logs:
            self.assertIsNone(build_knowledge(self.settings))

        self.assertIn("Knowledge graph unavailable", logs.output[0])


if __name__ == "__main__":
    unittest.main()
