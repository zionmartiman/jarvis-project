#!/usr/bin/env python3
"""Composition root for Jarvis Voice."""

from pathlib import Path
import threading

from Arduino.arduino_mega_connection import ArduinoMegaConnection
from audio.microphone_stream import MicrophoneStream
from bridge.gemini_bridge import GeminiBridge
from bridge.vento_bridge import VentoBridge
from config import settings
from Indicators.arduino_rgb_indicator import ArduinoRgbIndicator
from notifications.announcement_client import enqueue as enqueue_announcement
from Sensors.rainwater_tank_meter import RainwaterTankLevel, RainwaterTankMeter
from Sensors.rainwater_tank_web_server import RainwaterTankWebServer
from core.conversation import ConversationOrchestrator
from core.interfaces import AssistantBridge
from speech.azure_synthesizer import AzureSpeechSynthesizer
from speech.vosk_recognizer import VoskSpeechRecognizer
from system.power_control import RaspberryPowerController
from system.arduino_button_monitor import ArduinoButtonMonitor

_TANK_STATUS_MESSAGES = {"full": "Depósito lleno.", "nearly_full": "Depósito casi lleno.", "good": "Buenos niveles de agua.", "low": "Niveles de agua bajos.", "very_low": "Niveles de agua muy bajos, se está a punto de quedar sin agua.", "empty": "Depósito vacío."}


def announce_rainwater_tank_level(level: RainwaterTankLevel) -> None:
    enqueue_announcement(f"Deposito al {level.fill_percentage} por ciento.")


def announce_rainwater_tank_status(level: RainwaterTankLevel, status: str) -> None:
    del level
    enqueue_announcement(_TANK_STATUS_MESSAGES[status])


def build_bridge(model: str) -> AssistantBridge:
    """Create only the bridge selected by the spoken startup choice."""
    system_prompt_path = Path(__file__).resolve().parent / "system.md"
    if model == "gemini":
        return GeminiBridge(settings.load_gemini_credentials(), settings.MAX_HISTORY_ITEMS,
                           system_prompt_path=system_prompt_path)
    if model == "vento":
        return VentoBridge(settings.load_bridge_credentials(), settings.MAX_HISTORY_ITEMS)
    raise ValueError(f"Modelo no admitido: {model}")


def build_orchestrator() -> tuple[ConversationOrchestrator, MicrophoneStream, ArduinoRgbIndicator, RainwaterTankMeter, RainwaterTankWebServer, ArduinoButtonMonitor]:
    azure_credentials = settings.load_azure_credentials()
    microphone = MicrophoneStream(sample_rate=settings.SAMPLE_RATE, device=settings.INPUT_DEVICE)
    recognizer = VoskSpeechRecognizer(microphone=microphone, model_path=settings.MODEL_PATH, sample_rate=settings.SAMPLE_RATE)
    synthesizer = AzureSpeechSynthesizer(credentials=azure_credentials, voice_name=settings.AZURE_VOICE, output_device=settings.OUTPUT_DEVICE)
    power_controller = RaspberryPowerController()
    arduino = ArduinoMegaConnection(port=settings.ARDUINO_SERIAL_PORT, baudrate=settings.ARDUINO_BAUDRATE)
    arduino.connect()
    status_indicator = ArduinoRgbIndicator(arduino=arduino, control_socket_path=settings.ARDUINO_CONTROL_SOCKET_PATH)
    shutdown_button_event = threading.Event()
    response_interrupt_event = threading.Event()
    button_monitor = ArduinoButtonMonitor(arduino=arduino, on_shutdown_pressed=shutdown_button_event.set, on_response_interrupt_pressed=response_interrupt_event.set)
    rainwater_tank_meter = RainwaterTankMeter(arduino=arduino, state_path=settings.RAINWATER_TANK_STATE_PATH, on_fill_level_changed=announce_rainwater_tank_level, on_fill_level_status_changed=announce_rainwater_tank_status, poll_interval_seconds=settings.RAINWATER_TANK_POLL_INTERVAL_SECONDS)
    status_indicator.start_control_receiver()
    button_monitor.start()
    rainwater_tank_meter.start_polling()
    rainwater_tank_web_server = RainwaterTankWebServer(latest_level=rainwater_tank_meter.latest_level)
    rainwater_tank_web_server.start()
    orchestrator = ConversationOrchestrator(microphone=microphone, recognizer=recognizer, synthesizer=synthesizer, bridge_factory=build_bridge, power_controller=power_controller, status_indicator=status_indicator, max_history_items=settings.MAX_HISTORY_ITEMS, shutdown_button_event=shutdown_button_event, response_interrupt_event=response_interrupt_event)
    return orchestrator, microphone, status_indicator, rainwater_tank_meter, rainwater_tank_web_server, button_monitor


def main() -> None:
    orchestrator, microphone, status_indicator, rainwater_tank_meter, rainwater_tank_web_server, button_monitor = build_orchestrator()
    print("Jarvis por voz está listo. Di «Jarvis».", flush=True)
    try:
        with microphone:
            orchestrator.run_forever()
    finally:
        rainwater_tank_web_server.close()
        rainwater_tank_meter.close()
        button_monitor.close()
        status_indicator.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nJarvis detenido.", flush=True)
