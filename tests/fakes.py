"""Fakes and a ready-made object graph shared by the conversation tests."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable

from jarvis.application.conversation.assistant_selector import AssistantSelector
from jarvis.application.conversation.listener import SentenceListener
from jarvis.application.conversation.orchestrator import ConversationOrchestrator
from jarvis.application.conversation.power_commands import PowerCommandHandler
from jarvis.application.conversation.reply_interrupt import ReplyInterruptGate
from jarvis.application.conversation.turn_handler import TurnHandler
from jarvis.application.conversation.voice import Voice
from jarvis.application.memory.conversation_memory import ConversationMemory
from jarvis.domain.assistant_model import AssistantModel
from jarvis.domain.assistant_status import AssistantStatus
from jarvis.domain.conversation import ConversationContext
from jarvis.ports.assistant import AssistantBridge
from jarvis.ports.audio import AudioInput
from jarvis.ports.hardware import StatusIndicator
from jarvis.ports.speech import SpeechRecognizer, SpeechSynthesizer
from jarvis.ports.system import PowerController


class FakeMicrophone(AudioInput):
    def __init__(self) -> None:
        self.clears = 0
        self.stops = 0

    def start_capture(self) -> None:
        pass

    def stop_capture(self) -> None:
        self.stops += 1

    def clear(self) -> None:
        self.clears += 1

    def read_chunk(self, timeout: float | None = None) -> bytes:
        return b""


class ConversationFinished(BaseException):
    """Raised by the fake recognizer to leave ``run_forever`` (a BaseException is not caught)."""


class FakeRecognizer(SpeechRecognizer):
    """Hears the wake word ``wakes_allowed`` times, then ends the test run."""

    def __init__(
        self,
        sentences: Iterable[str] = (),
        wake_error: BaseException | None = None,
        wakes_allowed: int = 1,
    ) -> None:
        self.sentences = iter(sentences)
        self.wake_error = wake_error
        self.wakes_left = wakes_allowed

    def wait_for_wake_word(self) -> None:
        if self.wake_error is not None:
            raise self.wake_error
        if self.wakes_left <= 0:
            raise ConversationFinished()
        self.wakes_left -= 1

    def listen_for_sentence(self) -> str:
        return next(self.sentences)


class FakeSynthesizer(SpeechSynthesizer):
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.interruptions = 0

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def interrupt(self) -> None:
        self.interruptions += 1


class InterruptibleSynthesizer(FakeSynthesizer):
    """Blocks while speaking ``blocking_text`` until ``interrupt`` is called."""

    def __init__(self, blocking_text: str = "respuesta") -> None:
        super().__init__()
        self.blocking_text = blocking_text
        self.reply_started = threading.Event()
        self.interrupted = threading.Event()

    def speak(self, text: str) -> None:
        super().speak(text)
        if text == self.blocking_text:
            self.reply_started.set()
            self.interrupted.wait(timeout=5)

    def interrupt(self) -> None:
        super().interrupt()
        self.interrupted.set()


class FakeBridge(AssistantBridge):
    def __init__(self, response: str = "respuesta") -> None:
        self.response = response
        self.questions: list[str] = []
        self.contexts: list[ConversationContext] = []

    def ask(self, message: str, context: ConversationContext) -> str:
        self.questions.append(message)
        self.contexts.append(context)
        return self.response


class FailingBridge(AssistantBridge):
    def ask(self, message: str, context: ConversationContext) -> str:
        raise RuntimeError("bridge down")


class BlockingBridge(AssistantBridge):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def ask(self, message: str, context: ConversationContext) -> str:
        self.started.set()
        self.release.wait(timeout=5)
        return "respuesta tardía"


class RecordingKnowledge:
    """Stands in for KnowledgeGraphMemory in the turn tests: records what it observes and is asked."""

    def __init__(self, facts: str | None = None) -> None:
        self.observed: list[tuple[str, str]] = []
        self.queries: list[str] = []
        self.facts = facts

    def context_for(self, query: str) -> str | None:
        self.queries.append(query)
        return self.facts

    def observe_exchange(self, user_text: str, assistant_text: str) -> None:
        self.observed.append((user_text, assistant_text))


class RecordingStatusIndicator(StatusIndicator):
    def __init__(self) -> None:
        self.statuses: list[AssistantStatus] = []

    def set_status(self, status: AssistantStatus) -> None:
        self.statuses.append(status)


class RecordingPowerController(PowerController):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.shutdown_called = threading.Event()

    def shutdown(self) -> None:
        self.calls.append("shutdown")
        self.shutdown_called.set()

    def reboot(self) -> None:
        self.calls.append("reboot")


class ConversationHarness:
    """The whole conversation graph wired to fakes, built like the composition root will."""

    def __init__(
        self,
        sentences: Iterable[str] = (),
        bridge: AssistantBridge | None = None,
        factory: Callable[[AssistantModel], AssistantBridge] | None = None,
        memory: ConversationMemory | None = None,
        synthesizer: FakeSynthesizer | None = None,
        history_size: int = 6,
        wake_error: BaseException | None = None,
        wakes_allowed: int = 1,
        knowledge=None,
    ) -> None:
        self.shutting_down = threading.Event()
        self.microphone = FakeMicrophone()
        self.status = RecordingStatusIndicator()
        self.synthesizer = synthesizer or FakeSynthesizer()
        self.power = RecordingPowerController()
        self.recognizer = FakeRecognizer(sentences, wake_error, wakes_allowed)
        self.bridge = bridge or FakeBridge()
        self.created_models: list[AssistantModel] = []
        self._factory = factory or (lambda model: self.bridge)
        self.voice = Voice(self.synthesizer, self.microphone, self.status, self.shutting_down)
        self.listener = SentenceListener(self.recognizer, self.status)
        self.gate = ReplyInterruptGate(self.voice, self.shutting_down)
        self.selector = AssistantSelector(self._create_bridge, self.voice)
        self.turns = TurnHandler(
            self.selector,
            memory,
            self.voice,
            self.gate,
            self.microphone,
            self.status,
            self.shutting_down,
            knowledge=knowledge,
        )
        self.power_commands = PowerCommandHandler(self.voice, self.listener, self.power)
        self.orchestrator = ConversationOrchestrator(
            self.voice,
            self.recognizer,
            self.listener,
            self.selector,
            self.turns,
            self.power_commands,
            self.microphone,
            self.status,
            history_size,
        )

    def _create_bridge(self, model: AssistantModel) -> AssistantBridge:
        self.created_models.append(model)
        return self._factory(model)

    def run(self) -> None:
        """Run ``run_forever`` until the fake recognizer has no wake word left to hear."""
        try:
            self.orchestrator.run_forever()
        except ConversationFinished:
            pass

    def select(self, model: AssistantModel) -> None:
        """Make ``model`` the active one, as the orchestrator does at start-up."""
        self.selector.start(model)
        self.created_models.clear()
