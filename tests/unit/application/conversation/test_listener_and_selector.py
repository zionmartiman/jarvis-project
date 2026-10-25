import unittest

from jarvis.domain.assistant_model import AssistantModel
from jarvis.domain.assistant_status import AssistantStatus
from tests.fakes import ConversationHarness, FakeBridge

SELECTOR_LOGGER = "jarvis.application.conversation.assistant_selector"


class SentenceListenerTest(unittest.TestCase):
    def test_sets_listening_and_logs_the_transcript_line(self) -> None:
        harness = ConversationHarness(["Hola Jarvis"])

        with self.assertLogs("jarvis.transcript", level="INFO") as logs:
            sentence = harness.listener.listen()

        self.assertEqual(sentence, "Hola Jarvis")
        self.assertEqual([record.getMessage() for record in logs.records], ["Yo: Hola Jarvis"])
        self.assertEqual(harness.status.statuses, [AssistantStatus.LISTENING])


class AssistantSelectorTest(unittest.TestCase):
    def failing_factory(self, failing: set[AssistantModel]):
        def factory(model: AssistantModel) -> FakeBridge:
            if model in failing:
                raise RuntimeError("missing credentials")
            return FakeBridge()

        return factory

    def test_start_builds_the_model_silently(self) -> None:
        harness = ConversationHarness()

        harness.selector.start(AssistantModel.GEMINI)

        self.assertIs(harness.selector.model, AssistantModel.GEMINI)
        self.assertIs(harness.selector.bridge, harness.bridge)
        self.assertEqual(harness.synthesizer.spoken, [])

    def test_start_keeps_the_model_selected_when_it_cannot_be_prepared(self) -> None:
        harness = ConversationHarness(factory=self.failing_factory({AssistantModel.GEMINI}))

        with self.assertLogs(SELECTOR_LOGGER, level="ERROR"):
            harness.selector.start(AssistantModel.GEMINI)

        self.assertIs(harness.selector.model, AssistantModel.GEMINI)
        self.assertIsNone(harness.selector.bridge)
        self.assertEqual(harness.synthesizer.spoken, ["No puedo preparar Gemini."])

    def test_switch_changes_models_in_both_directions(self) -> None:
        for start, expected, phrase in (
            (AssistantModel.GEMINI, AssistantModel.VENTO, "Cambiando a Vento."),
            (AssistantModel.VENTO, AssistantModel.GEMINI, "Cambiando a Gemini."),
        ):
            with self.subTest(start=start):
                harness = ConversationHarness()
                harness.select(start)

                self.assertTrue(harness.selector.switch())

                self.assertEqual(harness.created_models, [expected])
                self.assertIs(harness.selector.model, expected)
                self.assertEqual(harness.synthesizer.spoken, [phrase])

    def test_failed_switch_keeps_the_current_model_and_says_so(self) -> None:
        harness = ConversationHarness(factory=self.failing_factory({AssistantModel.VENTO}))
        harness.select(AssistantModel.GEMINI)
        current = harness.selector.bridge

        with self.assertLogs(SELECTOR_LOGGER, level="ERROR"):
            changed = harness.selector.switch()

        self.assertFalse(changed)
        self.assertIs(harness.selector.model, AssistantModel.GEMINI)
        self.assertIs(harness.selector.bridge, current)
        self.assertEqual(harness.synthesizer.spoken, ["No puedo preparar Vento."])


if __name__ == "__main__":
    unittest.main()
