import os
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.config.settings import load_settings
from jarvis.infrastructure.runtime import runtime_dir

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class RuntimeDirTest(unittest.TestCase):
    def test_uses_the_current_uid(self) -> None:
        with patch.object(os, "getuid", create=True, return_value=1234):
            self.assertEqual(runtime_dir(), Path("/run/user/1234"))

    def test_falls_back_to_uid_1000_without_getuid(self) -> None:
        with patch("jarvis.infrastructure.runtime.hasattr", create=True, return_value=False):
            self.assertEqual(runtime_dir(), Path("/run/user/1000"))


class LoadSettingsTest(unittest.TestCase):
    def test_default_values_match_the_original_configuration(self) -> None:
        settings = load_settings(Path("base"))

        self.assertEqual(settings.audio.sample_rate, 16000)
        self.assertEqual(settings.audio.input_device, 1)
        self.assertEqual(settings.audio.output_device, "plughw:0,0")
        self.assertEqual(settings.audio.azure_voice, "es-ES-AlvaroNeural")
        self.assertEqual(settings.conversation.short_term_history_messages, 6)
        self.assertEqual(settings.memory.max_bytes, 4096)
        self.assertEqual(settings.memory.compact_after_messages, 10)
        self.assertEqual(settings.memory.recent_exchanges, 5)
        self.assertEqual(settings.memory.gemini_history_messages, 11)
        self.assertEqual(settings.gemini.default_model, "gemini-2.5-flash")
        self.assertEqual(settings.gemini.timeout_seconds, 130)
        self.assertEqual(settings.vento.timeout_seconds, 130)
        self.assertEqual(settings.arduino.serial_port, "/dev/ttyACM0")
        self.assertEqual(settings.arduino.baudrate, 115200)
        self.assertEqual(settings.arduino.button_poll_seconds, 0.1)
        self.assertEqual(settings.announcements.max_characters, 500)
        self.assertEqual(settings.announcements.max_datagram_bytes, 2048)
        self.assertEqual(settings.tank.poll_interval_seconds, 5.0)
        self.assertEqual(settings.tank.empty_distance_cm, 80.0)
        self.assertEqual(settings.tank.full_distance_cm, 9.0)
        self.assertEqual(settings.tank.min_change_percentage, 5)
        self.assertEqual(settings.tank.min_alert_interval_seconds, 5.0)
        self.assertEqual(settings.web.host, "0.0.0.0")
        self.assertEqual(settings.web.port, 8765)

    def test_the_graph_memory_is_switched_on_by_default(self) -> None:
        knowledge = load_settings(Path("base")).knowledge

        self.assertEqual(knowledge.path, Path("base") / "state" / "knowledge_graph.sqlite3")
        self.assertTrue(knowledge.extraction_enabled)
        self.assertTrue(knowledge.retrieval_enabled)
        self.assertIsNone(knowledge.extraction_model)
        self.assertIsNone(knowledge.extraction_thinking)

    def test_project_paths_are_relative_to_the_base_directory(self) -> None:
        base = Path("base")
        settings = load_settings(base)

        self.assertEqual(
            settings.audio.vosk_model_path, base / "models" / "vosk-model-small-es-0.42"
        )
        self.assertEqual(settings.memory.path, base / "state" / "conversation.jsonl")
        self.assertEqual(settings.vento.credentials_path, base / "state" / "bridge.env")
        self.assertEqual(settings.gemini.system_prompt_path, base / "prompts" / "system.md")
        self.assertEqual(
            settings.tank.state_path, base / "state" / "rainwater_tank_state.json"
        )

    def test_default_base_directory_is_the_project_root(self) -> None:
        settings = load_settings()

        self.assertEqual(settings.memory.path, PROJECT_ROOT / "state" / "conversation.jsonl")
        self.assertTrue((PROJECT_ROOT / "main.py").exists())

    def test_private_credentials_live_in_the_user_config_directory(self) -> None:
        settings = load_settings(Path("base"))
        config_dir = Path.home() / ".config" / "jarvis-voice"

        self.assertEqual(settings.audio.azure_credentials_path, config_dir / "azure.env")
        self.assertEqual(settings.gemini.credentials_path, config_dir / "gemini.env")

    def test_runtime_files_live_in_the_runtime_directory(self) -> None:
        settings = load_settings(Path("base"))
        runtime = runtime_dir()

        self.assertEqual(
            settings.arduino.alert_light_socket_path, runtime / "jarvis-arduino-control.sock"
        )
        self.assertEqual(settings.announcements.socket_path, runtime / "jarvis-announcer.sock")
        self.assertEqual(
            settings.announcements.playback_lock_path, runtime / "jarvis-speech.lock"
        )


if __name__ == "__main__":
    unittest.main()
