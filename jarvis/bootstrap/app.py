"""Composition root: builds every concrete object of Jarvis and runs the application."""

from __future__ import annotations

import logging
import threading
from contextlib import AbstractContextManager
from typing import Protocol

from jarvis.application.button_monitor import ButtonMonitor
from jarvis.application.conversation.assistant_selector import AssistantSelector
from jarvis.application.conversation.emergency_shutdown import EmergencyShutdown
from jarvis.application.conversation.listener import SentenceListener
from jarvis.application.conversation.orchestrator import ConversationOrchestrator
from jarvis.application.conversation.power_commands import PowerCommandHandler
from jarvis.application.conversation.reply_interrupt import ReplyInterruptGate
from jarvis.application.conversation.safe_status import SafeStatusIndicator
from jarvis.application.conversation.turn_handler import TurnHandler
from jarvis.application.conversation.voice import Voice
from jarvis.application.knowledge.graph_memory import KnowledgeGraphMemory
from jarvis.application.memory.conversation_memory import ConversationMemory
from jarvis.application.tank_monitor import TankMonitor
from jarvis.bootstrap.assistants import (
    build_assistant,
    build_graph_extractor,
    build_memory_summarizer,
)
from jarvis.bootstrap.logging_setup import configure_logging
from jarvis.config.credentials import load_azure_credentials
from jarvis.config.settings import Settings, load_settings
from jarvis.domain.tank import TankAlertPolicy, TankCalibration
from jarvis.domain.tank_phrases import STATUS_PHRASES, level_phrase
from jarvis.infrastructure.arduino.alert_light import ArduinoAlertLight
from jarvis.infrastructure.arduino.button_panel import ArduinoButtonPanel
from jarvis.infrastructure.arduino.distance_sensor import ArduinoDistanceSensor
from jarvis.infrastructure.arduino.status_light import ArduinoStatusLight
from jarvis.infrastructure.ipc.alert_light_server import AlertLightControlServer
from jarvis.infrastructure.ipc.announcer import SocketAnnouncer
from jarvis.infrastructure.knowledge.sqlite_store import SqliteKnowledgeGraph
from jarvis.infrastructure.memory.jsonl_backend import JsonlMemoryBackend
from jarvis.infrastructure.system.power_controller import SudoPowerController
from jarvis.infrastructure.tank.state_file import JsonTankStateFile
from jarvis.infrastructure.web.web_server import STATIC_DIR, JarvisWebServer
from jarvis.ports.hardware import ButtonPress

LOGGER = logging.getLogger(__name__)


class Component(Protocol):
    """A background part of the application that is started and closed with it."""

    def start(self) -> None: ...

    def close(self) -> None: ...


class Application:
    """Runs the conversation while its background components are alive."""

    def __init__(
        self,
        orchestrator: ConversationOrchestrator,
        microphone: AbstractContextManager,
        components: list[Component],
    ) -> None:
        self._orchestrator = orchestrator
        self._microphone = microphone
        self._components = components

    def run(self) -> None:
        """Start the components in order, converse until stopped and close them in reverse."""
        started: list[Component] = []
        try:
            for component in self._components:
                component.start()
                started.append(component)
            LOGGER.info('Jarvis voice is ready. Say "Jarvis".')
            with self._microphone:
                self._orchestrator.run_forever()
        finally:
            for component in reversed(started):
                component.close()


def build_application(settings: Settings) -> Application:
    """Create every object and wire it; nothing is started until ``Application.run``."""
    # These adapters need libraries that only exist on the Raspberry Pi. They are imported
    # here so that this module (and the tests of Application) load on the development PC.
    from jarvis.infrastructure.arduino.serial_connection import ArduinoSerialConnection
    from jarvis.infrastructure.audio.microphone import SoundDeviceMicrophone
    from jarvis.infrastructure.speech.azure_synthesizer import AzureSpeechSynthesizer
    from jarvis.infrastructure.speech.vosk_recognizer import VoskSpeechRecognizer

    azure_credentials = load_azure_credentials(settings.audio.azure_credentials_path)
    microphone = SoundDeviceMicrophone(
        sample_rate=settings.audio.sample_rate,
        device=settings.audio.input_device,
    )
    recognizer = VoskSpeechRecognizer(
        microphone=microphone,
        model_path=settings.audio.vosk_model_path,
        sample_rate=settings.audio.sample_rate,
    )
    synthesizer = AzureSpeechSynthesizer(
        credentials=azure_credentials,
        voice_name=settings.audio.azure_voice,
        output_device=settings.audio.output_device,
        playback_lock_path=settings.announcements.playback_lock_path,
    )
    power_controller = SudoPowerController()
    arduino = ArduinoSerialConnection(
        port=settings.arduino.serial_port,
        baudrate=settings.arduino.baudrate,
    )
    arduino.connect()

    status = SafeStatusIndicator(ArduinoStatusLight(arduino))
    alert_light_server = AlertLightControlServer(
        ArduinoAlertLight(arduino),
        settings.arduino.alert_light_socket_path,
    )

    shutting_down = threading.Event()
    voice = Voice(synthesizer, microphone, status, shutting_down)
    reply_gate = ReplyInterruptGate(voice, shutting_down)
    emergency_shutdown = EmergencyShutdown(voice, microphone, power_controller, shutting_down)
    button_monitor = ButtonMonitor(
        ArduinoButtonPanel(arduino),
        {
            ButtonPress.SHUTDOWN: emergency_shutdown.trigger,
            ButtonPress.INTERRUPT: reply_gate.request,
        },
        settings.arduino.button_poll_seconds,
    )

    announcer = SocketAnnouncer(settings.announcements.socket_path)
    tank_monitor = TankMonitor(
        ArduinoDistanceSensor(arduino),
        TankCalibration(settings.tank.empty_distance_cm, settings.tank.full_distance_cm),
        JsonTankStateFile(settings.tank.state_path),
        TankAlertPolicy(
            settings.tank.min_change_percentage,
            settings.tank.min_alert_interval_seconds,
            on_level_change=lambda level: announcer.announce(level_phrase(level)),
            on_status_change=lambda level, tank_status: announcer.announce(
                STATUS_PHRASES[tank_status]
            ),
        ),
        settings.tank.poll_interval_seconds,
    )
    knowledge = build_knowledge(settings)
    web_server = JarvisWebServer(
        host=settings.web.host,
        port=settings.web.port,
        static_dir=STATIC_DIR,
        latest_level=tank_monitor.latest_level,
        memory_feed=knowledge,
    )

    memory = ConversationMemory(
        JsonlMemoryBackend(settings.memory.path),
        summarizer=build_memory_summarizer(settings),
        max_size_bytes=settings.memory.max_bytes,
        compact_after_records=settings.memory.compact_after_messages,
        recent_interactions=settings.memory.recent_exchanges,
    )
    listener =SentenceListener(recognizer, status)
    selector = AssistantSelector(lambda model: build_assistant(model, settings), voice)
    orchestrator = ConversationOrchestrator(
        voice=voice,
        recognizer=recognizer,
        listener=listener,
        selector=selector,
        turn_handler=TurnHandler(
            selector,
            memory,
            voice,
            reply_gate,
            microphone,
            status,
            shutting_down,
            knowledge=knowledge,
        ),
        power_commands=PowerCommandHandler(voice, listener, power_controller),
        microphone=microphone,
        status=status,
        history_size=settings.conversation.short_term_history_messages,
    )
    return Application(
        orchestrator,
        microphone,
        [
            alert_light_server,
            button_monitor,
            tank_monitor,
            *([knowledge] if knowledge is not None else []),
            web_server,
        ],
    )


def build_knowledge(settings: Settings) -> KnowledgeGraphMemory | None:
    """The graph memory is optional: if its database cannot be opened, Jarvis runs without it."""
    try:
        store = SqliteKnowledgeGraph(settings.knowledge.path)
    except Exception:
        LOGGER.exception("Knowledge graph unavailable; continuing without it.")
        return None
    return KnowledgeGraphMemory(
        store,
        build_graph_extractor(settings),
        extraction_enabled=settings.knowledge.extraction_enabled,
        retrieval_enabled=settings.knowledge.retrieval_enabled,
    )


def run() -> None:
    """Entry point of ``main.py``."""
    configure_logging()
    try:
        build_application(load_settings()).run()
    except KeyboardInterrupt:
        LOGGER.info("Jarvis stopped.")
