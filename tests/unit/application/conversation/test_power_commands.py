import unittest

from jarvis.application.conversation.power_commands import PowerOutcome
from jarvis.domain.intents import Intent
from tests.fakes import ConversationHarness


class PowerCommandHandlerTest(unittest.TestCase):
    def test_confirmed_command_runs_its_action(self) -> None:
        for intent, answer, action in (
            (Intent.SHUTDOWN, "sí", "shutdown"),
            (Intent.REBOOT, "claro", "reboot"),
        ):
            with self.subTest(intent=intent):
                harness = ConversationHarness([answer])

                outcome = harness.power_commands.handle(intent)

                self.assertIs(outcome, PowerOutcome.EXECUTED)
                self.assertEqual(harness.power.calls, [action])

    def test_anything_but_a_confirmation_cancels(self) -> None:
        harness = ConversationHarness(["quizá"])

        outcome = harness.power_commands.handle(Intent.SHUTDOWN)

        self.assertIs(outcome, PowerOutcome.CANCELLED)
        self.assertEqual(harness.power.calls, [])
        self.assertEqual(
            harness.synthesizer.spoken,
            ["¿Está seguro de que quiere apagarme señor?", "Apagado cancelado, señor."],
        )

    def test_other_intents_are_not_handled_and_say_nothing(self) -> None:
        harness = ConversationHarness()

        for intent in (Intent.SWITCH_MODEL, Intent.END_CONVERSATION, Intent.QUESTION):
            with self.subTest(intent=intent):
                self.assertIs(harness.power_commands.handle(intent), PowerOutcome.NOT_HANDLED)
        self.assertEqual(harness.synthesizer.spoken, [])


if __name__ == "__main__":
    unittest.main()
