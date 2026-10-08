import unittest

from core.conversation import ConversationOrchestrator


class FakeMicrophone:
    def clear(self) -> None:
        pass

    def stop_capture(self) -> None:
        pass


class FakeRecognizer:
    def __init__(self, sentences: list[str] | None = None, wake_error: Exception | None = None) -> None:
        self.sentences = iter(sentences or [])
        self.wake_error = wake_error

    def wait_for_wake_word(self) -> None:
        if self.wake_error is not None:
            raise self.wake_error

    def listen_for_sentence(self) -> str:
        return next(self.sentences)


class FakeSynthesizer:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def interrupt(self) -> None:
        pass


class FakeBridge:
    def ask(self, message: str, history: list[dict]) -> str:
        return "respuesta"


class FakeStatusIndicator:
    def set_status(self, status) -> None:
        pass


class FakePowerController:
    def shutdown(self) -> None:
        pass

    def reboot(self) -> None:
        pass


class ConversationModelSwitchTest(unittest.TestCase):
    def create_orchestrator(self, recognizer: FakeRecognizer, synthesizer: FakeSynthesizer, factory) -> ConversationOrchestrator:
        return ConversationOrchestrator(
            microphone=FakeMicrophone(),
            recognizer=recognizer,
            synthesizer=synthesizer,
            bridge_factory=factory,
            power_controller=FakePowerController(),
            status_indicator=FakeStatusIndicator(),
            max_history_items=10,
        )

    def test_startup_prepares_gemini_before_waiting_for_wake_word(self) -> None:
        created_models: list[str] = []
        synthesizer = FakeSynthesizer()
        recognizer = FakeRecognizer(wake_error=StopIteration())
        orchestrator = self.create_orchestrator(
            recognizer,
            synthesizer,
            lambda model: created_models.append(model) or FakeBridge(),
        )

        with self.assertRaises(StopIteration):
            orchestrator.run_forever()

        self.assertEqual(created_models, ["gemini"])
        self.assertEqual(synthesizer.spoken, ["Sistemas listos."])

    def test_voice_command_switches_models_in_both_directions(self) -> None:
        for starting_model, expected_model, expected_reply in (
            ("gemini", "vento", "Cambiando a Vento."),
            ("vento", "gemini", "Cambiar a Gemini."),
        ):
            with self.subTest(starting_model=starting_model):
                created_models: list[str] = []
                synthesizer = FakeSynthesizer()
                orchestrator = self.create_orchestrator(
                    FakeRecognizer(["cambiar de modelo", "buenas noches"]),
                    synthesizer,
                    lambda model: created_models.append(model) or FakeBridge(),
                )
                orchestrator._active_model = starting_model
                orchestrator._bridge = FakeBridge()

                orchestrator._run_conversation()

                self.assertEqual(created_models, [expected_model])
                self.assertEqual(orchestrator._active_model, expected_model)
                self.assertIn(expected_reply, synthesizer.spoken)


if __name__ == "__main__":
    unittest.main()