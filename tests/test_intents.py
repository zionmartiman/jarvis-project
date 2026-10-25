import unittest

from core import intents


class NormalizeTextTest(unittest.TestCase):
    def test_removes_case_accents_and_punctuation(self) -> None:
        self.assertEqual(intents.normalize_text("  ¡Apágate!  "), "apagate")
        self.assertEqual(intents.normalize_text("PAUSAR, conversación."), "pausar conversacion")
        self.assertEqual(intents.normalize_text("Sí"), "si")


class IntentPhrasesTest(unittest.TestCase):
    SHUTDOWN = [
        "apaga la raspberry",
        "apagar la raspberry",
        "apaga el sistema",
        "apagar el sistema",
        "apágate",
        "apagar",
    ]
    REBOOT = [
        "reinicia la raspberry",
        "reiniciar la raspberry",
        "reinicia el sistema",
        "reiniciar el sistema",
        "reiníciate",
        "reinicia",
    ]
    END_CONVERSATION = [
        "buenas noches",
        "pausar",
        "páusate",
        "pausar conversación",
        "espera",
        "espérate",
        "descansa",
    ]
    CHANGE_MODEL = ["cambiar de modelo"]
    CONFIRMATION = ["sí", "dale", "confirmo", "confirmar", "adelante", "claro"]

    def assert_only_matches(self, phrases: list[str], matcher) -> None:
        detectors = {
            "wants_to_shutdown": intents.wants_to_shutdown,
            "wants_to_reboot": intents.wants_to_reboot,
            "wants_to_end_conversation": intents.wants_to_end_conversation,
            "wants_to_change_model": intents.wants_to_change_model,
            "is_confirmation": intents.is_confirmation,
        }
        for phrase in phrases:
            for variant in (phrase, phrase.upper(), f"  {phrase.capitalize()}. "):
                for name, detector in detectors.items():
                    with self.subTest(phrase=variant, detector=name):
                        self.assertEqual(detector(variant), detector is matcher)

    def test_shutdown_phrases(self) -> None:
        self.assert_only_matches(self.SHUTDOWN, intents.wants_to_shutdown)

    def test_reboot_phrases(self) -> None:
        self.assert_only_matches(self.REBOOT, intents.wants_to_reboot)

    def test_end_conversation_phrases(self) -> None:
        self.assert_only_matches(self.END_CONVERSATION, intents.wants_to_end_conversation)

    def test_change_model_phrases(self) -> None:
        self.assert_only_matches(self.CHANGE_MODEL, intents.wants_to_change_model)

    def test_confirmation_phrases(self) -> None:
        self.assert_only_matches(self.CONFIRMATION, intents.is_confirmation)

    def test_ordinary_questions_match_nothing(self) -> None:
        for phrase in ("¿qué hora es?", "no", "cambiar", "apaga la luz", ""):
            with self.subTest(phrase=phrase):
                self.assertFalse(intents.wants_to_shutdown(phrase))
                self.assertFalse(intents.wants_to_reboot(phrase))
                self.assertFalse(intents.wants_to_end_conversation(phrase))
                self.assertFalse(intents.wants_to_change_model(phrase))
                self.assertFalse(intents.is_confirmation(phrase))


if __name__ == "__main__":
    unittest.main()
