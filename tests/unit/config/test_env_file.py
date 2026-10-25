import tempfile
import unittest
from pathlib import Path

from jarvis.config.env_file import read_env_file


class ReadEnvFileTest(unittest.TestCase):
    def read(self, content: str) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "sample.env"
            path.write_text(content, encoding="utf-8")
            return read_env_file(path)

    def test_reads_quoted_and_unquoted_values(self) -> None:
        values = self.read(
            'AZURE_SPEECH_KEY="secret-key"\n'
            "AZURE_SPEECH_REGION='eastus'\n"
            "OTHER_VALUE=plain-value\n"
        )

        self.assertEqual(values["AZURE_SPEECH_KEY"], "secret-key")
        self.assertEqual(values["AZURE_SPEECH_REGION"], "eastus")
        self.assertEqual(values["OTHER_VALUE"], "plain-value")

    def test_ignores_comments_blank_lines_and_lines_without_equals(self) -> None:
        values = self.read("# comment\n\nnot a pair\nKEY = value \n")

        self.assertEqual(values, {"KEY": "value"})

    def test_keeps_equals_signs_inside_the_value(self) -> None:
        self.assertEqual(self.read("URL=https://x.test/?a=b\n"), {"URL": "https://x.test/?a=b"})

    def test_keeps_mismatched_or_lone_quotes(self) -> None:
        values = self.read("A=\"abc'\nB=\"\n")

        self.assertEqual(values, {"A": "\"abc'", "B": '"'})

    def test_missing_file_raises(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "No existe la configuración"):
            read_env_file(Path("does-not-exist.env"))


if __name__ == "__main__":
    unittest.main()
