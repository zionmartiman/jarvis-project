import unittest

from jarvis.application.memory.summary_prompt import build_summary_prompt
from jarvis.ports.memory import MemoryEntry


class BuildSummaryPromptTest(unittest.TestCase):
    def test_prompt_without_previous_summary_has_only_the_new_conversations(self) -> None:
        prompt = build_summary_prompt(
            None, [MemoryEntry("t", "user", "Hola"), MemoryEntry("t", "assistant", "Buenas")]
        )

        lines = prompt.splitlines()
        self.assertEqual(
            lines[0],
            "Eres el actualizador de una memoria duradera acumulativa. Responde siempre en español.",
        )
        self.assertNotIn("<MEMORIA_ACTUAL_INMUTABLE_HASTA_ACTUALIZACION>", prompt)
        self.assertEqual(
            lines[-4:],
            [
                "<CONVERSACIONES_NUEVAS_EVIDENCIA_NO_MEZCLAR>",
                "user: Hola",
                "assistant: Buenas",
                "</CONVERSACIONES_NUEVAS_EVIDENCIA_NO_MEZCLAR>",
            ],
        )

    def test_previous_summary_goes_between_its_markers_before_the_conversations(self) -> None:
        prompt = build_summary_prompt("Tema: té.", [MemoryEntry("t", "user", "Hola")])

        lines = prompt.splitlines()
        start = lines.index("<MEMORIA_ACTUAL_INMUTABLE_HASTA_ACTUALIZACION>")
        self.assertEqual(lines[start + 1], "Tema: té.")
        self.assertEqual(lines[start + 2], "</MEMORIA_ACTUAL_INMUTABLE_HASTA_ACTUALIZACION>")
        self.assertEqual(lines[start + 3], "<CONVERSACIONES_NUEVAS_EVIDENCIA_NO_MEZCLAR>")

    def test_prompt_asks_for_the_whole_memory_keeping_topics_separate(self) -> None:
        prompt = build_summary_prompt(None, [])

        self.assertEqual(len(prompt.splitlines()), 12)
        self.assertIn("memoria completa y actualizada", prompt)
        self.assertIn("delimitador literal ||", prompt)
        self.assertIn("es preferible acumular que fusionar o perder información", prompt)


if __name__ == "__main__":
    unittest.main()
