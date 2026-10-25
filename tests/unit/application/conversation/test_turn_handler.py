import tempfile
import threading
import unittest
from pathlib import Path

from jarvis.application.memory.conversation_memory import ConversationMemory
from jarvis.domain.assistant_model import AssistantModel
from jarvis.domain.assistant_status import AssistantStatus
from jarvis.domain.conversation import ChatMessage, Role, ShortTermHistory
from jarvis.infrastructure.memory.jsonl_backend import JsonlMemoryBackend
from tests.fakes import (
    BlockingBridge,
    ConversationHarness,
    FailingBridge,
    FakeBridge,
    InterruptibleSynthesizer,
    RecordingKnowledge,
)

PROCESSING_ERROR = "Lo siento, he tenido un problema al procesar la petición. Puede repetirla."
TURN_LOGGER = "jarvis.application.conversation.turn_handler"


class TurnHandlerTest(unittest.TestCase):
    def test_a_reply_is_logged_remembered_and_spoken(self) -> None:
        harness = ConversationHarness()
        harness.select(AssistantModel.GEMINI)
        history = ShortTermHistory(6)

        with self.assertLogs("jarvis.transcript", level="INFO") as logs:
            harness.turns.handle("Hola", history)

        self.assertEqual([record.getMessage() for record in logs.records], ["Gemini: respuesta"])
        self.assertEqual(harness.synthesizer.spoken, ["respuesta"])
        self.assertEqual(
            history.as_context().messages,
            (ChatMessage(Role.USER, "Hola"), ChatMessage(Role.ASSISTANT, "respuesta")),
        )
        self.assertEqual(
            harness.status.statuses, [AssistantStatus.PROCESSING, AssistantStatus.SPEAKING]
        )
        self.assertEqual(harness.microphone.clears, 1)

    def test_the_transcript_names_the_active_model(self) -> None:
        harness = ConversationHarness()
        harness.select(AssistantModel.VENTO)

        with self.assertLogs("jarvis.transcript", level="INFO") as logs:
            harness.turns.handle("Hola", ShortTermHistory(6))

        self.assertEqual([record.getMessage() for record in logs.records], ["Vento: respuesta"])

    def test_a_bridge_error_speaks_the_error_phrase(self) -> None:
        harness = ConversationHarness(bridge=FailingBridge())
        harness.select(AssistantModel.GEMINI)

        with self.assertLogs(TURN_LOGGER, level="ERROR"):
            harness.turns.handle("Hola", ShortTermHistory(6))

        self.assertEqual(harness.synthesizer.spoken, [PROCESSING_ERROR])
        self.assertEqual(harness.microphone.clears, 1)

    def test_a_missing_bridge_speaks_the_error_phrase(self) -> None:
        harness = ConversationHarness()

        with self.assertLogs(TURN_LOGGER, level="ERROR"):
            harness.turns.handle("Hola", ShortTermHistory(6))

        self.assertEqual(harness.synthesizer.spoken, [PROCESSING_ERROR])

    def test_vento_receives_the_short_term_history_and_never_the_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            memory = ConversationMemory(JsonlMemoryBackend(Path(directory) / "c.jsonl"))
            memory.record_exchange("¿Cómo me llamo?", "No lo sé.")
            harness = ConversationHarness(memory=memory)
            harness.select(AssistantModel.VENTO)
            history = ShortTermHistory(6)
            history.add_exchange("antes", "respuesta antes")

            harness.turns.handle("Ahora", history)

            context = harness.bridge.contexts[0]
            self.assertEqual([message.text for message in context.messages], ["antes", "respuesta antes"])
            self.assertIsNone(context.summary)

    def test_gemini_receives_the_persisted_context_and_the_exchange_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            memory = ConversationMemory(JsonlMemoryBackend(Path(directory) / "c.jsonl"))
            memory.record_exchange("¿Cómo me llamo?", "Aún no me lo has dicho.")
            harness = ConversationHarness(memory=memory)
            harness.select(AssistantModel.GEMINI)

            harness.turns.handle("Me llamo Ana", ShortTermHistory(6))

            received = harness.bridge.contexts[0].messages
            self.assertEqual(received[0].text, "¿Cómo me llamo?")
            self.assertEqual(received[-1], ChatMessage(Role.ASSISTANT, "Aún no me lo has dicho."))
            saved = memory.get_context().messages
            self.assertEqual(saved[-2], ChatMessage(Role.USER, "Me llamo Ana"))
            self.assertEqual(saved[-1], ChatMessage(Role.ASSISTANT, "respuesta"))

    def test_the_graph_memory_observes_each_answered_exchange_of_both_models(self) -> None:
        for model in (AssistantModel.GEMINI, AssistantModel.VENTO):
            with self.subTest(model=model):
                knowledge = RecordingKnowledge()
                harness = ConversationHarness(knowledge=knowledge)
                harness.select(model)

                harness.turns.handle("Mi hermana se llama Ana", ShortTermHistory(6))

                self.assertEqual(knowledge.observed, [("Mi hermana se llama Ana", "respuesta")])

    def test_a_failed_turn_is_not_observed(self) -> None:
        knowledge = RecordingKnowledge()
        harness = ConversationHarness(bridge=FailingBridge(), knowledge=knowledge)
        harness.select(AssistantModel.GEMINI)

        with self.assertLogs(TURN_LOGGER, level="ERROR"):
            harness.turns.handle("Hola", ShortTermHistory(6))

        self.assertEqual(knowledge.observed, [])

    def test_an_interrupted_turn_is_not_observed(self) -> None:
        bridge = BlockingBridge()
        knowledge = RecordingKnowledge()
        harness = ConversationHarness(bridge=bridge, knowledge=knowledge)
        harness.select(AssistantModel.GEMINI)
        turn = threading.Thread(
            target=harness.turns.handle, args=("Hola", ShortTermHistory(6)), daemon=True
        )
        turn.start()
        self.assertTrue(bridge.started.wait(timeout=1))
        harness.gate.request()
        turn.join(timeout=1)

        bridge.release.set()

        self.assertEqual(knowledge.observed, [])

    def test_interrupt_while_waiting_abandons_the_request_and_says_si(self) -> None:
        for model in (AssistantModel.GEMINI, AssistantModel.VENTO):
            with self.subTest(model=model):
                bridge = BlockingBridge()
                harness = ConversationHarness(bridge=bridge)
                harness.select(model)
                turn = threading.Thread(
                    target=harness.turns.handle, args=("Hola", ShortTermHistory(6)), daemon=True
                )
                turn.start()

                try:
                    self.assertTrue(bridge.started.wait(timeout=1))
                    harness.gate.request()
                    turn.join(timeout=1)

                    self.assertFalse(turn.is_alive())
                    self.assertEqual(harness.synthesizer.spoken, ["¿Sí?"])
                    self.assertEqual(harness.synthesizer.interruptions, 0)
                    self.assertEqual(harness.microphone.clears, 1)
                finally:
                    bridge.release.set()
                    turn.join(timeout=1)

    def test_late_reply_after_an_interruption_is_not_spoken_or_remembered(self) -> None:
        bridge = BlockingBridge()
        harness = ConversationHarness(bridge=bridge)
        harness.select(AssistantModel.GEMINI)
        history = ShortTermHistory(6)
        turn = threading.Thread(target=harness.turns.handle, args=("Hola", history), daemon=True)
        turn.start()
        self.assertTrue(bridge.started.wait(timeout=1))
        harness.gate.request()
        turn.join(timeout=1)

        bridge.release.set()

        self.assertEqual(history.as_context().messages, ())
        self.assertEqual(harness.synthesizer.spoken, ["¿Sí?"])

    def test_interrupt_while_speaking_cuts_the_voice_and_says_si(self) -> None:
        synthesizer = InterruptibleSynthesizer()
        harness = ConversationHarness(synthesizer=synthesizer)
        harness.select(AssistantModel.GEMINI)
        turn = threading.Thread(
            target=harness.turns.handle, args=("Hola", ShortTermHistory(6)), daemon=True
        )
        turn.start()

        try:
            self.assertTrue(synthesizer.reply_started.wait(timeout=1))
            harness.gate.request()
            turn.join(timeout=1)

            self.assertFalse(turn.is_alive())
            self.assertEqual(synthesizer.spoken, ["respuesta", "¿Sí?"])
            self.assertEqual(synthesizer.interruptions, 1)
        finally:
            harness.shutting_down.set()
            synthesizer.interrupted.set()
            turn.join(timeout=1)

    def test_a_button_press_outside_a_reply_does_nothing(self) -> None:
        harness = ConversationHarness()
        harness.select(AssistantModel.GEMINI)

        harness.gate.request()
        harness.turns.handle("Hola", ShortTermHistory(6))

        self.assertEqual(harness.synthesizer.spoken, ["respuesta"])

    def test_shutdown_during_the_wait_ends_the_turn_silently(self) -> None:
        bridge = BlockingBridge()
        harness = ConversationHarness(bridge=bridge)
        harness.select(AssistantModel.GEMINI)
        turn = threading.Thread(
            target=harness.turns.handle, args=("Hola", ShortTermHistory(6)), daemon=True
        )
        turn.start()

        try:
            self.assertTrue(bridge.started.wait(timeout=1))
            harness.shutting_down.set()
            turn.join(timeout=1)

            self.assertFalse(turn.is_alive())
            self.assertEqual(harness.synthesizer.spoken, [])
        finally:
            bridge.release.set()
            turn.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
