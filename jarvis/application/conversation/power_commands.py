"""Shutdown and reboot by voice, each with a spoken confirmation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from jarvis.application.conversation.listener import SentenceListener
from jarvis.application.conversation.voice import Voice
from jarvis.domain import phrases
from jarvis.domain.intents import Intent, is_confirmation
from jarvis.ports.system import PowerController


class PowerOutcome(Enum):
    NOT_HANDLED = "not_handled"
    EXECUTED = "executed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class _PowerCommand:
    question: str
    confirmed_reply: str
    cancelled_reply: str
    action: Callable[[], None]


class PowerCommandHandler:
    """Asks for confirmation and runs the power action when the user agrees."""

    def __init__(
        self,
        voice: Voice,
        listener: SentenceListener,
        power_controller: PowerController,
    ) -> None:
        self._voice = voice
        self._listener = listener
        self._commands = {
            Intent.SHUTDOWN: _PowerCommand(
                phrases.SHUTDOWN_QUESTION,
                phrases.SHUTDOWN_CONFIRMED,
                phrases.SHUTDOWN_CANCELLED,
                power_controller.shutdown,
            ),
            Intent.REBOOT: _PowerCommand(
                phrases.REBOOT_QUESTION,
                phrases.REBOOT_CONFIRMED,
                phrases.REBOOT_CANCELLED,
                power_controller.reboot,
            ),
        }

    def handle(self, intent: Intent) -> PowerOutcome:
        command = self._commands.get(intent)
        if command is None:
            return PowerOutcome.NOT_HANDLED
        self._voice.say(command.question)
        if is_confirmation(self._listener.listen()):
            self._voice.say(command.confirmed_reply)
            command.action()
            return PowerOutcome.EXECUTED
        self._voice.say(command.cancelled_reply)
        return PowerOutcome.CANCELLED
