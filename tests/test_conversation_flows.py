import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from core.conversation import ConversationOrchestrator
from tests.test_conversation_model_switch import (
    FakeBridge,
    FakeMicrophone,
    FakeRecognizer,
    FakeStatusIndicator,
    FakeSynthesizer,
)

PROCESSING_ERROR = "Lo siento, he tenido un problema al procesar la petición. Puede repetirla."


class RecordingPowerController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def shutdown(self) -> None:
        self.calls.append("shutdown")

    def reboot(self) -> None:
        self.calls.append("reboot")


class FailingBridge:
    def ask(self, message: str, history: list[dict]) -> str:
        raise RuntimeError("bridge down")


class HistorySizeBridge(FakeBridge):
    def __init__(self) -> None:
        super().__init__()
        self.history_sizes: list[int] = []

    def ask(self, message: str, history: list[dict]) -> str:
        self.history_sizes.append(len(history))
        return self.response


class ConversationFlowsTest(unittest.TestCase):
    def run_conversation(self, sentences: list[str], bridge=None, model: str = "gemini", history_items: int = 6):
        synthesizer = FakeSynthesizer()
        power = RecordingPowerController()
        orchestrator = ConversationOrchestrator(
            microphone=FakeMicrophone(),
            recognizer=FakeRecognizer(sentences),
            synthesizer=synthesizer,
            bridge_factory=lambda selected: bridge or FakeBridge(),
            power_controller=power,
            status_indicator=FakeStatusIndicator(),
            max_history_items=history_items,
        )
        orchestrator._active_model = model
        orchestrator._bridge = bridge or FakeBridge()
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            orchestrator._run_conversation()
        return synthesizer.spoken, power.calls

    def test_confirmed_shutdown_asks_confirms_and_powers_off(self) -> None:
        spoken, calls = self.run_conversation(["apágate", "sí"])

        self.assertEqual(
            spoken,
            [
                "Dime",
                "¿Está seguro de que quiere apagarme señor?",
                "Venga a tomar por culo. Tirando del cable... Chao!.",
            ],
        )
        self.assertEqual(calls, ["shutdown"])

    def test_cancelled_shutdown_keeps_conversation_open(self) -> None:
        spoken, calls = self.run_conversation(["apágate", "no", "buenas noches"])

        self.assertEqual(
            spoken,
            [
                "Dime",
                "¿Está seguro de que quiere apagarme señor?",
                "Apagado cancelado, señor.",
                "Sistema detenido hasta nueva orden.",
            ],
        )
        self.assertEqual(calls, [])

    def test_confirmed_reboot_asks_confirms_and_reboots(self) -> None:
        spoken, calls = self.run_conversation(["reinicia", "dale"])

        self.assertEqual(
            spoken,
            [
                "Dime",
                "¿Está seguro de que quiere reiniciarme señor?",
                "Okey reiniciando el sistema, ahora te hablo!.",
            ],
        )
        self.assertEqual(calls, ["reboot"])

    def test_cancelled_reboot_keeps_conversation_open(self) -> None:
        spoken, calls = self.run_conversation(["reiniciar el sistema", "mejor no", "descansa"])

        self.assertEqual(
            spoken,
            [
                "Dime",
                "¿Está seguro de que quiere reiniciarme señor?",
                "Reinicio cancelado, señor.",
                "Sistema detenido hasta nueva orden.",
            ],
        )
        self.assertEqual(calls, [])

    def test_good_night_ends_conversation(self) -> None:
        spoken, calls = self.run_conversation(["buenas noches"])

        self.assertEqual(spoken, ["Dime", "Sistema detenido hasta nueva orden."])
        self.assertEqual(calls, [])

    def test_bridge_error_speaks_error_phrase_and_conversation_continues(self) -> None:
        spoken, _ = self.run_conversation(["hola", "buenas noches"], bridge=FailingBridge())

        self.assertEqual(spoken, ["Dime", PROCESSING_ERROR, "Sistema detenido hasta nueva orden."])

    def test_missing_bridge_speaks_error_phrase(self) -> None:
        synthesizer = FakeSynthesizer()
        orchestrator = ConversationOrchestrator(
            microphone=FakeMicrophone(),
            recognizer=FakeRecognizer(["hola", "buenas noches"]),
            synthesizer=synthesizer,
            bridge_factory=lambda selected: FakeBridge(),
            power_controller=RecordingPowerController(),
            status_indicator=FakeStatusIndicator(),
            max_history_items=6,
        )

        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            orchestrator._run_conversation()

        self.assertEqual(synthesizer.spoken, ["Dime", PROCESSING_ERROR, "Sistema detenido hasta nueva orden."])

    def test_vento_history_is_limited_to_six_messages(self) -> None:
        bridge = HistorySizeBridge()

        self.run_conversation(
            ["uno", "dos", "tres", "cuatro", "cinco", "buenas noches"],
            bridge=bridge,
            model="vento",
        )

        self.assertEqual(bridge.history_sizes, [0, 2, 4, 6, 6])

    def test_history_keeps_latest_exchanges(self) -> None:
        orchestrator = ConversationOrchestrator(
            microphone=FakeMicrophone(),
            recognizer=FakeRecognizer(),
            synthesizer=FakeSynthesizer(),
            bridge_factory=lambda selected: FakeBridge(),
            power_controller=RecordingPowerController(),
            status_indicator=FakeStatusIndicator(),
            max_history_items=6,
        )
        orchestrator._active_model = "vento"
        orchestrator._bridge = FakeBridge("ok")
        history: list[dict] = []

        with redirect_stdout(StringIO()):
            for question in ("uno", "dos", "tres", "cuatro"):
                orchestrator._handle_turn(question, history)

        self.assertEqual(
            history,
            [
                {"role": "user", "text": "dos"},
                {"role": "assistant", "text": "ok"},
                {"role": "user", "text": "tres"},
                {"role": "assistant", "text": "ok"},
                {"role": "user", "text": "cuatro"},
                {"role": "assistant", "text": "ok"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
