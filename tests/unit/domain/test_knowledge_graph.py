import unittest
from datetime import datetime, timedelta, timezone

from jarvis.domain.knowledge_graph import (
    MAX_KEY_LENGTH,
    EntityProposal,
    EntityType,
    GraphDelta,
    InvalidationProposal,
    RelationProposal,
    format_timestamp,
    normalize_key,
    query_terms,
)


def relation(source: str, target: str, type_: str = "vive_en", fact: str = "Un hecho") -> dict:
    return {"source": source, "target": target, "type": type_, "fact": fact}


def entity(key: str, name: str = "Nombre", type_: str = "persona", aliases=()) -> dict:
    return {"key": key, "name": name, "type": type_, "aliases": list(aliases)}


class NormalizeKeyTest(unittest.TestCase):
    def test_removes_accents_and_lowers(self) -> None:
        self.assertEqual(normalize_key("San Sebastián"), "san_sebastian")
        self.assertEqual(normalize_key("Ñandú"), "nandu")
        self.assertEqual(normalize_key("MÁLAGA"), "malaga")

    def test_collapses_spaces_and_signs(self) -> None:
        self.assertEqual(normalize_key("  ¿Mi   hermana, Ana?  "), "mi_hermana_ana")
        self.assertEqual(normalize_key("vive-en"), "vive_en")
        self.assertEqual(normalize_key("Raspberry Pi 3B"), "raspberry_pi_3b")

    def test_empty_when_nothing_is_left(self) -> None:
        self.assertEqual(normalize_key("¡¿?!"), "")
        self.assertEqual(normalize_key(""), "")

    def test_is_cut_to_the_maximum_length_without_a_trailing_separator(self) -> None:
        key = normalize_key("palabra " * 20)

        self.assertLessEqual(len(key), MAX_KEY_LENGTH)
        self.assertFalse(key.endswith("_"))
        self.assertTrue(key.startswith("palabra_palabra"))
        self.assertEqual(normalize_key("a" * 59 + " bb"), "a" * 59)

    def test_is_idempotent(self) -> None:
        self.assertEqual(normalize_key(normalize_key("Ana García")), "ana_garcia")


class QueryTermsTest(unittest.TestCase):
    def test_drops_stopwords_only_as_single_words(self) -> None:
        terms = query_terms("¿Dónde vive mi hermana?")

        self.assertNotIn("donde", terms)
        self.assertNotIn("mi", terms)
        self.assertIn("vive", terms)
        self.assertIn("hermana", terms)
        self.assertIn("mi_hermana", terms)
        self.assertIn("vive_mi_hermana", terms)

    def test_builds_ngrams_up_to_the_maximum(self) -> None:
        terms = query_terms("San Sebastián de los Reyes")

        self.assertIn("san_sebastian", terms)
        self.assertIn("sebastian_de_los", terms)
        self.assertNotIn("san_sebastian_de_los", terms)
        self.assertEqual(query_terms("uno dos tres", max_ngram=1), ["dos", "tres"])

    def test_removes_repeats_and_accents(self) -> None:
        terms = query_terms("Málaga, malaga")

        self.assertEqual(terms.count("malaga"), 1)
        self.assertIn("malaga_malaga", terms)

    def test_empty_text(self) -> None:
        self.assertEqual(query_terms(""), [])


class GraphDeltaFromDictTest(unittest.TestCase):
    def test_parses_a_complete_delta(self) -> None:
        delta = GraphDelta.from_dict(
            {
                "entities": [entity("Ana", "Ana", "persona", ["mi hermana"])],
                "relations": [relation("ana", "valencia", "vive_en", "Ana vive en Valencia")],
                "invalidations": [
                    {"source": "ana", "target": "madrid", "type": "vive_en", "reason": "Se mudó"}
                ],
            }
        )

        self.assertEqual(
            delta.entities, (EntityProposal("ana", "Ana", EntityType.PERSONA, ("mi hermana",)),)
        )
        self.assertEqual(
            delta.relations, (RelationProposal("ana", "valencia", "vive_en", "Ana vive en Valencia"),)
        )
        self.assertEqual(
            delta.invalidations, (InvalidationProposal("ana", "madrid", "vive_en", "Se mudó"),)
        )
        self.assertFalse(delta.is_empty)

    def test_input_that_is_not_an_object_is_an_empty_delta(self) -> None:
        for value in (None, [], "texto", 3):
            with self.subTest(value=value):
                self.assertTrue(GraphDelta.from_dict(value).is_empty)

    def test_missing_or_wrong_lists_count_as_empty(self) -> None:
        delta = GraphDelta.from_dict({"entities": "no", "relations": None})

        self.assertEqual(delta, GraphDelta())

    def test_unknown_entity_type_becomes_concepto(self) -> None:
        delta = GraphDelta.from_dict({"entities": [entity("x", type_="planeta")]})

        self.assertEqual(delta.entities[0].type, EntityType.CONCEPTO)

    def test_empty_keys_and_items_that_are_not_objects_are_dropped(self) -> None:
        delta = GraphDelta.from_dict(
            {
                "entities": [entity("¿?"), entity("ok", name="  "), "ana", entity("bien")],
                "relations": [relation("¿?", "b"), relation("a", "b", type_="!!"), [], relation("a", "b")],
            }
        )

        self.assertEqual([item.key for item in delta.entities], ["bien"])
        self.assertEqual(len(delta.relations), 1)

    def test_relation_and_entity_type_keys_are_normalized(self) -> None:
        delta = GraphDelta.from_dict({"relations": [relation("Ana García", "Málaga", "Vive en")]})

        self.assertEqual(delta.relations[0].source, "ana_garcia")
        self.assertEqual(delta.relations[0].target, "malaga")
        self.assertEqual(delta.relations[0].type, "vive_en")

    def test_loops_are_dropped(self) -> None:
        delta = GraphDelta.from_dict(
            {
                "relations": [relation("ana", "Ana")],
                "invalidations": [{"source": "a", "target": "a", "type": "t", "reason": "r"}],
            }
        )

        self.assertTrue(delta.is_empty)

    def test_lists_are_capped(self) -> None:
        delta = GraphDelta.from_dict(
            {
                "entities": [entity(f"e{index}") for index in range(20)],
                "relations": [relation(f"a{index}", "b") for index in range(20)],
                "invalidations": [
                    {"source": f"a{index}", "target": "b", "type": "t", "reason": ""}
                    for index in range(20)
                ],
            }
        )

        self.assertEqual(len(delta.entities), 10)
        self.assertEqual(len(delta.relations), 15)
        self.assertEqual(len(delta.invalidations), 10)

    def test_invalid_items_do_not_use_up_the_cap(self) -> None:
        delta = GraphDelta.from_dict({"entities": [entity("")] * 10 + [entity("ana")]})

        self.assertEqual([item.key for item in delta.entities], ["ana"])

    def test_texts_and_aliases_are_limited(self) -> None:
        delta = GraphDelta.from_dict(
            {
                "entities": [
                    entity(
                        "ana",
                        name="N" * 100,
                        aliases=["a1", "a2", 7, "a" * 61, "a1", "", "a3", "a4", "a5", "a6"],
                    )
                ],
                "relations": [relation("ana", "b", fact="F" * 300)],
                "invalidations": [{"source": "ana", "target": "b", "type": "t", "reason": "R" * 300}],
            }
        )

        self.assertEqual(len(delta.entities[0].name), 80)
        self.assertEqual(delta.entities[0].aliases, ("a1", "a2", "a3", "a4", "a5"))
        self.assertEqual(len(delta.relations[0].fact), 200)
        self.assertEqual(len(delta.invalidations[0].reason), 200)

    def test_relation_without_fact_is_dropped_but_invalidation_without_reason_is_kept(self) -> None:
        delta = GraphDelta.from_dict(
            {
                "relations": [relation("a", "b", fact=" ")],
                "invalidations": [{"source": "a", "target": "b", "type": "t"}],
            }
        )

        self.assertEqual(delta.relations, ())
        self.assertEqual(delta.invalidations, (InvalidationProposal("a", "b", "t", ""),))

    def test_relation_type_alias_is_rewritten_and_inverted(self) -> None:
        # Phase 0: Gemini answered «mi hermana se llama Ana» with usuario —tiene_hermana→ ana.
        delta = GraphDelta.from_dict(
            {
                "relations": [relation("usuario", "ana", "tiene_hermana", "Ana es la hermana del usuario")],
                "invalidations": [
                    {"source": "usuario", "target": "ana", "type": "tiene_hermana", "reason": "r"}
                ],
            }
        )

        self.assertEqual(
            delta.relations,
            (RelationProposal("ana", "usuario", "hermana_de", "Ana es la hermana del usuario"),),
        )
        self.assertEqual(
            delta.invalidations, (InvalidationProposal("ana", "usuario", "hermana_de", "r"),)
        )


class KinshipAliasesTest(unittest.TestCase):
    def test_relative_of_the_user_gets_the_alias_the_user_says(self) -> None:
        delta = GraphDelta.from_dict(
            {
                "entities": [entity("ana", "Ana", "persona")],
                "relations": [relation("ana", "usuario", "hermana_de", "Ana es la hermana del usuario")],
            }
        )

        self.assertEqual(delta.entities[0].aliases, ("mi hermana", "hermana"))

    def test_inverted_form_from_gemini_also_gets_it(self) -> None:
        delta = GraphDelta.from_dict(
            {
                "entities": [entity("ana", "Ana", "persona", ["la peque"])],
                "relations": [relation("usuario", "ana", "tiene_hermana", "Ana es la hermana del usuario")],
            }
        )

        self.assertEqual(delta.entities[0].aliases, ("mi hermana", "hermana", "la peque"))

    def test_existing_alias_is_not_repeated_and_the_limit_holds(self) -> None:
        delta = GraphDelta.from_dict(
            {
                "entities": [entity("ana", "Ana", "persona", ["Mi hermana", "a1", "a2", "a3", "a4"])],
                "relations": [relation("ana", "usuario", "hermana_de")],
            }
        )

        self.assertEqual(delta.entities[0].aliases, ("mi hermana", "hermana", "a1", "a2", "a3"))

    def test_only_relatives_of_the_user_declared_in_the_delta(self) -> None:
        delta = GraphDelta.from_dict(
            {
                "entities": [entity("ana", "Ana"), entity("luis", "Luis")],
                "relations": [
                    relation("ana", "luis", "hermana_de"),
                    relation("luis", "usuario", "amigo_de"),
                    relation("marta", "usuario", "madre_de"),
                ],
            }
        )

        self.assertEqual([item.aliases for item in delta.entities], [(), ()])


class FormatTimestampTest(unittest.TestCase):
    def test_utc_with_whole_seconds(self) -> None:
        moment = datetime(2026, 10, 25, 20, 2, 11, 999999, tzinfo=timezone(timedelta(hours=2)))

        self.assertEqual(format_timestamp(moment), "2026-10-25T18:02:11+00:00")


if __name__ == "__main__":
    unittest.main()
