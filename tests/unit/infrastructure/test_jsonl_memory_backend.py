import json
import tempfile
import unittest
from pathlib import Path

from jarvis.infrastructure.memory.jsonl_backend import JsonlMemoryBackend
from jarvis.ports.memory import MemoryEntry


def entry(role: str, content: str) -> MemoryEntry:
    return MemoryEntry("2026-01-01T00:00:00+00:00", role, content)


class JsonlMemoryBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state" / "conversation.jsonl"
        self.backend = JsonlMemoryBackend(self.path)

    def test_missing_file_reads_as_empty(self) -> None:
        self.assertEqual(self.backend.read_all(), [])
        self.assertEqual(self.backend.size_bytes(), 0)

    def test_append_writes_one_compact_json_object_per_line(self) -> None:
        self.backend.append_many([entry("user", "Hola"), entry("assistant", "Buenos días")])

        text = self.path.read_text(encoding="utf-8")
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertEqual([row["content"] for row in rows], ["Hola", "Buenos días"])
        self.assertIn("Buenos días", text)
        self.assertEqual(
            self.backend.read_all(), [entry("user", "Hola"), entry("assistant", "Buenos días")]
        )
        self.assertGreater(self.backend.size_bytes(), 0)

    def test_replace_all_swaps_the_content(self) -> None:
        self.backend.append_many([entry("user", "viejo")])

        self.backend.replace_all([entry("summary", "nuevo")])

        self.assertEqual(self.backend.read_all(), [entry("summary", "nuevo")])

    def test_backup_copies_the_current_file(self) -> None:
        self.backend.append_many([entry("user", "Hola")])

        self.backend.backup()
        self.backend.replace_all([])

        self.assertEqual(
            JsonlMemoryBackend(self.backend.backup_path).read_all(), [entry("user", "Hola")]
        )
        self.assertEqual(self.backend.backup_path.name, "conversation.jsonl.bak")

    def test_backup_without_a_file_does_nothing(self) -> None:
        self.backend.backup()

        self.assertFalse(self.backend.backup_path.exists())

    def test_truncated_final_line_is_discarded_but_mid_file_corruption_fails(self) -> None:
        valid = json.dumps({"timestamp": "t", "role": "user", "content": "válido"}).encode("utf-8")
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(valid + b"\n{partial")

        self.assertEqual([item.content for item in self.backend.read_all()], ["válido"])
        self.assertTrue(self.path.read_bytes().endswith(b"\n"))

        self.path.write_bytes(b"{invalid}\n" + valid + b"\n")
        with self.assertRaisesRegex(ValueError, "línea 1"):
            self.backend.read_all()


if __name__ == "__main__":
    unittest.main()
