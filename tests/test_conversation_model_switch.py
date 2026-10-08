import unittest
from contextlib import redirect_stdout
from io import StringIO
import threading

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
        self.interruptions = 0

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def interrupt(self) -> None:
        self.interruptions += 1


class InterruptibleSynthesizer(FakeSynthesizer):
    def __init__(self) -> None:
        super().__init__()
        self.reply_started = threading.Event()
        self.interrupted = threading.Event()

    def speak(self, text: str) -> None:
        super().speak(text)
        if text == "respuesta":
            self.reply_started.set()
            self.interrupted.wait(timeout=5)

    def interrupt(self) -> None:
        super().interrupt()
        self.interrupted.set()


class FakeBridge:
    def __init__(self, response: str = "respuesta") -> None:
        self.response = response

    def ask(self, message: str, history: list[dict]) -> str:
        return self.response


class BlockingBridge:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def ask(self, message: str, history: list[dict]) -> str:
        self.started.set()
        self.release.wait(timeout=5)
        return "respuesta tardía"


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

    def test_logs_user_and_active_model_in_dialogue_order(self) -> None:
        output = StringIO()
        orchestrator = self.create_orchestrator(
            FakeRecognizer(["Hola", "cambiar de modelo", "Prueba con Vento", "buenas noches"]),
            FakeSynthesizer(),
            lambda model: FakeBridge(f"respuesta de {model}"),
        )
        orchestrator._active_model = "gemini"
        orchestrator._bridge = FakeBridge("respuesta de gemini")

        with redirect_stdout(output):
            orchestrator._run_conversation()

        self.assertEqual(
            output.getvalue().splitlines(),
            [
                "Yo: Hola",
                "Gemini: respuesta de gemini",
                "Yo: cambiar de modelo",
                "Yo: Prueba con Vento",
                "Vento: respuesta de vento",
                "Yo: buenas noches",
            ],
        )

    def test_interrupt_button_aborts_wait_for_each_model(self) -> None:
        for model in ("gemini", "vento"):
            with self.subTest(model=model):
                interrupt_event = threading.Event()
                bridge = BlockingBridge()
                synthesizer = FakeSynthesizer()
                orchestrator = ConversationOrchestrator(
                    microphone=FakeMicrophone(),
                    recognizer=FakeRecognizer(),
                    synthesizer=synthesizer,
                    bridge_factory=lambda selected: FakeBridge(),
                    power_controller=FakePowerController(),
                    status_indicator=FakeStatusIndicator(),
                    max_history_items=10,
                    response_interrupt_event=interrupt_event,
                )
                orchestrator._active_model = model
                orchestrator._bridge = bridge
                watcher = threading.Thread(
                    target=orchestrator._watch_response_interrupt_button,
                    daemon=True,
                )
                turn = threading.Thread(
                    target=orchestrator._handle_turn,
                    args=("Hola", []),
                    daemon=True,
                )
                watcher.start()
                turn.start()

                try:
                    self.assertTrue(bridge.started.wait(timeout=1))
                    interrupt_event.set()
                    turn.join(timeout=1)

                    self.assertFalse(turn.is_alive())
                    self.assertEqual(synthesizer.spoken, ["¿Sí?"])
                    self.assertEqual(synthesizer.interruptions, 0)
                finally:
                    bridge.release.set()
                    orchestrator._shutdown_started.set()
                    interrupt_event.set()
                    watcher.join(timeout=1)
                    turn.join(timeout=1)

    def test_interrupt_button_stops_spoken_reply_and_says_si(self) -> None:
        interrupt_event = threading.Event()
        synthesizer = InterruptibleSynthesizer()
        orchestrator = ConversationOrchestrator(
            microphone=FakeMicrophone(),
            recognizer=FakeRecognizer(),
            synthesizer=synthesizer,
            bridge_factory=lambda model: FakeBridge(),
            power_controller=FakePowerController(),
            status_indicator=FakeStatusIndicator(),
            max_history_items=10,
            response_interrupt_event=interrupt_event,
        )
        orchestrator._active_model = "gemini"
        orchestrator._bridge = FakeBridge("respuesta")
        watcher = threading.Thread(
            target=orchestrator._watch_response_interrupt_button,
            daemon=True,
        )
        turn = threading.Thread(
            target=orchestrator._handle_turn,
            args=("Hola", []),
            daemon=True,
        )
        watcher.start()
        turn.start()

        try:
            self.assertTrue(synthesizer.reply_started.wait(timeout=1))
            interrupt_event.set()
            turn.join(timeout=1)

            self.assertFalse(turn.is_alive())
            self.assertEqual(synthesizer.spoken, ["respuesta", "¿Sí?"])
            self.assertEqual(synthesizer.interruptions, 1)
        finally:
            orchestrator._shutdown_started.set()
            interrupt_event.set()
            watcher.join(timeout=1)
            turn.join(timeout=1)


if __name__ == "__main__":
    unittest.main()