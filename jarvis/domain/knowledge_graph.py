"""Knowledge-graph memory data: entities, relations, the deltas Gemini proposes and their events."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import TypeVar

ROOT_ENTITY_KEY = "usuario"
ROOT_ENTITY_NAME = "Usuario"
ROOT_ENTITY_ALIASES = ("yo",)

# Relations where a subject has a single current value: a new one replaces the previous one.
SINGLE_VALUED_RELATION_TYPES = frozenset({"vive_en", "trabaja_en", "se_llama", "pareja_de"})
# Observed relation type -> (canonical type, swap source and target). Grows with what Gemini
# returns in practice; Phase 0 found ``usuario —tiene_hermana→ ana`` for ``ana —hermana_de→ usuario``.
RELATION_TYPE_ALIASES: dict[str, tuple[str, bool]] = {"tiene_hermana": ("hermana_de", True)}
# Kinship type -> how the user names that relative, so «mi hermana» finds «ana». It is added as an
# alias of the relative when ``<relative> —type→ usuario`` arrives with the relative in the delta.
KINSHIP_ALIASES: dict[str, tuple[str, ...]] = {
    "hermana_de": ("mi hermana", "hermana"),
    "hermano_de": ("mi hermano", "hermano"),
    "madre_de": ("mi madre", "madre"),
    "padre_de": ("mi padre", "padre"),
}

MAX_KEY_LENGTH = 60
MAX_ENTITIES = 10
MAX_RELATIONS = 15
MAX_INVALIDATIONS = 10
MAX_NAME_LENGTH = 80
MAX_FACT_LENGTH = 200
MAX_REASON_LENGTH = 200
MAX_ALIASES = 5
MAX_ALIAS_LENGTH = 60

# Already folded (no accents, lower case). Only removed from single-word query terms.
SPANISH_STOPWORDS = frozenset(
    {
        "a", "al", "algo", "como", "con", "cual", "cuales", "cuando", "de", "del", "donde",
        "el", "ella", "ellas", "ellos", "en", "era", "es", "esa", "ese", "eso", "esta", "estan",
        "estas", "este", "esto", "fue", "ha", "han", "hay", "he", "la", "las", "le", "les", "lo",
        "los", "mas", "me", "mi", "mis", "muy", "no", "nos", "o", "para", "pero", "por", "que",
        "quien", "se", "si", "sin", "sobre", "son", "su", "sus", "te", "tu", "tus", "un", "una",
        "unas", "uno", "unos", "y", "ya",
    }
)

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


class EntityType(str, Enum):
    PERSONA = "persona"
    LUGAR = "lugar"
    PROYECTO = "proyecto"
    DISPOSITIVO = "dispositivo"
    PREFERENCIA = "preferencia"
    TAREA = "tarea"
    EVENTO = "evento"
    CONCEPTO = "concepto"


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_ALPHANUMERIC.sub("_", without_marks.lower()).strip("_")


def normalize_key(text: str) -> str:
    """NFKD without diacritics, lower case; runs of anything but [a-z0-9] become one '_'."""
    return _fold(text)[:MAX_KEY_LENGTH].rstrip("_")


def query_terms(text: str, max_ngram: int = 3) -> list[str]:
    """Normalized 1..max_ngram word n-grams joined by '_'; stopwords only dropped as unigrams."""
    words = [word for word in _fold(text).split("_") if word]
    terms: list[str] = []
    seen: set[str] = set()
    for size in range(1, max_ngram + 1):
        for start in range(len(words) - size + 1):
            gram = words[start : start + size]
            if size == 1 and gram[0] in SPANISH_STOPWORDS:
                continue
            term = normalize_key("_".join(gram))
            if term and term not in seen:
                seen.add(term)
                terms.append(term)
    return terms


def format_timestamp(moment: datetime) -> str:
    """ISO 8601 in UTC with whole seconds; these strings sort chronologically."""
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Entity:
    id: int
    key: str
    name: str
    type: EntityType
    aliases: tuple[str, ...]
    created_at: str
    updated_at: str

    def as_node(self) -> dict:
        """The JSON node the browser and the events use."""
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "type": self.type.value,
            "aliases": list(self.aliases),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class Relation:
    id: int
    source_id: int
    target_id: int
    type: str
    fact: str
    valid_from: str
    valid_to: str | None

    def as_link(self) -> dict:
        """The JSON link the browser and the events use; source and target are entity ids."""
        return {
            "id": self.id,
            "source": self.source_id,
            "target": self.target_id,
            "type": self.type,
            "fact": self.fact,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
        }


@dataclass(frozen=True)
class KnownGraph:
    """What Gemini is shown before extracting."""

    entities: tuple[Entity, ...]
    relations: tuple[Relation, ...]


@dataclass(frozen=True)
class EntityProposal:
    key: str
    name: str
    type: EntityType
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelationProposal:
    source: str
    target: str
    type: str
    fact: str


@dataclass(frozen=True)
class InvalidationProposal:
    source: str
    target: str
    type: str
    reason: str


_Proposal = TypeVar("_Proposal", RelationProposal, InvalidationProposal)


def canonical_relation(proposal: _Proposal) -> _Proposal:
    """Rewrite a known synonym to its canonical type, swapping the direction when needed."""
    canonical = RELATION_TYPE_ALIASES.get(proposal.type)
    if canonical is None:
        return proposal
    relation_type, swap = canonical
    if swap:
        return replace(proposal, source=proposal.target, target=proposal.source, type=relation_type)
    return replace(proposal, type=relation_type)


@dataclass(frozen=True)
class GraphDelta:
    entities: tuple[EntityProposal, ...] = ()
    relations: tuple[RelationProposal, ...] = ()
    invalidations: tuple[InvalidationProposal, ...] = ()

    @classmethod
    def from_dict(cls, value: object) -> GraphDelta:
        """Defensive parse of Gemini's JSON: anything that breaks a rule is dropped silently."""
        if not isinstance(value, dict):
            return cls()
        entities = _parse_items(value.get("entities"), _parse_entity, MAX_ENTITIES)
        relations = _parse_items(value.get("relations"), _parse_relation, MAX_RELATIONS)
        return cls(
            entities=_with_kinship_aliases(entities, relations),
            relations=relations,
            invalidations=_parse_items(
                value.get("invalidations"), _parse_invalidation, MAX_INVALIDATIONS
            ),
        )

    @property
    def is_empty(self) -> bool:
        return not (self.entities or self.relations or self.invalidations)


@dataclass(frozen=True)
class GraphEvent:
    version: int
    ts: str
    op: str
    data: dict


@dataclass(frozen=True)
class GraphSnapshot:
    graph_id: str
    version: int
    nodes: tuple[dict, ...]
    links: tuple[dict, ...]


def _parse_items(raw: object, parse, limit: int) -> tuple:
    if not isinstance(raw, list):
        return ()
    items = []
    for item in raw:
        if len(items) == limit:
            break
        parsed = parse(item) if isinstance(item, dict) else None
        if parsed is not None:
            items.append(parsed)
    return tuple(items)


def _with_kinship_aliases(
    entities: tuple[EntityProposal, ...], relations: tuple[RelationProposal, ...]
) -> tuple[EntityProposal, ...]:
    """Give each relative of the user declared in the delta the alias the user would say."""
    kinship = {
        relation.source: KINSHIP_ALIASES[relation.type]
        for relation in relations
        if relation.target == ROOT_ENTITY_KEY and relation.type in KINSHIP_ALIASES
    }
    result = []
    for proposal in entities:
        extra = kinship.get(proposal.key)
        if extra is None:
            result.append(proposal)
            continue
        aliases: list[str] = []
        seen: set[str] = set()
        for alias in (*extra, *proposal.aliases):
            alias_key = normalize_key(alias)
            if alias_key not in seen:
                seen.add(alias_key)
                aliases.append(alias)
        result.append(replace(proposal, aliases=tuple(aliases[:MAX_ALIASES])))
    return tuple(result)


def _text(value: object, max_length: int) -> str:
    return value.strip()[:max_length].strip() if isinstance(value, str) else ""


def _key(value: object) -> str:
    return normalize_key(value) if isinstance(value, str) else ""


def _parse_entity(item: dict) -> EntityProposal | None:
    key = _key(item.get("key"))
    name = _text(item.get("name"), MAX_NAME_LENGTH)
    if not key or not name:
        return None
    try:
        entity_type = EntityType(item.get("type"))
    except ValueError:
        entity_type = EntityType.CONCEPTO
    aliases: list[str] = []
    raw_aliases = item.get("aliases")
    for alias in raw_aliases if isinstance(raw_aliases, list) else ():
        if len(aliases) == MAX_ALIASES:
            break
        if not isinstance(alias, str):
            continue
        alias = alias.strip()
        if alias and len(alias) <= MAX_ALIAS_LENGTH and normalize_key(alias) and alias not in aliases:
            aliases.append(alias)
    return EntityProposal(key=key, name=name, type=entity_type, aliases=tuple(aliases))


def _parse_relation(item: dict) -> RelationProposal | None:
    source, target, relation_type = (_key(item.get(field)) for field in ("source", "target", "type"))
    fact = _text(item.get("fact"), MAX_FACT_LENGTH)
    if not (source and target and relation_type and fact) or source == target:
        return None
    return canonical_relation(RelationProposal(source, target, relation_type, fact))


def _parse_invalidation(item: dict) -> InvalidationProposal | None:
    source, target, relation_type = (_key(item.get(field)) for field in ("source", "target", "type"))
    if not (source and target and relation_type) or source == target:
        return None
    reason = _text(item.get("reason"), MAX_REASON_LENGTH)
    return canonical_relation(InvalidationProposal(source, target, relation_type, reason))
