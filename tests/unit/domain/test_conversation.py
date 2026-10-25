import unittest

from jarvis.domain.assistant_model import AssistantModel
from jarvis.domain.conversation import ChatMessage, ConversationContext, Role, ShortTermHistory


class ShortTermHistoryTest(unittest.TestCase):
    def test_starts_empty(self) -> None:
        self.assertEqual(ShortTermHistory(6).as_context(), ConversationContext())

    def test_keeps_exchanges_in_order(self) -> None:
        history = ShortTermHistory(6)
        history.add_exchange("hola", "buenas")

        self.assertEqual(
            history.as_context().messages,
            (ChatMessage(Role.USER, "hola"), ChatMessage(Role.ASSISTANT, "buenas")),
        )
        self.assertIsNone(history.as_context().summary)

    def test_keeps_only_the_last_messages(self) -> None:
        history = ShortTermHistory(6)
        for number in range(1, 5):
            history.add_exchange(f"q{number}", f"a{number}")

        texts = [message.text for message in history.as_context().messages]
        self.assertEqual(texts, ["q2", "a2", "q3", "a3", "q4", "a4"])

    def test_context_is_a_snapshot(self) -> None:
        history = ShortTermHistory(6)
        history.add_exchange("q1", "a1")
        snapshot = history.as_context()

        history.add_exchange("q2", "a2")

        self.assertEqual(len(snapshot.messages), 2)

    def test_rejects_non_positive_limit(self) -> None:
        with self.assertRaises(ValueError):
            ShortTermHistory(0)

    def test_role_values_match_the_wire_format(self) -> None:
        self.assertEqual(Role.USER, "user")
        self.assertEqual(Role.ASSISTANT, "assistant")


class AssistantModelTest(unittest.TestCase):
    def test_display_names(self) -> None:
        self.assertEqual(AssistantModel.GEMINI.display_name, "Gemini")
        self.assertEqual(AssistantModel.VENTO.display_name, "Vento")

    def test_only_gemini_uses_long_term_memory(self) -> None:
        self.assertTrue(AssistantModel.GEMINI.uses_long_term_memory)
        self.assertFalse(AssistantModel.VENTO.uses_long_term_memory)

    def test_other_alternates_between_the_models(self) -> None:
        self.assertIs(AssistantModel.GEMINI.other, AssistantModel.VENTO)
        self.assertIs(AssistantModel.VENTO.other, AssistantModel.GEMINI)


if __name__ == "__main__":
    unittest.main()
