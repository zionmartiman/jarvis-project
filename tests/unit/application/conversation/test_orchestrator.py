import unittest

from jarvis.domain.assistant_model import AssistantModel
from jarvis.domain.assistant_status import AssistantStatus
from tests.fakes import ConversationHarness, FailingBridge, FakeBridge

PROCESSING_ERROR = "Lo siento, he tenido un problema al procesar la petición. Puede repetirla."
READY = "Sistemas listos."
STANDBY = "Sistema detenido hasta nueva orden."


def run_conversation(harness: ConversationHarness) -> list[str]:
    """Run one wake-word cycle and return what Jarvis said, without the start-up phrase."""
    harness.run()
    spoken = harness.synthesizer.spoken
    assert spoken[0] == READY
    return spoken[1:]


class OrchestratorStartupTest(unittest.TestCase):
    def test_startup_says_ready_and_prepares_gemini_before_waiting_for_the_wake_word(self) -> None:
        harness = ConversationHarness(wake_error=StopIteration())

        with self.assertRaises(StopIteration):
            harness.orchestrator.run_forever()

        self.assertEqual(harness.created_models, [AssistantModel.GEMINI])
        self.assertEqual(harness.synthesizer.spoken, [READY])
        self.assertEqual(harness.status.statuses[-2:], [AssistantStatus.SPEAKING, AssistantStatus.WAITING])

    def test_a_gemini_that_cannot_be_prepared_is_announced_and_jarvis_keeps_running(self) -> None:
        def factory(model: AssistantModel):
            raise RuntimeError("no gemini.env")

        harness = ConversationHarness(["buenas noches"], factory=factory)

        with self.assertLogs("jarvis.application.conversation.assistant_selector", "ERROR"):
            spoken = run_conversation(harness)

        self.assertEqual(spoken, ["No puedo preparar Gemini.", "Dime", STANDBY])

    def test_an_error_in_a_conversation_is_logged_and_the_loop_continues(self) -> None:
        harness = ConversationHarness([], wakes_allowed=2)

        with self.assertLogs("jarvis.application.conversation.orchestrator", "ERROR"):
            harness.run()

        self.assertEqual(harness.synthesizer.spoken, [READY, "Dime", "Dime"])
        self.assertEqual(harness.microphone.clears, 2)


class OrchestratorFlowsTest(unittest.TestCase):
    def test_confirmed_shutdown_asks_confirms_and_powers_off(self) -> None:
        harness = ConversationHarness(["apágate", "sí"])

        spoken = run_conversation(harness)

        self.assertEqual(
            spoken,
            [
                "Dime",
                "¿Está seguro de que quiere apagarme señor?",
                "Venga a tomar por culo. Tirando del cable... Chao!.",
            ],
        )
        self.assertEqual(harness.power.calls, ["shutdown"])

    def test_cancelled_shutdown_keeps_the_conversation_open(self) -> None:
        harness = ConversationHarness(["apágate", "no", "buenas noches"])

        spoken = run_conversation(harness)

        self.assertEqual(
            spoken,
            [
                "Dime",
                "¿Está seguro de que quiere apagarme señor?",
                "Apagado cancelado, señor.",
                STANDBY,
            ],
        )
        self.assertEqual(harness.power.calls, [])

    def test_confirmed_reboot_asks_confirms_and_reboots(self) -> None:
        harness = ConversationHarness(["reinicia", "dale"])

        spoken = run_conversation(harness)

        self.assertEqual(
            spoken,
            [
                "Dime",
                "¿Está seguro de que quiere reiniciarme señor?",
                "Okey reiniciando el sistema, ahora te hablo!.",
            ],
        )
        self.assertEqual(harness.power.calls, ["reboot"])

    def test_cancelled_reboot_keeps_the_conversation_open(self) -> None:
        harness = ConversationHarness(["reiniciar el sistema", "mejor no", "descansa"])

        spoken = run_conversation(harness)

        self.assertEqual(
            spoken,
            [
                "Dime",
                "¿Está seguro de que quiere reiniciarme señor?",
                "Reinicio cancelado, señor.",
                STANDBY,
            ],
        )
        self.assertEqual(harness.power.calls, [])

    def test_good_night_ends_the_conversation(self) -> None:
        harness = ConversationHarness(["buenas noches"])

        self.assertEqual(run_conversation(harness), ["Dime", STANDBY])
        self.assertEqual(harness.power.calls, [])

    def test_a_bridge_error_speaks_the_error_phrase_and_the_conversation_continues(self) -> None:
        harness = ConversationHarness(["hola", "buenas noches"], bridge=FailingBridge())

        with self.assertLogs("jarvis.application.conversation.turn_handler", "ERROR"):
            spoken = run_conversation(harness)

        self.assertEqual(spoken, ["Dime", PROCESSING_ERROR, STANDBY])

    def test_standby_returns_to_waiting_for_the_wake_word(self) -> None:
        harness = ConversationHarness(["buenas noches"])

        run_conversation(harness)

        self.assertEqual(harness.status.statuses[-1], AssistantStatus.WAITING)


class OrchestratorModelSwitchTest(unittest.TestCase):
    def test_switching_models_in_both_directions(self) -> None:
        bridges = {AssistantModel.GEMINI: FakeBridge("de gemini"), AssistantModel.VENTO: FakeBridge("de vento")}
        harness = ConversationHarness(
            ["cambiar de modelo", "cambiar de modelo", "buenas noches"],
            factory=lambda model: bridges[model],
        )

        spoken = run_conversation(harness)

        self.assertEqual(
            harness.created_models,
            [AssistantModel.GEMINI, AssistantModel.VENTO, AssistantModel.GEMINI],
        )
        self.assertEqual(
            spoken, ["Dime", "Cambiando a Vento.", "Cambiando a Gemini.", STANDBY]
        )
        self.assertEqual(harness.microphone.clears, 2)

    def test_a_failed_switch_keeps_the_current_model_without_clearing_the_microphone(self) -> None:
        def factory(model: AssistantModel):
            if model is AssistantModel.VENTO:
                raise RuntimeError("no bridge.env")
            return FakeBridge()

        harness = ConversationHarness(["cambiar de modelo", "hola", "buenas noches"], factory=factory)

        with self.assertLogs("jarvis.application.conversation.assistant_selector", "ERROR"):
            spoken = run_conversation(harness)

        self.assertEqual(
            spoken, ["Dime", "No puedo preparar Vento.", "respuesta", STANDBY]
        )
        self.assertEqual(harness.microphone.clears, 1)

    def test_transcript_lines_follow_the_dialogue_and_the_active_model(self) -> None:
        bridges = {
            AssistantModel.GEMINI: FakeBridge("respuesta de gemini"),
            AssistantModel.VENTO: FakeBridge("respuesta de vento"),
        }
        harness = ConversationHarness(
            ["Hola", "cambiar de modelo", "Prueba con Vento", "buenas noches"],
            factory=lambda model: bridges[model],
        )

        with self.assertLogs("jarvis.transcript", level="INFO") as logs:
            harness.run()

        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Yo: Hola",
                "Gemini: respuesta de gemini",
                "Yo: cambiar de modelo",
                "Yo: Prueba con Vento",
                "Vento: respuesta de vento",
                "Yo: buenas noches",
            ],
        )

    def test_short_term_history_is_shared_across_a_switch(self) -> None:
        bridge = FakeBridge()
        harness = ConversationHarness(
            ["uno", "cambiar de modelo", "dos", "buenas noches"], bridge=bridge
        )

        run_conversation(harness)

        self.assertEqual([len(context.messages) for context in bridge.contexts], [0, 2])


class OrchestratorHistoryTest(unittest.TestCase):
    def test_vento_history_is_limited_to_six_messages(self) -> None:
        bridge = FakeBridge()
        harness = ConversationHarness(
            ["cambiar de modelo", "uno", "dos", "tres", "cuatro", "cinco", "buenas noches"],
            bridge=bridge,
        )

        run_conversation(harness)

        self.assertEqual([len(context.messages) for context in bridge.contexts], [0, 2, 4, 6, 6])

    def test_history_keeps_the_latest_exchanges(self) -> None:
        bridge = FakeBridge("ok")
        harness = ConversationHarness(
            ["cambiar de modelo", "uno", "dos", "tres", "cuatro", "buenas noches"], bridge=bridge
        )

        run_conversation(harness)

        last = bridge.contexts[-1].messages
        self.assertEqual(
            [(message.role.value, message.text) for message in last],
            [
                ("user", "uno"),
                ("assistant", "ok"),
                ("user", "dos"),
                ("assistant", "ok"),
                ("user", "tres"),
                ("assistant", "ok"),
            ],
        )

    def test_each_wake_word_starts_with_an_empty_history(self) -> None:
        bridge = FakeBridge()
        harness = ConversationHarness(
            ["uno", "buenas noches", "dos", "buenas noches"], bridge=bridge, wakes_allowed=2
        )

        harness.run()

        self.assertEqual([len(context.messages) for context in bridge.contexts], [0, 0])


if __name__ == "__main__":
    unittest.main()
