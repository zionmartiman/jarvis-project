"""SQLite knowledge graph: entities, relations, the events that rebuild them and the extraction queue."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from collections.abc import Callable, Collection, Iterable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jarvis.domain.knowledge_graph import (
    ROOT_ENTITY_ALIASES,
    ROOT_ENTITY_KEY,
    ROOT_ENTITY_NAME,
    SINGLE_VALUED_RELATION_TYPES,
    Entity,
    EntityProposal,
    EntityType,
    GraphDelta,
    GraphEvent,
    GraphSnapshot,
    Relation,
    format_timestamp,
    normalize_key,
)
from jarvis.ports.knowledge_graph import KnowledgeGraphStore, PendingExtraction

LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1
# One statement per item: ``executescript`` would commit the migration transaction halfway.
_SCHEMA_V1 = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE entities (
        id          INTEGER PRIMARY KEY,
        key         TEXT NOT NULL UNIQUE,
        name        TEXT NOT NULL,
        type        TEXT NOT NULL,
        merged_into INTEGER REFERENCES entities(id),
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )""",
    """CREATE TABLE entity_aliases (
        alias_key TEXT PRIMARY KEY,
        entity_id INTEGER NOT NULL REFERENCES entities(id),
        alias     TEXT NOT NULL
    )""",
    "CREATE INDEX entity_aliases_entity ON entity_aliases(entity_id)",
    """CREATE TABLE relations (
        id                  INTEGER PRIMARY KEY,
        source_id           INTEGER NOT NULL REFERENCES entities(id),
        target_id           INTEGER NOT NULL REFERENCES entities(id),
        type                TEXT NOT NULL,
        fact_text           TEXT NOT NULL,
        valid_from          TEXT NOT NULL,
        valid_to            TEXT,
        invalidation_reason TEXT,
        created_at          TEXT NOT NULL,
        CHECK (source_id <> target_id)
    )""",
    """CREATE UNIQUE INDEX relations_active_unique
        ON relations(source_id, target_id, type) WHERE valid_to IS NULL""",
    "CREATE INDEX relations_source ON relations(source_id)",
    "CREATE INDEX relations_target ON relations(target_id)",
    """CREATE TABLE events (
        version      INTEGER PRIMARY KEY,
        ts           TEXT NOT NULL,
        op           TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )""",
    """CREATE TABLE extraction_queue (
        id              INTEGER PRIMARY KEY,
        kind            TEXT NOT NULL CHECK (kind IN ('exchange', 'summary')),
        user_text       TEXT NOT NULL,
        assistant_text  TEXT NOT NULL,
        observed_at     TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'failed')),
        attempts        INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT NOT NULL,
        claimed_at      TEXT,
        last_error      TEXT
    )""",
    "CREATE INDEX extraction_queue_next ON extraction_queue(status, next_attempt_at, id)",
)
_QUEUE_KINDS = frozenset({"exchange", "summary"})
_MAX_ERROR_LENGTH = 500
# Keeps IN (...) lists under the 999-variable limit of SQLite releases older than 3.32.
_IN_CHUNK_SIZE = 500
_MAX_MERGE_CHAIN = 100
_RELATION_COLUMNS = "id, source_id, target_id, type, fact_text, valid_from, valid_to"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _placeholders(count: int) -> str:
    return ", ".join("?" * count)


def _chunks(values: list, size: int = _IN_CHUNK_SIZE) -> Iterator[list]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _relation_from_row(row: tuple) -> Relation:
    return Relation(*row)


def _encode(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


class SqliteKnowledgeGraph(KnowledgeGraphStore):
    """One connection per operation, so worker, HTTP and turn threads never share one."""

    def __init__(self, path: Path, clock: Callable[[], datetime] = _utc_now) -> None:
        self.path = Path(path)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    # graph

    def apply(self, delta: GraphDelta, observed_at: str) -> list[GraphEvent]:
        with self._write() as connection:
            return self._apply(connection, delta, observed_at)

    def entities_by_alias_keys(self, alias_keys: Iterable[str]) -> list[Entity]:
        keys = list(dict.fromkeys(key for key in alias_keys if key))
        with self._read() as connection:
            owners: dict[str, int] = {}
            for chunk in _chunks(keys):
                owners.update(
                    connection.execute(
                        "SELECT alias_key, entity_id FROM entity_aliases "
                        f"WHERE alias_key IN ({_placeholders(len(chunk))})",
                        chunk,
                    ).fetchall()
                )
            ids = list(
                dict.fromkeys(self._final_id(connection, owners[key]) for key in keys if key in owners)
            )
            return self._ordered_entities(connection, ids)

    def recent_entities(self, limit: int, exclude_ids: Collection[int] = ()) -> list[Entity]:
        if limit <= 0:
            return []
        excluded = set(exclude_ids)
        with self._read() as connection:
            rows = connection.execute(
                "SELECT id FROM entities WHERE merged_into IS NULL "
                "ORDER BY updated_at DESC, id DESC LIMIT ?",
                (limit + len(excluded),),
            ).fetchall()
            ids = [entity_id for (entity_id,) in rows if entity_id not in excluded][:limit]
            return self._ordered_entities(connection, ids)

    def active_relations(self, entity_ids: Collection[int], limit: int) -> list[Relation]:
        ids = list(dict.fromkeys(entity_ids))
        if not ids or limit <= 0:
            return []
        marks = _placeholders(len(ids))
        with self._read() as connection:
            rows = connection.execute(
                f"SELECT {_RELATION_COLUMNS} FROM relations WHERE valid_to IS NULL "
                f"AND (source_id IN ({marks}) OR target_id IN ({marks})) "
                f"ORDER BY (source_id IN ({marks})) + (target_id IN ({marks})) DESC, "
                "valid_from DESC, id DESC LIMIT ?",
                [*ids, *ids, *ids, *ids, limit],
            ).fetchall()
        return [_relation_from_row(row) for row in rows]

    def entities_by_ids(self, ids: Collection[int]) -> list[Entity]:
        with self._read() as connection:
            return self._load_entities(connection, list(dict.fromkeys(ids)))

    def merge_entities(self, source_key: str, target_key: str) -> list[GraphEvent]:
        with self._write() as connection:
            now = self._now()
            source_id = self._require_entity(connection, source_key)
            target_id = self._require_entity(connection, target_key)
            if source_id == target_id:
                raise ValueError(f"{source_key!r} and {target_key!r} are already the same entity")
            if source_id == self._resolve(connection, ROOT_ENTITY_KEY):
                raise ValueError("The root entity cannot be merged into another one")

            events: list[GraphEvent] = []
            moved: list[int] = []
            rows = connection.execute(
                "SELECT id, source_id, target_id, type, valid_to FROM relations "
                "WHERE source_id = ? OR target_id = ? ORDER BY id",
                (source_id, source_id),
            ).fetchall()
            for relation_id, old_source, old_target, relation_type, valid_to in rows:
                new_source = target_id if old_source == source_id else old_source
                new_target = target_id if old_target == source_id else old_target
                if new_source == new_target:
                    # A relation between the two merged entities would point at itself: it stays
                    # on the merged entity, expired, and drops out of the snapshot.
                    if valid_to is None:
                        events.append(self._invalidate(connection, relation_id, now, "fusionada", now))
                    continue
                if valid_to is None and self._active_relation_id(
                    connection, new_source, new_target, relation_type
                ):
                    events.append(self._invalidate(connection, relation_id, now, "fusionada", now))
                connection.execute(
                    "UPDATE relations SET source_id = ?, target_id = ? WHERE id = ?",
                    (new_source, new_target, relation_id),
                )
                moved.append(relation_id)

            connection.execute(
                "UPDATE entity_aliases SET entity_id = ? WHERE entity_id = ?", (target_id, source_id)
            )
            connection.execute(
                "UPDATE entities SET merged_into = ?, updated_at = ? WHERE id = ?",
                (target_id, now, source_id),
            )
            connection.execute("UPDATE entities SET updated_at = ? WHERE id = ?", (now, target_id))
            # Moved links first, so a client never sees a link to a node that was just removed.
            for relation_id in moved:
                link = self._relation(connection, relation_id).as_link()
                events.append(self._record(connection, "relation_updated", link, now))
            merged = {
                "from_id": source_id,
                "into": self._entity(connection, target_id).as_node(),
                "relation_ids": moved,
            }
            events.append(self._record(connection, "entity_merged", merged, now))
            return events

    def snapshot(self) -> GraphSnapshot:
        with self._read() as connection:
            (graph_id,) = connection.execute(
                "SELECT value FROM meta WHERE key = 'graph_id'"
            ).fetchone()
            version = self._current_version(connection)
            ids = [
                entity_id
                for (entity_id,) in connection.execute(
                    "SELECT id FROM entities WHERE merged_into IS NULL ORDER BY id"
                )
            ]
            nodes = tuple(entity.as_node() for entity in self._load_entities(connection, ids))
            rows = connection.execute(
                "SELECT r.id, r.source_id, r.target_id, r.type, r.fact_text, r.valid_from, r.valid_to "
                "FROM relations r JOIN entities s ON s.id = r.source_id "
                "JOIN entities t ON t.id = r.target_id "
                "WHERE s.merged_into IS NULL AND t.merged_into IS NULL ORDER BY r.id"
            ).fetchall()
        links = tuple(_relation_from_row(row).as_link() for row in rows)
        return GraphSnapshot(graph_id=graph_id, version=version, nodes=nodes, links=links)

    def events_since(self, version: int, limit: int) -> list[GraphEvent]:
        with self._read() as connection:
            rows = connection.execute(
                "SELECT version, ts, op, payload_json FROM events "
                "WHERE version > ? ORDER BY version LIMIT ?",
                (version, limit),
            ).fetchall()
        return [GraphEvent(number, ts, op, json.loads(payload)) for number, ts, op, payload in rows]

    def current_version(self) -> int:
        with self._read() as connection:
            return self._current_version(connection)

    # persistent queue

    def enqueue(
        self, kind: str, user_text: str, assistant_text: str, observed_at: str, max_pending: int
    ) -> None:
        if kind not in _QUEUE_KINDS:
            raise ValueError(f"Unknown extraction kind: {kind!r}")
        if max_pending < 1:
            raise ValueError("max_pending must be at least 1")
        with self._write() as connection:
            (pending,) = connection.execute(
                "SELECT COUNT(*) FROM extraction_queue WHERE status = 'pending'"
            ).fetchone()
            overflow = pending - max_pending + 1
            if overflow > 0:
                connection.execute(
                    "DELETE FROM extraction_queue WHERE id IN (SELECT id FROM extraction_queue "
                    "WHERE status = 'pending' ORDER BY id LIMIT ?)",
                    (overflow,),
                )
                LOGGER.warning(
                    "Knowledge extraction queue is full (%d pending); dropped the oldest %d. "
                    "The conversation is still in the JSONL memory.",
                    pending,
                    overflow,
                )
            connection.execute(
                "INSERT INTO extraction_queue "
                "(kind, user_text, assistant_text, observed_at, next_attempt_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, user_text, assistant_text, observed_at, self._now()),
            )

    def claim_next(self, now: str, claim_timeout_seconds: float) -> PendingExtraction | None:
        stale_before = format_timestamp(
            datetime.fromisoformat(now) - timedelta(seconds=claim_timeout_seconds)
        )
        with self._write() as connection:
            row = connection.execute(
                "SELECT id, kind, user_text, assistant_text, observed_at, attempts "
                "FROM extraction_queue WHERE status = 'pending' AND next_attempt_at <= ? "
                "AND (claimed_at IS NULL OR claimed_at < ?) ORDER BY id LIMIT 1",
                (now, stale_before),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE extraction_queue SET claimed_at = ?, attempts = attempts + 1 WHERE id = ?",
                (now, row[0]),
            )
        item_id, kind, user_text, assistant_text, observed_at, attempts = row
        return PendingExtraction(item_id, kind, user_text, assistant_text, observed_at, attempts + 1)

    def complete(self, item_id: int, delta: GraphDelta) -> list[GraphEvent]:
        with self._write() as connection:
            row = connection.execute(
                "SELECT observed_at FROM extraction_queue WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                LOGGER.warning("Extraction %d is no longer queued; its delta was not applied.", item_id)
                return []
            events = self._apply(connection, delta, row[0])
            connection.execute("DELETE FROM extraction_queue WHERE id = ?", (item_id,))
            return events

    def fail(self, item_id: int, error: str, retry_at: str | None) -> None:
        with self._write() as connection:
            if retry_at is None:
                connection.execute(
                    "UPDATE extraction_queue SET status = 'failed', claimed_at = NULL, "
                    "last_error = ? WHERE id = ?",
                    (error[:_MAX_ERROR_LENGTH], item_id),
                )
            else:
                connection.execute(
                    "UPDATE extraction_queue SET next_attempt_at = ?, claimed_at = NULL, "
                    "last_error = ? WHERE id = ?",
                    (retry_at, error[:_MAX_ERROR_LENGTH], item_id),
                )

    def pending_count(self) -> int:
        with self._read() as connection:
            (count,) = connection.execute(
                "SELECT COUNT(*) FROM extraction_queue WHERE status = 'pending'"
            ).fetchone()
        return count

    # connections and migration

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, isolation_level=None, timeout=5.0)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA synchronous = NORMAL")
        except BaseException:
            connection.close()
            raise
        return connection

    @contextmanager
    def _transaction(self, begin: str) -> Iterator[sqlite3.Connection]:
        # ``with sqlite3.connect(...)`` does not close the connection; ``closing`` does. An open
        # connection on Windows keeps the file locked.
        with closing(self._connect()) as connection:
            connection.execute(begin)
            try:
                yield connection
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")

    def _write(self):
        return self._transaction("BEGIN IMMEDIATE")

    def _read(self):
        return self._transaction("BEGIN")

    def _migrate(self) -> None:
        with closing(self._connect()) as connection:
            version = self._user_version(connection)
            if version == SCHEMA_VERSION:
                return
            # Persistent, and it cannot change inside a transaction.
            connection.execute("PRAGMA journal_mode = WAL")
        with self._write() as connection:
            version = self._user_version(connection)
            if version == SCHEMA_VERSION:  # another process migrated in the meantime
                return
            for statement in _SCHEMA_V1:
                connection.execute(statement)
            now = self._now()
            connection.execute(
                "INSERT INTO meta (key, value) VALUES ('graph_id', ?)", (uuid.uuid4().hex,)
            )
            root = EntityProposal(
                ROOT_ENTITY_KEY, ROOT_ENTITY_NAME, EntityType.PERSONA, ROOT_ENTITY_ALIASES
            )
            root_id = self._insert_entity(connection, root, now)
            self._record(connection, "entity_created", self._entity(connection, root_id).as_node(), now)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _user_version(self, connection: sqlite3.Connection) -> int:
        (version,) = connection.execute("PRAGMA user_version").fetchone()
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"{self.path} uses schema version {version}, newer than the {SCHEMA_VERSION} "
                "this code knows; it was written by a newer Jarvis."
            )
        if version not in (0, SCHEMA_VERSION):
            raise RuntimeError(f"{self.path} has an unknown schema version {version}")
        return version

    # helpers that run inside an open transaction

    def _now(self) -> str:
        return format_timestamp(self._clock())

    def _apply(
        self, connection: sqlite3.Connection, delta: GraphDelta, observed_at: str
    ) -> list[GraphEvent]:
        now = self._now()
        events: list[GraphEvent] = []
        resolved: dict[str, int] = {}

        for proposal in delta.entities:
            key = normalize_key(proposal.key)
            if not key:
                continue
            lookup_keys = [key, *(normalize_key(alias) for alias in proposal.aliases)]
            lookup_keys.append(normalize_key(proposal.name))
            entity_id = next(
                (
                    found
                    for found in (self._resolve(connection, item) for item in lookup_keys if item)
                    if found is not None
                ),
                None,
            )
            if entity_id is None:
                entity_id = self._insert_entity(connection, proposal, now)
                node = self._entity(connection, entity_id).as_node()
                events.append(self._record(connection, "entity_created", node, now))
            elif self._add_aliases(connection, entity_id, _alias_rows(proposal)):
                # Name and type never change here, so a Gemini mistake cannot rename anyone.
                connection.execute(
                    "UPDATE entities SET updated_at = ? WHERE id = ?", (now, entity_id)
                )
                node = self._entity(connection, entity_id).as_node()
                events.append(self._record(connection, "entity_updated", node, now))
            resolved[key] = entity_id

        for proposal in delta.invalidations:
            source_id = self._endpoint(connection, resolved, proposal.source)
            target_id = self._endpoint(connection, resolved, proposal.target)
            relation_id = (
                None
                if source_id is None or target_id is None
                else self._active_relation_id(
                    connection, source_id, target_id, normalize_key(proposal.type)
                )
            )
            if relation_id is not None:
                events.append(
                    self._invalidate(connection, relation_id, observed_at, proposal.reason, now)
                )

        for proposal in delta.relations:
            source_id = self._endpoint(connection, resolved, proposal.source)
            target_id = self._endpoint(connection, resolved, proposal.target)
            relation_type = normalize_key(proposal.type)
            if source_id is None or target_id is None or source_id == target_id or not relation_type:
                LOGGER.info(
                    "Dropped relation %s —%s→ %s: unknown or identical ends.",
                    proposal.source,
                    proposal.type,
                    proposal.target,
                )
                continue
            if relation_type in SINGLE_VALUED_RELATION_TYPES:
                replaced = connection.execute(
                    "SELECT id FROM relations WHERE source_id = ? AND type = ? "
                    "AND target_id <> ? AND valid_to IS NULL ORDER BY id",
                    (source_id, relation_type, target_id),
                ).fetchall()
                for (replaced_id,) in replaced:
                    reason = f"sustituida por {proposal.fact}"
                    events.append(self._invalidate(connection, replaced_id, observed_at, reason, now))
            row = connection.execute(
                "SELECT id, fact_text FROM relations WHERE source_id = ? AND target_id = ? "
                "AND type = ? AND valid_to IS NULL",
                (source_id, target_id, relation_type),
            ).fetchone()
            if row is None:
                cursor = connection.execute(
                    "INSERT INTO relations "
                    "(source_id, target_id, type, fact_text, valid_from, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (source_id, target_id, relation_type, proposal.fact, observed_at, now),
                )
                link = self._relation(connection, cursor.lastrowid).as_link()
                events.append(self._record(connection, "relation_created", link, now))
            elif row[1] != proposal.fact:
                connection.execute(
                    "UPDATE relations SET fact_text = ? WHERE id = ?", (proposal.fact, row[0])
                )
                link = self._relation(connection, row[0]).as_link()
                events.append(self._record(connection, "relation_updated", link, now))
        return events

    def _record(self, connection: sqlite3.Connection, op: str, data: dict, ts: str) -> GraphEvent:
        cursor = connection.execute(
            "INSERT INTO events (ts, op, payload_json) VALUES (?, ?, ?)", (ts, op, _encode(data))
        )
        return GraphEvent(version=cursor.lastrowid, ts=ts, op=op, data=data)

    def _insert_entity(
        self, connection: sqlite3.Connection, proposal: EntityProposal, now: str
    ) -> int:
        cursor = connection.execute(
            "INSERT INTO entities (key, name, type, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (normalize_key(proposal.key), proposal.name, proposal.type.value, now, now),
        )
        entity_id = cursor.lastrowid
        self._add_aliases(connection, entity_id, _alias_rows(proposal))
        return entity_id

    def _add_aliases(
        self, connection: sqlite3.Connection, entity_id: int, rows: list[tuple[str, str]]
    ) -> bool:
        changed = False
        for alias_key, alias in rows:
            owner = connection.execute(
                "SELECT entity_id FROM entity_aliases WHERE alias_key = ?", (alias_key,)
            ).fetchone()
            if owner is None:
                connection.execute(
                    "INSERT INTO entity_aliases (alias_key, entity_id, alias) VALUES (?, ?, ?)",
                    (alias_key, entity_id, alias),
                )
                changed = True
            elif self._final_id(connection, owner[0]) != entity_id:
                LOGGER.info(
                    "Alias %r already belongs to entity %d; not added to entity %d.",
                    alias,
                    owner[0],
                    entity_id,
                )
        return changed

    def _invalidate(
        self, connection: sqlite3.Connection, relation_id: int, valid_to: str, reason: str, now: str
    ) -> GraphEvent:
        connection.execute(
            "UPDATE relations SET valid_to = ?, invalidation_reason = ? WHERE id = ?",
            (valid_to, reason, relation_id),
        )
        data = {"id": relation_id, "valid_to": valid_to, "reason": reason}
        return self._record(connection, "relation_invalidated", data, now)

    def _active_relation_id(
        self, connection: sqlite3.Connection, source_id: int, target_id: int, relation_type: str
    ) -> int | None:
        row = connection.execute(
            "SELECT id FROM relations WHERE source_id = ? AND target_id = ? AND type = ? "
            "AND valid_to IS NULL",
            (source_id, target_id, relation_type),
        ).fetchone()
        return None if row is None else row[0]

    def _endpoint(
        self, connection: sqlite3.Connection, resolved: dict[str, int], key: str
    ) -> int | None:
        key = normalize_key(key)
        if key in resolved:
            return resolved[key]
        return self._resolve(connection, key) if key else None

    def _resolve(self, connection: sqlite3.Connection, alias_key: str) -> int | None:
        row = connection.execute(
            "SELECT entity_id FROM entity_aliases WHERE alias_key = ?", (alias_key,)
        ).fetchone()
        return None if row is None else self._final_id(connection, row[0])

    def _require_entity(self, connection: sqlite3.Connection, key: str) -> int:
        entity_id = self._resolve(connection, normalize_key(key))
        if entity_id is None:
            raise ValueError(f"Unknown entity: {key!r}")
        return entity_id

    def _final_id(self, connection: sqlite3.Connection, entity_id: int) -> int:
        for _ in range(_MAX_MERGE_CHAIN):
            (merged_into,) = connection.execute(
                "SELECT merged_into FROM entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if merged_into is None:
                return entity_id
            entity_id = merged_into
        raise RuntimeError(f"Merge chain too long or circular at entity {entity_id}")

    def _current_version(self, connection: sqlite3.Connection) -> int:
        (version,) = connection.execute("SELECT COALESCE(MAX(version), 0) FROM events").fetchone()
        return version

    def _entity(self, connection: sqlite3.Connection, entity_id: int) -> Entity:
        return self._load_entities(connection, [entity_id])[0]

    def _relation(self, connection: sqlite3.Connection, relation_id: int) -> Relation:
        row = connection.execute(
            f"SELECT {_RELATION_COLUMNS} FROM relations WHERE id = ?", (relation_id,)
        ).fetchone()
        return _relation_from_row(row)

    def _ordered_entities(self, connection: sqlite3.Connection, ids: list[int]) -> list[Entity]:
        by_id = {entity.id: entity for entity in self._load_entities(connection, ids)}
        return [by_id[entity_id] for entity_id in ids if entity_id in by_id]

    def _load_entities(self, connection: sqlite3.Connection, ids: list[int]) -> list[Entity]:
        """Entities ordered by id. Aliases leave out the ones that only repeat the key or name."""
        rows: list[tuple] = []
        alias_rows: list[tuple] = []
        for chunk in _chunks(ids):
            marks = _placeholders(len(chunk))
            rows += connection.execute(
                "SELECT id, key, name, type, created_at, updated_at FROM entities "
                f"WHERE id IN ({marks})",
                chunk,
            ).fetchall()
            alias_rows += connection.execute(
                "SELECT rowid, entity_id, alias_key, alias FROM entity_aliases "
                f"WHERE entity_id IN ({marks})",
                chunk,
            ).fetchall()
        aliases: dict[int, list[tuple[str, str]]] = {}
        for _, entity_id, alias_key, alias in sorted(alias_rows):
            aliases.setdefault(entity_id, []).append((alias_key, alias))
        entities = []
        for entity_id, key, name, entity_type, created_at, updated_at in sorted(rows):
            hidden = {key, normalize_key(name)}
            shown = dict.fromkeys(
                alias for alias_key, alias in aliases.get(entity_id, []) if alias_key not in hidden
            )
            entities.append(
                Entity(
                    id=entity_id,
                    key=key,
                    name=name,
                    type=EntityType(entity_type),
                    aliases=tuple(shown),
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
        return entities


def _alias_rows(proposal: EntityProposal) -> list[tuple[str, str]]:
    """(alias_key, original text) for the key, the name and each alias, without repeats."""
    key = normalize_key(proposal.key)
    key_text = proposal.name if normalize_key(proposal.name) == key else key
    rows = [(key, key_text), (normalize_key(proposal.name), proposal.name)]
    rows += [(normalize_key(alias), alias) for alias in proposal.aliases]
    unique: dict[str, str] = {}
    for alias_key, alias in rows:
        if alias_key and alias_key not in unique:
            unique[alias_key] = alias
    return list(unique.items())
