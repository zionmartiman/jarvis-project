"""One question/answer turn with the active assistant."""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from queue import Empty, Queue

from jarvis.application.conversation.assistant_selector import AssistantSelector
from jarvis.application.conversation.reply_interrupt import ReplyInterruptGate
from jarvis.application.conversation.transcript import TRANSCRIPT
from jarvis.application.conversation.voice import Voice
from jarvis.application.knowledge.graph_memory import KnowledgeGraphMemory
from jarvis.application.memory.conversation_memory import ConversationMemory
from jarvis.domain import phrases
from jarvis.domain.assistant_status import AssistantStatus
from jarvis.domain.conversation import ConversationContext, ShortTermHistory
from jarvis.ports.assistant import AssistantBridge
from jarvis.ports.audio import AudioInput
from jarvis.ports.hardware import StatusIndicator

LOGGER = logging.getLogger(__name__)

_REPLY_POLL_SECONDS = 0.05


class TurnHandler:
    """Asks the assistant, records the exchange and speaks the reply, honouring interruptions."""

    def __init__(
        self,
        selector: AssistantSelector,
        memory: ConversationMemory | None,
        voice: Voice,
        gate: ReplyInterruptGate,
        microphone: AudioInput,
        status: StatusIndicator,
        shutting_down: threading.Event,
        knowledge: KnowledgeGraphMemory | None = None,
        read_log: bool = True,
        write_log: bool = True,
    ) -> None:
        self._selector = selector
        self._memory = memory
        self._read_log = read_log
        self._write_log = write_log
        self._voice = voice
        self._gate = gate
        self._microphone = microphone
        self._status = status
        self._shutting_down = shutting_down
        self._knowledge = knowledge

    def handle(self, command: str, history: ShortTermHistory) -> None:
        try:
            self._status.set_status(AssistantStatus.PROCESSING)
            bridge = self._selector.bridge
            model = self._selector.model
            if bridge is None or model is None:
                raise RuntimeError("No AI assistant is selected")
            self._gate.begin()
            try:
                if model.uses_long_term_memory:
                    context = self._long_term_context(command, history)
                else:
                    context = history.as_context()
                reply = self._ask_interruptibly(bridge, command, context)
                if reply is None:
                    if self._gate.is_requested and not self._shutting_down.is_set():
                        self._acknowledge_interrupt()
                    return
                if self._gate.is_requested:
                    self._acknowledge_interrupt()
                    return
                TRANSCRIPT.info("%s: %s", model.display_name, reply)
                history.add_exchange(command, reply)
                if self._memory is not None and self._write_log:
                    self._memory.record_exchange(command, reply)
                if self._knowledge is not None:
                    self._knowledge.observe_exchange(command, reply)
                was_interrupted = self._speak_reply(reply)
                if was_interrupted and not self._shutting_down.is_set():
                    self._gate.end()
                    self._voice.say(phrases.INTERRUPT_ACK)
                self._microphone.clear()
            finally:
                self._gate.end()
        except Exception:
            LOGGER.exception("Unable to process the message.")
            self._voice.say(phrases.PROCESSING_ERROR)
            self._microphone.clear()

    def _long_term_context(self, command: str, history: ShortTermHistory) -> ConversationContext:
        """What Gemini recalls: the conversation log (or just this session) plus the graph facts."""
        if self._memory is not None and self._read_log:
            context = self._memory.get_context()
        else:
            context = history.as_context()
        if self._knowledge is not None:
            context = replace(context, knowledge=self._knowledge.context_for(command))
        return context

    def _acknowledge_interrupt(self) -> None:
        self._gate.end()
        self._voice.say(phrases.INTERRUPT_ACK)
        self._microphone.clear()

    def _speak_reply(self, reply: str) -> bool:
        """Speak ``reply``; return True when the button interrupted it (or the wait before it)."""
        if self._gate.is_requested:
            return True
        with self._gate.speaking():
            if self._gate.is_requested:
                return True
            self._voice.say(reply)
        return self._gate.is_requested

    def _ask_interruptibly(
        self,
        bridge: AssistantBridge,
        command: str,
        context: ConversationContext,
    ) -> str | None:
        """Ask in a worker thread; return None if the button or a shutdown abandons the wait."""
        result_queue: Queue[tuple[str | None, Exception | None]] = Queue(maxsize=1)

        def ask() -> None:
            try:
                result_queue.put((bridge.ask(command, context), None))
            except Exception as error:
                result_queue.put((None, error))

        threading.Thread(target=ask, name="assistant-model-request", daemon=True).start()

        while not self._shutting_down.is_set():
            if self._gate.is_requested:
                return None
            try:
                reply, error = result_queue.get(timeout=_REPLY_POLL_SECONDS)
            except Empty:
                continue
            if self._gate.is_requested or self._shutting_down.is_set():
                return None
            if error is not None:
                raise error
            return reply
        return None
