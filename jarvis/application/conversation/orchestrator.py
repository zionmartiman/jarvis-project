"""The conversation loop: wait for "Jarvis", then listen, dispatch and answer."""

from __future__ import annotations

import logging

from jarvis.application.conversation.assistant_selector import AssistantSelector
from jarvis.application.conversation.listener import SentenceListener
from jarvis.application.conversation.power_commands import PowerCommandHandler, PowerOutcome
from jarvis.application.conversation.turn_handler import TurnHandler
from jarvis.application.conversation.voice import Voice
from jarvis.domain import phrases
from jarvis.domain.assistant_model import AssistantModel
from jarvis.domain.assistant_status import AssistantStatus
from jarvis.domain.conversation import ShortTermHistory
from jarvis.domain.intents import Intent, classify
from jarvis.ports.audio import AudioInput
from jarvis.ports.hardware import StatusIndicator
from jarvis.ports.speech import SpeechRecognizer

LOGGER = logging.getLogger(__name__)


class ConversationOrchestrator:
    """Runs the wake-word / conversation cycle and sends each instruction to its handler."""

    def __init__(
        self,
        voice: Voice,
        recognizer: SpeechRecognizer,
        listener: SentenceListener,
        selector: AssistantSelector,
        turn_handler: TurnHandler,
        power_commands: PowerCommandHandler,
        microphone: AudioInput,
        status: StatusIndicator,
        history_size: int,
    ) -> None:
        self._voice = voice
        self._recognizer = recognizer
        self._listener = listener
        self._selector = selector
        self._turn_handler = turn_handler
        self._power_commands = power_commands
        self._microphone = microphone
        self._status = status
        self._history_size = history_size

    def run_forever(self) -> None:
        self._voice.say(phrases.SYSTEMS_READY)
        self._selector.start(AssistantModel.GEMINI)
        while True:
            self._status.set_status(AssistantStatus.WAITING)
            LOGGER.info('Waiting for the wake word "Jarvis"')
            self._recognizer.wait_for_wake_word()
            try:
                self._run_conversation()
            except Exception:
                LOGGER.exception("Unable to run the conversation.")
                self._microphone.clear()

    def _run_conversation(self) -> None:
        history = ShortTermHistory(self._history_size)
        self._voice.say(phrases.WAKE_ACK)
        while True:
            command = self._listener.listen()
            intent = classify(command)
            if intent in (Intent.SHUTDOWN, Intent.REBOOT):
                outcome = self._power_commands.handle(intent)
                if outcome is PowerOutcome.EXECUTED:
                    return
                continue
            if intent is Intent.SWITCH_MODEL:
                if self._selector.switch():
                    self._microphone.clear()
                continue
            if intent is Intent.END_CONVERSATION:
                self._voice.say(phrases.STANDBY)
                return
            self._turn_handler.handle(command, history)
