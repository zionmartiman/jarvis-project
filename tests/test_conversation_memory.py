import json
from pathlib import Path
import tempfile
import threading
import unittest

from core.memory import ConversationMemory, JsonlMemoryBackend, MemoryEntry


class ConversationMemoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "conversation.jsonl"
        self.backend = JsonlMemoryBackend(self.path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_records_exchange_as_independent_json_lines(self) -> None:
        memory = ConversationMemory(self.backend, summarizer=None)

        memory.record_exchange("Hola", "Buenos días")

        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["role"] for row in rows], ["user", "assistant"])
        self.assertEqual([row["content"] for row in rows], ["Hola", "Buenos días"])
        self.assertTrue(all(row["timestamp"] for row in rows))

    def test_context_contains_summary_and_only_five_complete_interactions(self) -> None:
        entries = [MemoryEntry("2026-01-01T00:00:00+00:00", "summary", "Le gusta el té.")]
        for index in range(7):
            entries.extend(
                [
                    MemoryEntry("2026-01-01T00:00:00+00:00", "user", f"pregunta {index}"),
                    MemoryEntry("2026-01-01T00:00:00+00:00", "assistant", f"respuesta {index}"),
                ]
            )
        self.backend.replace_all(entries)

        context = ConversationMemory(self.backend, summarizer=None).get_context()

        self.assertEqual(len(context), 11)
        self.assertEqual(context[0], {"role": "summary", "text": "Le gusta el té."})
        self.assertEqual(context[1]["text"], "pregunta 2")
        self.assertEqual(context[-1]["text"], "respuesta 6")

    def test_compaction_backs_up_and_preserves_last_five_interactions(self) -> None:
        entries = []
        for index in range(6):
            entries.extend(
                [
                    MemoryEntry("2026-01-01T00:00:00+00:00", "user", f"pregunta {index}"),
                    MemoryEntry("2026-01-01T00:00:00+00:00", "assistant", f"respuesta {index}"),
                ]
            )
        self.backend.replace_all(entries)
        memory = ConversationMemory(self.backend, summarizer=lambda prompt: "Nombre: Ana; pendiente: llamar.")

        memory.compact()

        compacted = self.backend.read_all()
        self.assertEqual(compacted[0].role, "summary")
        self.assertIn("Nombre: Ana", compacted[0].content)
        self.assertEqual([entry.content for entry in compacted[1:]], [
            "pregunta 1", "respuesta 1", "pregunta 2", "respuesta 2", "pregunta 3",
            "respuesta 3", "pregunta 4", "respuesta 4", "pregunta 5", "respuesta 5",
        ])
        self.assertTrue(self.backend.backup_path.exists())
        self.assertEqual(len(self.backend.read_all()), 11)

    def test_automatic_compaction_is_scheduled_after_ten_records(self) -> None:
        summary_called = threading.Event()

        def summarize(prompt: str) -> str:
            summary_called.set()
            return "Resumen previo."

        memory = ConversationMemory(self.backend, summarizer=summarize)
        for index in range(6):
            memory.record_exchange(f"pregunta {index}", f"respuesta {index}")

        self.assertTrue(summary_called.wait(timeout=2))
        memory.compact()
        self.assertEqual(self.backend.read_all()[0].role, "summary")

    def test_size_threshold_compacts_existing_file_on_startup(self) -> None:
        entries = []
        for index in range(6):
            entries.extend(
                [
                    MemoryEntry("2026-01-01T00:00:00+00:00", "user", f"pregunta {index} " + "x" * 400),
                    MemoryEntry("2026-01-01T00:00:00+00:00", "assistant", f"respuesta {index} " + "y" * 400),
                ]
            )
        self.backend.replace_all(entries)
        summary_called = threading.Event()

        def summarize(prompt: str) -> str:
            summary_called.set()
            return "Resumen por tamaño."

        memory = ConversationMemory(
            self.backend,
            summarizer=summarize,
            max_size_bytes=4096,
            compact_after_records=100,
        )

        self.assertGreater(self.backend.size_bytes(), 4096)
        self.assertTrue(summary_called.wait(timeout=2))
        memory.compact()
        self.assertEqual(self.backend.read_all()[0].content, "Resumen por tamaño.")

    def test_truncated_final_line_is_discarded_but_mid_file_corruption_fails(self) -> None:
        valid = json.dumps({"timestamp": "t", "role": "user", "content": "válido"}).encode("utf-8")
        self.path.write_bytes(valid + b"\n{partial")

        self.assertEqual([entry.content for entry in self.backend.read_all()], ["válido"])
        self.assertTrue(self.path.read_bytes().endswith(b"\n"))

        self.path.write_bytes(b"{invalid}\n" + valid + b"\n")
        with self.assertRaisesRegex(ValueError, "línea 1"):
            self.backend.read_all()


if __name__ == "__main__":
    unittest.main()