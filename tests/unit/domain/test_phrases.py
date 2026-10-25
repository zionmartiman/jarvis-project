import unittest

from jarvis.domain import phrases
from jarvis.domain.assistant_model import AssistantModel


class PhrasesTest(unittest.TestCase):
    def test_spoken_texts_are_unchanged(self) -> None:
        self.assertEqual(phrases.SYSTEMS_READY, "Sistemas listos.")
        self.assertEqual(phrases.WAKE_ACK, "Dime")
        self.assertEqual(phrases.STANDBY, "Sistema detenido hasta nueva orden.")
        self.assertEqual(phrases.INTERRUPT_ACK, "¿Sí?")
        self.assertEqual(
            phrases.PROCESSING_ERROR,
            "Lo siento, he tenido un problema al procesar la petición. Puede repetirla.",
        )
        self.assertEqual(
            phrases.EMERGENCY_SHUTDOWN,
            "Apagado manual accionado!, apagando sistemas. Venga, chao!",
        )
        self.assertEqual(phrases.SHUTDOWN_CANCELLED, "Apagado cancelado, señor.")
        self.assertEqual(phrases.REBOOT_CANCELLED, "Reinicio cancelado, señor.")

    def test_cannot_prepare_names_the_model(self) -> None:
        self.assertEqual(
            phrases.CANNOT_PREPARE.format(name=AssistantModel.VENTO.display_name),
            "No puedo preparar Vento.",
        )

    def test_switch_announcements(self) -> None:
        self.assertEqual(phrases.SWITCHED_TO[AssistantModel.VENTO], "Cambiando a Vento.")
        self.assertEqual(phrases.SWITCHED_TO[AssistantModel.GEMINI], "Cambiando a Gemini.")


if __name__ == "__main__":
    unittest.main()
