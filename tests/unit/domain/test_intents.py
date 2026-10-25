import unittest

from jarvis.domain.intents import Intent, classify, is_confirmation, normalize_text


class NormalizeTextTest(unittest.TestCase):
    def test_removes_case_accents_and_punctuation(self) -> None:
        self.assertEqual(normalize_text("  ¡Apágate!  "), "apagate")
        self.assertEqual(normalize_text("PAUSAR, conversación."), "pausar conversacion")
        self.assertEqual(normalize_text("Sí"), "si")


class ClassifyTest(unittest.TestCase):
    PHRASES = {
        Intent.SHUTDOWN: [
            "apaga la raspberry",
            "apagar la raspberry",
            "apaga el sistema",
            "apagar el sistema",
            "apágate",
            "apagar",
        ],
        Intent.REBOOT: [
            "reinicia la raspberry",
            "reiniciar la raspberry",
            "reinicia el sistema",
            "reiniciar el sistema",
            "reiníciate",
            "reinicia",
        ],
        Intent.END_CONVERSATION: [
            "buenas noches",
            "pausar",
            "páusate",
            "pausar conversación",
            "espera",
            "espérate",
            "descansa",
        ],
        Intent.SWITCH_MODEL: ["cambiar de modelo"],
    }
    CONFIRMATIONS = ["sí", "dale", "confirmo", "confirmar", "adelante", "claro"]

    def test_reserved_phrases_with_accents_and_case(self) -> None:
        for intent, phrases in self.PHRASES.items():
            for phrase in phrases:
                for variant in (phrase, phrase.upper(), f"  {phrase.capitalize()}. "):
                    with self.subTest(intent=intent, phrase=variant):
                        self.assertIs(classify(variant), intent)

    def test_ordinary_text_is_a_question(self) -> None:
        for phrase in ("¿qué hora es?", "no", "cambiar", "apaga la luz", "", "sí"):
            with self.subTest(phrase=phrase):
                self.assertIs(classify(phrase), Intent.QUESTION)

    def test_confirmation_phrases(self) -> None:
        for phrase in self.CONFIRMATIONS:
            for variant in (phrase, phrase.upper(), f"  {phrase.capitalize()}. "):
                with self.subTest(phrase=variant):
                    self.assertTrue(is_confirmation(variant))

    def test_other_text_is_not_a_confirmation(self) -> None:
        for phrase in ("no", "quizá", "apágate", "cambiar de modelo", ""):
            with self.subTest(phrase=phrase):
                self.assertFalse(is_confirmation(phrase))


if __name__ == "__main__":
    unittest.main()
