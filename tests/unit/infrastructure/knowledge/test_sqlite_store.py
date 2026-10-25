import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from jarvis.domain.knowledge_graph import (
    EntityProposal,
    EntityType,
    GraphDelta,
    InvalidationProposal,
    RelationProposal,
    format_timestamp,
)
from jarvis.infrastructure.knowledge.sqlite_store import (
    SCHEMA_VERSION,
    SqliteKnowledgeGraph,
    backup_and_remove,
)

T1 = "2026-11-01T10:00:00+00:00"
T2 = "2026-11-02T10:00:00+00:00"
T3 = "2026-11-03T10:00:00+00:00"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 25, 18, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def text(self, seconds: float = 0) -> str:
        return format_timestamp(self.now + timedelta(seconds=seconds))


def person(key: str, name: str, *aliases: str) -> EntityProposal:
    return EntityProposal(key, name, EntityType.PERSONA, aliases)


def place(key: str, name: str) -> EntityProposal:
    return EntityProposal(key, name, EntityType.LUGAR)


def lives_in(source: str, target: str, fact: str) -> RelationProposal:
    return RelationProposal(source, target, "vive_en", fact)


def rebuild(events) -> tuple[list[dict], list[dict]]:
    """What a client gets by applying every event in order, as the browser will."""
    nodes: dict[int, dict] = {}
    links: dict[int, dict] = {}
    for event in events:
        data = event.data
        if event.op in ("entity_created", "entity_updated"):
            nodes[data["id"]] = data
        elif event.op in ("relation_created", "relation_updated"):
            links[data["id"]] = data
        elif event.op == "relation_invalidated":
            links[data["id"]] = {**links[data["id"]], "valid_to": data["valid_to"]}
        elif event.op == "entity_merged":
            del nodes[data["from_id"]]
            nodes[data["into"]["id"]] = data["into"]
            links = {
                link_id: link
                for link_id, link in links.items()
                if data["from_id"] not in (link["source"], link["target"])
            }
        else:
            raise AssertionError(f"unknown op {event.op}")
    return [nodes[key] for key in sorted(nodes)], [links[key] for key in sorted(links)]


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state" / "knowledge_graph.sqlite3"
        self.clock = FakeClock()
        self.store = self.open_store()

    def open_store(self) -> SqliteKnowledgeGraph:
        return SqliteKnowledgeGraph(self.path, clock=self.clock)

    def node(self, key: str) -> dict:
        return next(node for node in self.store.snapshot().nodes if node["key"] == key)

    def links(self) -> list[dict]:
        return list(self.store.snapshot().links)

    def query(self, sql: str, params=()) -> list[tuple]:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(sql, params).fetchall()


class MigrationTest(StoreTestCase):
    def test_creates_the_schema_and_the_root_entity(self) -> None:
        snapshot = self.store.snapshot()

        self.assertTrue(self.path.exists())
        self.assertEqual(self.query("PRAGMA user_version"), [(SCHEMA_VERSION,)])
        self.assertEqual(self.query("PRAGMA journal_mode"), [("wal",)])
        self.assertRegex(snapshot.graph_id, r"^[0-9a-f]{32}$")
        self.assertEqual(snapshot.version, 1)
        self.assertEqual(
            snapshot.nodes,
            (
                {
                    "id": 1,
                    "key": "usuario",
                    "name": "Usuario",
                    "type": "persona",
                    "aliases": ["yo"],
                    "created_at": "2026-10-25T18:00:00+00:00",
                    "updated_at": "2026-10-25T18:00:00+00:00",
                },
            ),
        )
        self.assertEqual(snapshot.links, ())
        [event] = self.store.events_since(0, 10)
        self.assertEqual((event.version, event.op, event.data), (1, "entity_created", snapshot.nodes[0]))
        self.assertEqual(
            sorted(self.query("SELECT alias_key FROM entity_aliases")), [("usuario",), ("yo",)]
        )

    def test_reopening_does_not_migrate_again(self) -> None:
        graph_id = self.store.snapshot().graph_id

        reopened = self.open_store()

        self.assertEqual(reopened.snapshot().graph_id, graph_id)
        self.assertEqual(reopened.current_version(), 1)
        self.assertEqual(self.query("SELECT COUNT(*) FROM entities"), [(1,)])

    def test_newer_schema_version_fails_with_a_clear_message(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA user_version = 99")

        with self.assertRaisesRegex(RuntimeError, "schema version 99"):
            self.open_store()

    def test_creates_missing_folders(self) -> None:
        nested = self.path.parent / "a" / "b" / "kg.sqlite3"

        store = SqliteKnowledgeGraph(nested, clock=self.clock)

        self.assertEqual(store.current_version(), 1)


class ApplyEntitiesTest(StoreTestCase):
    def test_new_entity_is_created_with_its_aliases(self) -> None:
        [event] = self.store.apply(GraphDelta(entities=(person("ana", "Ana", "mi hermana"),)), T1)

        self.assertEqual(event.op, "entity_created")
        self.assertEqual(event.data["key"], "ana")
        self.assertEqual(event.data["aliases"], ["mi hermana"])
        self.assertEqual(self.node("ana"), event.data)

    def test_existing_entity_is_found_by_key_and_only_gains_new_aliases(self) -> None:
        self.store.apply(GraphDelta(entities=(person("ana", "Ana", "mi hermana"),)), T1)
        self.clock.advance(60)

        same = self.store.apply(GraphDelta(entities=(person("ana", "Ana", "Mi hermana"),)), T2)
        [updated] = self.store.apply(GraphDelta(entities=(person("ana", "Ana", "la peque"),)), T2)
        # A different name never renames the entity: it is kept as one more alias.
        [renamed] = self.store.apply(
            GraphDelta(entities=(EntityProposal("ana", "Anabel", EntityType.LUGAR),)), T2
        )

        self.assertEqual(same, [])
        self.assertEqual(updated.op, "entity_updated")
        self.assertEqual(updated.data["aliases"], ["mi hermana", "la peque"])
        self.assertEqual(updated.data["updated_at"], self.clock.text())
        self.assertEqual((renamed.data["name"], renamed.data["type"]), ("Ana", "persona"))
        self.assertEqual(renamed.data["aliases"], ["mi hermana", "la peque", "Anabel"])
        self.assertEqual(len(self.store.snapshot().nodes), 2)

    def test_existing_entity_is_found_by_alias(self) -> None:
        self.store.apply(GraphDelta(entities=(person("ana", "Ana", "mi hermana"),)), T1)

        [event] = self.store.apply(
            GraphDelta(entities=(person("ana_garcia", "Ana García", "Mi hermana"),)), T2
        )

        self.assertEqual(event.op, "entity_updated")
        self.assertEqual(event.data["key"], "ana")
        self.assertEqual(event.data["aliases"], ["mi hermana", "Ana García"])
        self.assertEqual([entity.key for entity in self.store.entities_by_alias_keys(["ana_garcia"])], ["ana"])

    def test_the_user_name_becomes_an_alias_of_the_root(self) -> None:
        [event] = self.store.apply(GraphDelta(entities=(person("usuario", "Usuario", "Marc"),)), T1)

        self.assertEqual(event.data["id"], 1)
        self.assertEqual(event.data["aliases"], ["yo", "Marc"])

    def test_alias_of_another_entity_is_not_taken(self) -> None:
        self.store.apply(
            GraphDelta(entities=(person("ana", "Ana", "la jefa"), person("eva", "Eva"))), T1
        )

        events = self.store.apply(GraphDelta(entities=(person("eva", "Eva", "La jefa", "Evita"),)), T2)

        self.assertEqual(self.node("eva")["aliases"], ["Evita"])
        self.assertEqual(self.node("ana")["aliases"], ["la jefa"])
        self.assertEqual([event.op for event in events], ["entity_updated"])

    def test_entities_by_alias_keys_ignores_unknown_keys_and_repeats(self) -> None:
        self.store.apply(GraphDelta(entities=(person("ana", "Ana", "mi hermana"),)), T1)

        found = self.store.entities_by_alias_keys(["nadie", "mi_hermana", "ana", "yo", ""])

        self.assertEqual([entity.key for entity in found], ["ana", "usuario"])


class ApplyRelationsTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.apply(
            GraphDelta(
                entities=(
                    person("ana", "Ana", "mi hermana"),
                    place("valencia", "Valencia"),
                    place("madrid", "Madrid"),
                )
            ),
            T1,
        )

    def test_relation_is_created_from_the_moment_it_was_observed(self) -> None:
        [event] = self.store.apply(
            GraphDelta(relations=(lives_in("ana", "valencia", "Ana vive en Valencia"),)), T1
        )

        self.assertEqual(event.op, "relation_created")
        self.assertEqual(
            event.data,
            {
                "id": 1,
                "source": self.node("ana")["id"],
                "target": self.node("valencia")["id"],
                "type": "vive_en",
                "fact": "Ana vive en Valencia",
                "valid_from": T1,
                "valid_to": None,
            },
        )

    def test_ends_resolve_through_aliases_and_new_entities_of_the_same_delta(self) -> None:
        events = self.store.apply(
            GraphDelta(
                entities=(place("ibiza", "Ibiza"),),
                relations=(RelationProposal("mi_hermana", "ibiza", "le_gusta", "A Ana le gusta Ibiza"),),
            ),
            T1,
        )

        self.assertEqual([event.op for event in events], ["entity_created", "relation_created"])
        self.assertEqual(events[1].data["source"], self.node("ana")["id"])

    def test_unknown_end_is_dropped(self) -> None:
        events = self.store.apply(GraphDelta(relations=(lives_in("ana", "paris", "Ana vive en París"),)), T1)

        self.assertEqual(events, [])
        self.assertEqual(self.links(), [])

    def test_same_active_triple_is_a_no_op_or_an_update_of_the_fact(self) -> None:
        self.store.apply(GraphDelta(relations=(lives_in("ana", "valencia", "Ana vive en Valencia"),)), T1)

        same = self.store.apply(
            GraphDelta(relations=(lives_in("ana", "valencia", "Ana vive en Valencia"),)), T2
        )
        [updated] = self.store.apply(
            GraphDelta(relations=(lives_in("ana", "valencia", "Ana vive en el centro de Valencia"),)),
            T2,
        )

        self.assertEqual(same, [])
        self.assertEqual(updated.op, "relation_updated")
        self.assertEqual(updated.data["fact"], "Ana vive en el centro de Valencia")
        self.assertEqual(updated.data["valid_from"], T1)
        self.assertEqual(len(self.links()), 1)

    def test_invalidation_closes_the_relation_at_the_observed_moment(self) -> None:
        self.store.apply(
            GraphDelta(relations=(RelationProposal("ana", "valencia", "le_gusta", "A Ana le gusta Valencia"),)),
            T1,
        )

        [event] = self.store.apply(
            GraphDelta(invalidations=(InvalidationProposal("ana", "valencia", "le_gusta", "Ya no"),)),
            T2,
        )
        again = self.store.apply(
            GraphDelta(invalidations=(InvalidationProposal("ana", "valencia", "le_gusta", "Ya no"),)),
            T3,
        )
        unknown = self.store.apply(
            GraphDelta(invalidations=(InvalidationProposal("ana", "nadie", "le_gusta", "?"),)), T3
        )

        self.assertEqual(event.op, "relation_invalidated")
        self.assertEqual(event.data, {"id": 1, "valid_to": T2, "reason": "Ya no"})
        self.assertEqual(self.links()[0]["valid_to"], T2)
        self.assertEqual((again, unknown), ([], []))
        self.assertEqual(self.store.active_relations([self.node("ana")["id"]], 10), [])

    def test_invalidated_triple_can_be_true_again_later(self) -> None:
        relation = RelationProposal("ana", "valencia", "le_gusta", "A Ana le gusta Valencia")
        self.store.apply(GraphDelta(relations=(relation,)), T1)
        self.store.apply(
            GraphDelta(invalidations=(InvalidationProposal("ana", "valencia", "le_gusta", "r"),)), T2
        )

        [event] = self.store.apply(GraphDelta(relations=(relation,)), T3)

        self.assertEqual(event.op, "relation_created")
        self.assertEqual([link["valid_to"] for link in self.links()], [T2, None])

    def test_single_valued_relation_replaces_the_previous_one(self) -> None:
        self.store.apply(GraphDelta(relations=(lives_in("ana", "valencia", "Ana vive en Valencia"),)), T1)

        events = self.store.apply(
            GraphDelta(relations=(lives_in("ana", "madrid", "Ana vive en Madrid"),)), T2
        )

        self.assertEqual([event.op for event in events], ["relation_invalidated", "relation_created"])
        self.assertEqual(events[0].data["reason"], "sustituida por Ana vive en Madrid")
        self.assertEqual(events[0].data["valid_to"], T2)
        [active] = self.store.active_relations([self.node("ana")["id"]], 10)
        self.assertEqual(active.fact, "Ana vive en Madrid")

    def test_multi_valued_relation_keeps_both(self) -> None:
        self.store.apply(
            GraphDelta(
                relations=(
                    RelationProposal("ana", "valencia", "le_gusta", "A Ana le gusta Valencia"),
                    RelationProposal("ana", "madrid", "le_gusta", "A Ana le gusta Madrid"),
                )
            ),
            T1,
        )

        self.assertEqual(len(self.store.active_relations([self.node("ana")["id"]], 10)), 2)

    def test_active_relations_prefer_both_ends_then_newest(self) -> None:
        ana, valencia, madrid = (self.node(key)["id"] for key in ("ana", "valencia", "madrid"))
        self.store.apply(
            GraphDelta(relations=(RelationProposal("ana", "valencia", "le_gusta", "uno"),)), T1
        )
        self.store.apply(
            GraphDelta(relations=(RelationProposal("valencia", "madrid", "cerca_de", "dos"),)), T2
        )
        self.store.apply(
            GraphDelta(relations=(RelationProposal("ana", "madrid", "le_gusta", "tres"),)), T3
        )

        facts = [relation.fact for relation in self.store.active_relations([ana, valencia], 10)]
        limited = self.store.active_relations([madrid], 1)

        self.assertEqual(facts, ["uno", "tres", "dos"])
        self.assertEqual([relation.fact for relation in limited], ["tres"])
        self.assertEqual(self.store.active_relations([], 10), [])

    def test_a_failure_halfway_leaves_nothing_written(self) -> None:
        before = self.store.snapshot()
        original = self.store._record
        recorded: list[object] = []

        def fail_on_second_event(*args):
            if recorded:
                raise RuntimeError("boom")
            recorded.append(original(*args))
            return recorded[-1]

        delta = GraphDelta(
            entities=(person("eva", "Eva"),),
            relations=(lives_in("eva", "madrid", "Eva vive en Madrid"),),
        )
        with patch.object(self.store, "_record", side_effect=fail_on_second_event):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                self.store.apply(delta, T1)

        self.assertEqual(self.store.snapshot(), before)
        self.assertEqual(self.store.events_since(before.version, 10), [])
        self.assertEqual(self.store.entities_by_alias_keys(["eva"]), [])


class EventsTest(StoreTestCase):
    def test_events_are_ordered_and_rebuild_the_snapshot(self) -> None:
        self.store.apply(
            GraphDelta(
                entities=(person("ana", "Ana", "mi hermana"), place("valencia", "Valencia")),
                relations=(lives_in("ana", "valencia", "Ana vive en Valencia"),),
            ),
            T1,
        )
        self.store.apply(
            GraphDelta(
                entities=(place("madrid", "Madrid"), person("ana_g", "Ana G.", "Anita")),
                relations=(
                    lives_in("ana", "madrid", "Ana vive en Madrid"),
                    RelationProposal("ana_g", "usuario", "amiga_de", "Ana G. es amiga del usuario"),
                    RelationProposal("ana_g", "ana", "conoce_a", "Ana G. conoce a Ana"),
                ),
            ),
            T2,
        )
        self.store.apply(GraphDelta(relations=(lives_in("ana", "madrid", "Ana vive en Madrid centro"),)), T3)
        self.store.merge_entities("ana_g", "ana")

        events = self.store.events_since(0, 1000)
        snapshot = self.store.snapshot()

        versions = [event.version for event in events]
        self.assertEqual(versions, sorted(versions))
        self.assertEqual(versions[-1], snapshot.version)
        self.assertEqual(rebuild(events), (list(snapshot.nodes), list(snapshot.links)))

    def test_events_since_pages_through_the_log(self) -> None:
        self.store.apply(GraphDelta(entities=(person("a", "A"), person("b", "B"), person("c", "C"))), T1)

        first = self.store.events_since(0, 2)
        rest = self.store.events_since(first[-1].version, 10)

        self.assertEqual([event.version for event in first + rest], [1, 2, 3, 4])
        self.assertEqual(self.store.current_version(), 4)
        self.assertEqual(self.store.events_since(4, 10), [])


class MergeEntitiesTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.apply(
            GraphDelta(
                entities=(
                    person("ana", "Ana", "mi hermana"),
                    person("ana_garcia", "Ana García", "Anita"),
                    place("valencia", "Valencia"),
                    place("madrid", "Madrid"),
                ),
                relations=(
                    RelationProposal("ana", "valencia", "le_gusta", "A Ana le gusta Valencia"),
                    RelationProposal("ana_garcia", "valencia", "le_gusta", "A Ana García le gusta Valencia"),
                    RelationProposal("ana_garcia", "madrid", "trabaja_en", "Ana García trabaja en Madrid"),
                    RelationProposal("ana_garcia", "usuario", "hermana_de", "Ana García es hermana del usuario"),
                    RelationProposal("ana", "ana_garcia", "es", "Ana es Ana García"),
                ),
            ),
            T1,
        )
        self.ana = self.node("ana")["id"]
        self.garcia = self.node("ana_garcia")["id"]

    def test_moves_relations_and_aliases_into_the_target(self) -> None:
        self.clock.advance(60)

        events = self.store.merge_entities("Ana García", "ana")

        self.assertEqual(
            [event.op for event in events],
            [
                "relation_invalidated",  # duplicate le_gusta valencia
                "relation_invalidated",  # ana —es→ ana_garcia would become a loop
                "relation_updated",
                "relation_updated",
                "relation_updated",
                "entity_merged",
            ],
        )
        merged = events[-1].data
        self.assertEqual(merged["from_id"], self.garcia)
        self.assertEqual(merged["into"]["id"], self.ana)
        self.assertEqual(merged["into"]["aliases"], ["mi hermana", "Ana García", "Anita"])
        self.assertEqual(merged["into"]["updated_at"], self.clock.text())
        self.assertEqual(len(merged["relation_ids"]), 3)
        self.assertNotIn(self.garcia, [node["id"] for node in self.store.snapshot().nodes])
        self.assertTrue(all(self.garcia not in (link["source"], link["target"]) for link in self.links()))
        active = {(relation.type, relation.fact) for relation in self.store.active_relations([self.ana], 10)}
        self.assertEqual(
            active,
            {
                ("le_gusta", "A Ana le gusta Valencia"),
                ("trabaja_en", "Ana García trabaja en Madrid"),
                ("hermana_de", "Ana García es hermana del usuario"),
            },
        )
        self.assertEqual([entity.id for entity in self.store.entities_by_alias_keys(["anita"])], [self.ana])

    def test_later_deltas_about_the_merged_key_reach_the_target(self) -> None:
        self.store.merge_entities("ana_garcia", "ana")

        [event] = self.store.apply(
            GraphDelta(relations=(RelationProposal("ana_garcia", "madrid", "le_gusta", "Le gusta Madrid"),)),
            T2,
        )

        self.assertEqual(event.data["source"], self.ana)

    def test_rejects_unknown_identical_and_root_merges(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown entity"):
            self.store.merge_entities("nadie", "ana")
        with self.assertRaisesRegex(ValueError, "already the same entity"):
            self.store.merge_entities("mi hermana", "ana")
        with self.assertRaisesRegex(ValueError, "root entity"):
            self.store.merge_entities("yo", "ana")
        self.assertEqual(len(self.store.snapshot().nodes), 5)


class RecentEntitiesTest(StoreTestCase):
    def test_newest_first_with_exclusions_and_limit(self) -> None:
        for key in ("a", "b", "c"):
            self.clock.advance(1)
            self.store.apply(GraphDelta(entities=(person(key, key.upper()),)), T1)

        recent = self.store.recent_entities(2, exclude_ids=[self.node("c")["id"]])

        self.assertEqual([entity.key for entity in recent], ["b", "a"])
        self.assertEqual(self.store.recent_entities(0), [])
        self.assertEqual(
            [entity.key for entity in self.store.entities_by_ids([self.node("b")["id"], 1])],
            ["usuario", "b"],
        )


class ExtractionQueueTest(StoreTestCase):
    def enqueue(self, text: str, max_pending: int = 10) -> None:
        self.store.enqueue("exchange", text, "Vale.", T1, max_pending)

    def test_items_are_claimed_in_order_and_only_once(self) -> None:
        self.enqueue("uno")
        self.enqueue("dos")
        other_process = self.open_store()

        first = self.store.claim_next(self.clock.text(), 300)
        second = other_process.claim_next(self.clock.text(), 300)
        third = self.store.claim_next(self.clock.text(), 300)

        self.assertEqual((first.user_text, first.attempts, first.kind, first.observed_at), ("uno", 1, "exchange", T1))
        self.assertEqual(second.user_text, "dos")
        self.assertIsNone(third)
        self.assertEqual(self.store.pending_count(), 2)

    def test_stale_claim_can_be_taken_again(self) -> None:
        self.enqueue("uno")
        self.store.claim_next(self.clock.text(), 300)

        self.assertIsNone(self.store.claim_next(self.clock.text(300), 300))
        again = self.store.claim_next(self.clock.text(301), 300)

        self.assertEqual((again.user_text, again.attempts), ("uno", 2))

    def test_enqueue_drops_the_oldest_beyond_the_limit(self) -> None:
        for text in ("uno", "dos", "tres"):
            if text == "tres":
                with self.assertLogs("jarvis.infrastructure.knowledge.sqlite_store", "WARNING"):
                    self.enqueue(text, max_pending=2)
            else:
                self.enqueue(text, max_pending=2)

        claimed = [self.store.claim_next(self.clock.text(), 300).user_text for _ in range(2)]

        self.assertEqual(claimed, ["dos", "tres"])
        self.assertEqual(self.store.pending_count(), 2)

    def test_enqueue_rejects_an_unknown_kind(self) -> None:
        with self.assertRaises(ValueError):
            self.store.enqueue("otro", "a", "b", T1, 10)

    def test_complete_applies_the_delta_with_the_observed_moment_and_removes_the_item(self) -> None:
        self.store.enqueue("summary", "resumen", "", T2, 10)
        item = self.store.claim_next(self.clock.text(), 300)
        delta = GraphDelta(
            entities=(person("ana", "Ana"), place("valencia", "Valencia")),
            relations=(lives_in("ana", "valencia", "Ana vive en Valencia"),),
        )

        events = self.store.complete(item.id, delta)

        self.assertEqual([event.op for event in events], ["entity_created"] * 2 + ["relation_created"])
        self.assertEqual(events[-1].data["valid_from"], T2)
        self.assertEqual(self.store.pending_count(), 0)
        self.assertIsNone(self.store.claim_next(self.clock.text(1000), 300))
        with self.assertLogs("jarvis.infrastructure.knowledge.sqlite_store", "WARNING"):
            self.assertEqual(self.store.complete(item.id, delta), [])
        self.assertEqual(len(self.links()), 1)

    def test_complete_is_atomic(self) -> None:
        self.enqueue("uno")
        item = self.store.claim_next(self.clock.text(), 300)
        before = self.store.snapshot()

        with patch.object(self.store, "_record", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.store.complete(item.id, GraphDelta(entities=(person("ana", "Ana"),)))

        self.assertEqual(self.store.snapshot(), before)
        self.assertEqual(self.store.pending_count(), 1)

    def test_fail_with_retry_releases_the_item_until_the_retry_time(self) -> None:
        self.enqueue("uno")
        item = self.store.claim_next(self.clock.text(), 300)

        self.store.fail(item.id, "HTTP 429", retry_at=self.clock.text(30))

        self.assertIsNone(self.store.claim_next(self.clock.text(29), 300))
        again = self.store.claim_next(self.clock.text(30), 300)
        self.assertEqual((again.id, again.attempts), (item.id, 2))
        self.assertEqual(
            self.query("SELECT status, last_error FROM extraction_queue"), [("pending", "HTTP 429")]
        )

    def test_fail_without_retry_marks_the_item_as_failed(self) -> None:
        self.enqueue("uno")
        item = self.store.claim_next(self.clock.text(), 300)

        self.store.fail(item.id, "x" * 1000, retry_at=None)

        self.assertEqual(self.store.pending_count(), 0)
        self.assertIsNone(self.store.claim_next(self.clock.text(10_000), 300))
        [(status, error)] = self.query("SELECT status, last_error FROM extraction_queue")
        self.assertEqual((status, len(error)), ("failed", 500))

    def test_retry_failed_makes_failed_items_pending_with_their_attempts_reset(self) -> None:
        self.enqueue("uno")
        self.enqueue("dos")
        item = self.store.claim_next(self.clock.text(), 300)
        self.store.fail(item.id, "sin red", retry_at=None)
        self.clock.advance(60)

        self.assertEqual(self.store.retry_failed(), 1)

        self.assertEqual(self.store.pending_count(), 2)
        again = self.store.claim_next(self.clock.text(), 300)
        self.assertEqual((again.id, again.attempts), (item.id, 1))
        self.assertEqual(self.store.retry_failed(), 0)


class BackupAndRemoveTest(StoreTestCase):
    def test_copies_the_whole_database_and_removes_it_with_its_wal_files(self) -> None:
        self.store.apply(GraphDelta(entities=(person("ana", "Ana"),)), T1)
        graph_id = self.store.snapshot().graph_id
        backup = self.path.with_name("copia.bak")

        self.assertTrue(backup_and_remove(self.path, backup))

        for suffix in ("", "-wal", "-shm"):
            self.assertFalse(Path(f"{self.path}{suffix}").exists(), suffix)
        copy = SqliteKnowledgeGraph(backup, clock=self.clock)
        self.assertEqual(copy.snapshot().graph_id, graph_id)
        self.assertIn("ana", [node["key"] for node in copy.snapshot().nodes])
        fresh = self.open_store()
        self.assertNotEqual(fresh.snapshot().graph_id, graph_id)
        self.assertEqual([node["key"] for node in fresh.snapshot().nodes], ["usuario"])

    def test_without_a_database_there_is_nothing_to_do(self) -> None:
        missing = self.path.with_name("otra.sqlite3")

        self.assertFalse(backup_and_remove(missing, self.path.with_name("x.bak")))
        self.assertFalse(self.path.with_name("x.bak").exists())


if __name__ == "__main__":
    unittest.main()
