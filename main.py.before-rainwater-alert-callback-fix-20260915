#!/usr/bin/env python3
"""Composition root for Jarvis Voice."""

from Arduino.arduino_mega_connection import ArduinoMegaConnection
from audio.microphone_stream import MicrophoneStream
from bridge.vento_bridge import VentoBridge
from config import settings
from Indicators.arduino_rgb_indicator import ArduinoRgbIndicator
from notifications.announcement_client import enqueue as enqueue_announcement
from Sensors.rainwater_tank_meter import RainwaterTankLevel, RainwaterTankMeter
from core.conversation import ConversationOrchestrator
from speech.azure_synthesizer import AzureSpeechSynthesizer
from speech.vosk_recognizer import VoskSpeechRecognizer
from system.power_control import RaspberryPowerController


def announce_rainwater_tank_level(
    level: RainwaterTankLevel,
    message: str,
) -> None:
    """Queue one semantic alert after a tank-level threshold is crossed."""
    enqueue_announcement(message)


def build_orchestrator() -> tuple[
    ConversationOrchestrator,
    MicrophoneStream,
    ArduinoRgbIndicator,
    RainwaterTankMeter,
]:
    """Load configuration and construct the running application."""
    bridge_credentials = settings.load_bridge_credentials()
    azure_credentials = settings.load_azure_credentials()
    microphone = MicrophoneStream(
        sample_rate=settings.SAMPLE_RATE,
        device=settings.INPUT_DEVICE,
    )
    recognizer = VoskSpeechRecognizer(
        microphone=microphone,
        model_path=settings.MODEL_PATH,
        sample_rate=settings.SAMPLE_RATE,
    )
    synthesizer = AzureSpeechSynthesizer(
        credentials=azure_credentials,
        voice_name=settings.AZURE_VOICE,
        output_device=settings.OUTPUT_DEVICE,
    )
    bridge = VentoBridge(
        credentials=bridge_credentials,
        history_limit=settings.MAX_HISTORY_ITEMS,
    )
    power_controller = RaspberryPowerController()
    arduino = ArduinoMegaConnection(
        port=settings.ARDUINO_SERIAL_PORT,
        baudrate=settings.ARDUINO_BAUDRATE,
    )
    arduino.connect()
    status_indicator = ArduinoRgbIndicator(
        arduino=arduino,
        control_socket_path=settings.ARDUINO_CONTROL_SOCKET_PATH,
    )
    rainwater_tank_meter = RainwaterTankMeter(
        arduino=arduino,
        state_path=settings.RAINWATER_TANK_STATE_PATH,
        on_fill_level_changed=announce_rainwater_tank_level,
    )
    status_indicator.start_control_receiver()
    rainwater_tank_meter.start_polling()
    orchestrator = ConversationOrchestrator(
        microphone=microphone,
        recognizer=recognizer,
        synthesizer=synthesizer,
        bridge=bridge,
        power_controller=power_controller,
        status_indicator=status_indicator,
        max_history_items=settings.MAX_HISTORY_ITEMS,
    )
    return orchestrator, microphone, status_indicator, rainwater_tank_meter


def main() -> None:
    orchestrator, microphone, status_indicator, rainwater_tank_meter = (
        build_orchestrator()
    )
    print("Jarvis por voz está listo. Di «Jarvis».", flush=True)
    try:
        with microphone:
            orchestrator.run_forever()
    finally:
        rainwater_tank_meter.close()
        status_indicator.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nJarvis detenido.", flush=True)
