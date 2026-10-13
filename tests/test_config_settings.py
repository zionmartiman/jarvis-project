import tempfile
import unittest
from pathlib import Path

from config.settings import read_env_file


class ReadEnvFileTest(unittest.TestCase):
    def test_reads_quoted_and_unquoted_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "azure.env"
            config_path.write_text(
                'AZURE_SPEECH_KEY="secret-key"\n'
                "AZURE_SPEECH_REGION='eastus'\n"
                "OTHER_VALUE=plain-value\n",
                encoding="utf-8",
            )

            values = read_env_file(config_path)

        self.assertEqual(values["AZURE_SPEECH_KEY"], "secret-key")
        self.assertEqual(values["AZURE_SPEECH_REGION"], "eastus")
        self.assertEqual(values["OTHER_VALUE"], "plain-value")


if __name__ == "__main__":
    unittest.main()