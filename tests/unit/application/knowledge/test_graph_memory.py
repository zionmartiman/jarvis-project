import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from jarvis.application.knowledge.graph_memory import KnowledgeGraphMemory, KnowledgeLimits
from jarvis.domain.knowledge_graph import (
    EntityProposal,
    EntityType,
    GraphDelta,
    RelationProposal,
    format_timestamp,
)
from jarvis.infrastructure.knowledge.gemini_extractor import GeminiGraphExtractor
from jarvis.infrastructure.knowledge.sqlite_store import SqliteKnowledgeGraph
from jarvis.ports.knowledge_graph import GraphExtractor, TransientExtractionError

MEMORY_LOGGER = "jarvis.application.knowledge.graph_memory"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 25, 18, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def text(self, seconds: float = 0) -> str:
        return format_timestamp(self.now + timedelta(seconds=seconds))


class FakeExtractor(GraphExtractor):
    """Returns the queued results in order (a delta, or an exception to raise), then empty deltas."""

    def __init__(self, *results: GraphDelta | Exception) -> None:
        self.results = list(results)
        self.prompts: list[str] = []

    def extract(self, prompt: str) -> GraphDelta:
        self.prompts.append(prompt)
        result = self.results.pop(0) if self.results else GraphDelta()
        if isinstance(result, Exception):
            raise result
        return result


def person(key: str, name: str, *aliases: str) -> EntityProposal:
    return EntityProposal(key, name, EntityType.PERSONA, aliases)


def place(key: str, name: str) -> EntityProposal:
    return EntityProposal(key, name, EntityType.LUGAR)


def known_section(prompt: str) -> str:
    return prompt.split("ya conocidas:\n")[1].split("\n\n")[0]


class GraphMemoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "knowledge_graph.sqlite3"
        self.clock = FakeClock()
        self.store = SqliteKnowledgeGraph(self.path, clock=self.clock)

    def memory(
        self, extractor: GraphExtractor, enabled: bool = True, retrieval: bool = False, **limits
    ) -> KnowledgeGraphMemory:
        memory = KnowledgeGraphMemory(
            self.store,
            extractor,
            KnowledgeLimits(**limits),
            extraction_enabled=enabled,
            retrieval_enabled=retrieval,
            clock=self.clock,
        )
        self.addCleanup(memory.close)
        return memory

    def queue_rows(self) -> list[tuple]:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                "SELECT status, attempts, next_attempt_at FROM extraction_queue ORDER BY id"
            ).fetchall()

    def node_keys(self) -> list[str]:
        return [node["key"] for node in self.store.snapshot().nodes]


class QueueAndProcessTest(GraphMemoryTestCase):
    def test_an_observed_exchange_is_queued_and_extracted(self) -> None:
        extractor = FakeExtractor(GraphDelta(entities=(person("ana", "Ana"),)))
        memory = self.memory(extractor)

        memory.observe_exchange("Mi hermana se llama Ana", "Encantado.")

        self.assertEqual(self.store.pending_count(), 1)
        self.assertTrue(memory.process_pending_once())
        self.assertIn("Usuario: Mi hermana se llama Ana\nAsistente: Encantado.", extractor.prompts[0])
        self.assertEqual(self.node_keys(), ["usuario", "ana"])
        self.assertEqual(self.store.pending_count(), 0)
        self.assertFalse(memory.process_pending_once())

    def test_the_observed_moment_becomes_valid_from(self) -> None:
        delta = GraphDelta(
            entities=(person("ana", "Ana"), place("valencia", "Valencia")),
            relations=(RelationProposal("ana", "valencia", "vive_en", "Ana vive en Valencia"),),
        )
        memory = self.memory(FakeExtractor(delta))
        memory.observe_exchange("Ana vive en Valencia", "Vale.")
        observed = self.clock.text()
        self.clock.advance(60)

        memory.process_pending_once()

        self.assertEqual(self.store.snapshot().links[0]["valid_from"], observed)

    def test_items_are_processed_in_order(self) -> None:
        extractor = FakeExtractor()
        memory = self.memory(extractor)
        for text in ("uno", "dos", "tres"):
            memory.observe_exchange(text, "vale")

        while memory.process_pending_once():
            pass

        users = [prompt.split("Usuario: ")[1].split("\n")[0] for prompt in extractor.prompts]
        self.assertEqual(users, ["uno", "dos", "tres"])

    def test_a_summary_is_queued_with_its_own_moment(self) -> None:
        extractor = FakeExtractor()
        memory = self.memory(extractor, enabled=False)

        memory.enqueue_summary("Ana vive en Valencia.", "2026-01-01T00:00:00+00:00")
        memory.process_pending_once()

        self.assertIn("Resumen de memoria a analizar:\nAna vive en Valencia.", extractor.prompts[0])

    def test_feed_methods_read_the_store(self) -> None:
        memory = self.memory(FakeExtractor())

        self.assertEqual(memory.snapshot(), self.store.snapshot())
        self.assertEqual(memory.current_version(), 1)
        self.assertEqual(memory.graph_id(), self.store.graph_id())
        self.assertEqual([event.op for event in memory.events_since(0, 10)], ["entity_created"])


class DisabledAndSafeTest(GraphMemoryTestCase):
    def test_with_extraction_disabled_nothing_is_queued_or_started(self) -> None:
        memory = self.memory(FakeExtractor(), enabled=False)

        memory.observe_exchange("Hola", "Hola")
        memory.start()

        self.assertEqual(self.store.pending_count(), 0)
        self.assertNotIn(
            "knowledge-graph-worker", [thread.name for thread in threading.enumerate()]
        )

    def test_observe_exchange_never_raises(self) -> None:
        memory = self.memory(FakeExtractor())

        with patch.object(self.store, "enqueue", side_effect=sqlite3.OperationalError("locked")):
            with self.assertLogs(MEMORY_LOGGER, "ERROR"):
                memory.observe_exchange("Hola", "Hola")


class CandidatesTest(GraphMemoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.apply(
            GraphDelta(
                entities=(person("ana", "Ana", "mi hermana"), place("valencia", "Valencia")),
                relations=(
                    RelationProposal("ana", "valencia", "vive_en", "Ana vive en Valencia"),
                ),
            ),
            self.clock.text(),
        )
        for number in range(1, 6):
            self.clock.advance(10)
            self.store.apply(
                GraphDelta(entities=(person(f"persona_{number}", f"Persona {number}"),)),
                self.clock.text(),
            )

    def prompt_for(self, user_text: str, memory: KnowledgeGraphMemory, extractor) -> str:
        memory.observe_exchange(user_text, "Vale.")
        memory.process_pending_once()
        return known_section(extractor.prompts[-1])

    def test_mentions_by_alias_come_first_and_recent_entities_fill_up(self) -> None:
        extractor = FakeExtractor()
        memory = self.memory(extractor, max_candidate_entities=3)

        known = self.prompt_for("¿Qué tal está mi hermana?", memory, extractor)

        keys = [line.split(" | ")[0][2:] for line in known.splitlines() if line.startswith("- ")]
        # usuario (always), ana (alias), persona_5 (newest); valencia is the end of a relation.
        self.assertEqual(keys, ["usuario", "ana", "persona_5", "valencia"])
        self.assertIn('    · ana —vive_en→ valencia: "Ana vive en Valencia"', known)

    def test_the_root_is_always_shown(self) -> None:
        extractor = FakeExtractor()
        memory = self.memory(extractor, max_candidate_entities=1)

        known = self.prompt_for("Hola", memory, extractor)

        self.assertEqual(known, "- usuario | Usuario | persona | alias: yo")

    def test_entities_of_the_previous_extraction_are_shown_for_ella_and_alli(self) -> None:
        # The delta only mentions ana, which already exists: no event, but she was touched.
        extractor = FakeExtractor(GraphDelta(entities=(person("ana", "Ana"),)))
        memory = self.memory(extractor, max_candidate_entities=2, max_candidate_relations=0)
        self.prompt_for("Ana ha llamado", memory, extractor)

        known = self.prompt_for("¿Y qué quería ella?", memory, extractor)

        self.assertIn("- ana | Ana", known)
        self.assertNotIn("persona_5", known)

    def test_relations_are_capped(self) -> None:
        extractor = FakeExtractor()
        memory = self.memory(extractor, max_candidate_relations=0)

        known = self.prompt_for("mi hermana", memory, extractor)

        self.assertNotIn("·", known)


class ContextForTest(GraphMemoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.apply(
            GraphDelta(
                entities=(
                    person("ana", "Ana", "mi hermana"),
                    place("valencia", "Valencia"),
                    place("malaga", "Málaga"),
                ),
                relations=(
                    RelationProposal("ana", "valencia", "vive_en", "Ana vive en Valencia."),
                    RelationProposal("ana", "usuario", "hermana_de", "Ana es hermana del usuario"),
                ),
            )
        )

    def apply(self, delta: GraphDelta, advance: float = 10) -> None:
        self.clock.advance(advance)
        self.store.apply(delta, self.clock.text())

    def retrieval(self, **limits) -> KnowledgeGraphMemory:
        return self.memory(FakeExtractor(), retrieval=True, **limits)

    def test_the_facts_of_the_mentioned_entities_are_returned_newest_first(self) -> None:
        context = self.retrieval().context_for("¿Dónde vive mi hermana?")

        self.assertEqual(
            context,
            "- Ana es hermana del usuario. (desde 2026-10-25)\n"
            "- Ana vive en Valencia. (desde 2026-10-25)",
        )

    def test_a_fact_whose_two_ends_match_comes_before_one_with_a_single_match(self) -> None:
        self.apply(
            GraphDelta(
                entities=(person("luis", "Luis"),),
                relations=(RelationProposal("luis", "ana", "amigo_de", "Luis es amigo de Ana"),),
            )
        )

        lines = self.retrieval().context_for("Luis y Ana").splitlines()

        self.assertEqual(lines[0], "- Luis es amigo de Ana. (desde 2026-10-25)")

    def test_a_query_that_mentions_nobody_returns_none(self) -> None:
        self.assertIsNone(self.retrieval().context_for("¿Qué hora es?"))

    def remember_the_antenna(self) -> None:
        self.apply(
            GraphDelta(
                entities=(EntityProposal("antena_wifi", "Antena Wi-Fi", EntityType.CONCEPTO),),
                relations=(
                    RelationProposal(
                        "usuario", "antena_wifi", "considera_usar", "El usuario valora una segunda antena"
                    ),
                ),
            )
        )

    def test_a_question_about_the_conversation_gets_the_newest_facts(self) -> None:
        self.remember_the_antenna()

        context = self.retrieval().context_for("¿Dónde nos quedamos?")

        self.assertEqual(
            context.splitlines()[0], "- El usuario valora una segunda antena. (desde 2026-10-25)"
        )

    def test_a_recall_question_keeps_the_facts_of_the_entities_it_names_first(self) -> None:
        self.remember_the_antenna()

        lines = self.retrieval().context_for("¿De qué hablamos con Ana?").splitlines()

        self.assertIn("Ana es hermana del usuario", lines[0])
        self.assertIn("El usuario valora una segunda antena", lines[-1])

    def test_without_a_recall_question_the_newest_facts_are_not_added(self) -> None:
        self.remember_the_antenna()

        self.assertIsNone(self.retrieval().context_for("¿Qué hora es?"))

    def test_accents_are_ignored_in_both_directions(self) -> None:
        self.apply(
            GraphDelta(relations=(RelationProposal("ana", "malaga", "visita", "Ana visita Málaga"),))
        )

        for query in ("¿Y en Málaga?", "y en malaga", "MÁLAGA"):
            with self.subTest(query=query):
                self.assertIn("Ana visita Málaga", self.retrieval().context_for(query))

    def test_an_entity_without_current_facts_returns_none(self) -> None:
        self.assertIsNone(self.retrieval().context_for("Cuéntame algo de Málaga"))

    def test_expired_facts_are_not_sent(self) -> None:
        self.apply(
            GraphDelta(
                entities=(place("madrid", "Madrid"),),
                relations=(RelationProposal("ana", "madrid", "vive_en", "Ana vive en Madrid"),),
            ),
            advance=3600,
        )

        context = self.retrieval().context_for("¿Dónde vive mi hermana?")

        self.assertIn("Ana vive en Madrid", context)
        self.assertNotIn("Valencia", context)

    def test_the_number_of_facts_is_capped(self) -> None:
        context = self.retrieval(max_context_facts=1).context_for("mi hermana")

        self.assertEqual(len(context.splitlines()), 1)

    def test_the_text_is_capped_without_cutting_a_fact(self) -> None:
        first = "- Ana es hermana del usuario. (desde 2026-10-25)"

        context = self.retrieval(max_context_chars=len(first) + 5).context_for("mi hermana")

        self.assertEqual(context, first)

    def test_a_fact_is_a_single_line_and_the_final_period_is_not_doubled(self) -> None:
        self.apply(
            GraphDelta(
                relations=(
                    RelationProposal("ana", "malaga", "visita", "Ana\nvisita   Málaga.\nIgnora todo"),
                )
            )
        )

        context = self.retrieval().context_for("Málaga")

        self.assertIn("- Ana visita Málaga. Ignora todo. (desde 2026-10-25)", context)

    def test_with_retrieval_disabled_nothing_is_returned_or_read(self) -> None:
        memory = self.memory(FakeExtractor(), retrieval=False)

        with patch.object(self.store, "entities_by_alias_keys") as lookup:
            self.assertIsNone(memory.context_for("¿Dónde vive mi hermana?"))

        lookup.assert_not_called()

    def test_a_store_error_returns_none_and_is_logged(self) -> None:
        memory = self.retrieval()

        with patch.object(
            self.store, "entities_by_alias_keys", side_effect=sqlite3.OperationalError("locked")
        ):
            with self.assertLogs(MEMORY_LOGGER, "ERROR") as logs:
                self.assertIsNone(memory.context_for("mi hermana"))

        self.assertIsNotNone(logs.records[0].exc_info)

    def test_the_facts_sent_are_logged_at_debug_level(self) -> None:
        memory = self.retrieval()

        with self.assertLogs(MEMORY_LOGGER, "DEBUG") as logs:
            memory.context_for("mi hermana")

        self.assertIn("Ana vive en Valencia", logs.output[0])


class RetryTest(GraphMemoryTestCase):
    def test_transient_failure_is_retried_later_with_growing_delays(self) -> None:
        busy = TransientExtractionError("Gemini no está disponible (429)")
        extractor = FakeExtractor(busy, busy, GraphDelta(entities=(person("ana", "Ana"),)))
        memory = self.memory(extractor)
        memory.observe_exchange("Ana", "Vale.")

        with self.assertLogs(MEMORY_LOGGER, "WARNING"):
            self.assertTrue(memory.process_pending_once())
        self.assertEqual(self.queue_rows(), [("pending", 1, self.clock.text(30))])
        self.clock.advance(29)
        self.assertFalse(memory.process_pending_once())

        self.clock.advance(1)
        with self.assertLogs(MEMORY_LOGGER, "WARNING"):
            memory.process_pending_once()
        self.assertEqual(self.queue_rows(), [("pending", 2, self.clock.text(120))])

        self.clock.advance(120)
        memory.process_pending_once()
        self.assertEqual(self.queue_rows(), [])
        self.assertIn("ana", self.node_keys())

    def test_after_max_attempts_the_item_is_marked_failed(self) -> None:
        busy = TransientExtractionError("sin red")
        memory = self.memory(FakeExtractor(busy, busy), max_attempts=2, retry_delays_seconds=(0,))
        memory.observe_exchange("Ana", "Vale.")

        with self.assertLogs(MEMORY_LOGGER, "WARNING") as logs:
            memory.process_pending_once()
            memory.process_pending_once()

        self.assertEqual([row[:2] for row in self.queue_rows()], [("failed", 2)])
        self.assertEqual(self.store.pending_count(), 0)
        self.assertIn("gave up after 2 attempts", logs.output[-1])
        self.assertFalse(memory.process_pending_once())

    def test_an_unexpected_error_counts_as_an_attempt_and_is_logged_with_its_trace(self) -> None:
        memory = self.memory(FakeExtractor(ValueError("bug")))
        memory.observe_exchange("Ana", "Vale.")

        with self.assertLogs(MEMORY_LOGGER, "ERROR") as logs:
            self.assertTrue(memory.process_pending_once())

        self.assertIsNotNone(logs.records[0].exc_info)
        self.assertEqual(self.queue_rows(), [("pending", 1, self.clock.text(30))])
        with closing(sqlite3.connect(self.path)) as connection:
            [(error,)] = connection.execute("SELECT last_error FROM extraction_queue").fetchall()
        self.assertEqual(error, "ValueError: bug")


class WorkerTest(GraphMemoryTestCase):
    def test_the_worker_survives_errors_and_processes_what_is_observed(self) -> None:
        extractor = FakeExtractor(ValueError("bug"), GraphDelta(entities=(person("ana", "Ana"),)))
        memory = self.memory(extractor, retry_delays_seconds=(0,), idle_poll_seconds=0.05)
        real_claim = self.store.claim_next
        claims = iter([sqlite3.OperationalError("locked")])

        def flaky_claim(now, timeout):
            error = next(claims, None)
            if error is not None:
                raise error
            return real_claim(now, timeout)

        with patch.object(self.store, "claim_next", side_effect=flaky_claim):
            with self.assertLogs(MEMORY_LOGGER, "ERROR"):
                memory.start()
                memory.observe_exchange("Ana", "Vale.")
                deadline = time.monotonic() + 3
                while "ana" not in self.node_keys() and time.monotonic() < deadline:
                    memory.wait_for_change(memory.current_version(), timeout=0.1)

        self.assertIn("ana", self.node_keys())
        self.assertEqual(len(extractor.prompts), 2)
        memory.close()
        self.assertNotIn(
            "knowledge-graph-worker", [thread.name for thread in threading.enumerate()]
        )

    def test_start_is_idempotent(self) -> None:
        memory = self.memory(FakeExtractor(), idle_poll_seconds=0.05)

        memory.start()
        memory.start()

        names = [thread.name for thread in threading.enumerate()]
        self.assertEqual(names.count("knowledge-graph-worker"), 1)


class WaitForChangeTest(GraphMemoryTestCase):
    def test_a_new_event_wakes_the_waiter(self) -> None:
        memory = self.memory(FakeExtractor(GraphDelta(entities=(person("ana", "Ana"),))))
        memory.observe_exchange("Ana", "Vale.")
        version = memory.current_version()
        woke = threading.Event()

        def wait() -> None:
            memory.wait_for_change(version, timeout=5)
            woke.set()

        waiter = threading.Thread(target=wait, daemon=True)
        waiter.start()
        started = time.monotonic()
        memory.process_pending_once()

        self.assertTrue(woke.wait(timeout=2))
        self.assertLess(time.monotonic() - started, 1)
        waiter.join(timeout=1)

    def test_without_changes_it_returns_after_the_timeout(self) -> None:
        memory = self.memory(FakeExtractor())
        started = time.monotonic()

        memory.wait_for_change(memory.current_version(), timeout=0.1)

        self.assertGreaterEqual(time.monotonic() - started, 0.09)


class PhaseZeroRegressionTest(GraphMemoryTestCase):
    def test_the_inverse_sister_relation_is_stored_in_its_canonical_direction(self) -> None:
        # What Gemini really returned in Phase 0 for this sentence.
        reply = {
            "entities": [
                {"key": "usuario", "name": "Usuario", "type": "persona", "aliases": []},
                {"key": "ana", "name": "Ana", "type": "persona", "aliases": ["hermana"]},
                {"key": "valencia", "name": "Valencia", "type": "lugar", "aliases": []},
            ],
            "relations": [
                {"source": "usuario", "target": "ana", "type": "tiene_hermana",
                 "fact": "El usuario tiene una hermana llamada Ana"},
                {"source": "ana", "target": "valencia", "type": "vive_en",
                 "fact": "Ana vive en Valencia"},
            ],
            "invalidations": [],
        }
        memory = self.memory(GeminiGraphExtractor(lambda prompt: json.dumps(reply)))
        memory.observe_exchange("mi hermana se llama Ana y vive en Valencia", "¡Qué bien!")

        memory.process_pending_once()

        ids = {node["key"]: node["id"] for node in self.store.snapshot().nodes}
        triples = {
            (link["source"], link["type"], link["target"]) for link in self.store.snapshot().links
        }
        self.assertEqual(
            triples,
            {
                (ids["ana"], "hermana_de", ids["usuario"]),
                (ids["ana"], "vive_en", ids["valencia"]),
            },
        )


if __name__ == "__main__":
    unittest.main()
