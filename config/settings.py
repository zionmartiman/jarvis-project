"""
Configuración general de Jarvis Voice.
"""

from __future__ import annotations

import os
from pathlib import Path

from jarvis.config.credentials import AzureCredentials, GeminiCredentials
from jarvis.config.credentials import VentoCredentials as BridgeCredentials
from jarvis.config.env_file import read_env_file

BASE_DIR = Path(__file__).resolve().parent.parent


def get_runtime_uid() -> int:
    """Return the current uid on Unix and a safe fallback for other hosts."""
    if hasattr(os, "getuid"):
        return int(os.getuid())
    return 1000


SAMPLE_RATE = 16000
INPUT_DEVICE = 1
OUTPUT_DEVICE = "plughw:0,0"

MODEL_PATH = BASE_DIR / "models" / "vosk-model-small-es-0.42"
AZURE_CONFIG_PATH = Path.home() / ".config" / "jarvis-voice" / "azure.env"
BRIDGE_CONFIG_PATH = BASE_DIR / "state" / "bridge.env"

AZURE_VOICE = "es-ES-AlvaroNeural"

# Conservamos los últimos tres intercambios completos (usuario + Jarvis).
MAX_HISTORY_ITEMS = 6
GEMINI_MEMORY_CONTEXT_ITEMS = 11
CONVERSATION_MEMORY_PATH = BASE_DIR / "state" / "conversation.jsonl"
CONVERSATION_MEMORY_MAX_BYTES = 4096
CONVERSATION_MEMORY_COMPACT_RECORDS = 10
CONVERSATION_MEMORY_RECENT_INTERACTIONS = 5

# Arduino Mega conectado por USB para las luces físicas.
ARDUINO_SERIAL_PORT = "/dev/ttyACM0"
ARDUINO_BAUDRATE = 115200
ARDUINO_CONTROL_SOCKET_PATH = (
    Path("/run/user") / str(get_runtime_uid()) / "jarvis-arduino-control.sock"
)

# Cola local del receptor independiente de avisos hablados.
ANNOUNCEMENT_SOCKET_PATH = (
    Path("/run/user") / str(get_runtime_uid()) / "jarvis-announcer.sock"
)
PLAYBACK_LOCK_PATH = (
    Path("/run/user") / str(get_runtime_uid()) / "jarvis-speech.lock"
)
MAX_ANNOUNCEMENT_CHARACTERS = 500
MAX_ANNOUNCEMENT_DATAGRAM_BYTES = 2048

# Queryable rainwater tank state, updated by RainwaterTankMeter.
RAINWATER_TANK_STATE_PATH = BASE_DIR / "state" / "rainwater_tank_state.json"
RAINWATER_TANK_POLL_INTERVAL_SECONDS = 5.0


def load_azure_credentials() -> AzureCredentials:
    values = read_env_file(AZURE_CONFIG_PATH)
    key = values.get("AZURE_SPEECH_KEY")
    region = values.get("AZURE_SPEECH_REGION")

    if not key or not region:
        raise RuntimeError(
            "azure.env debe contener AZURE_SPEECH_KEY y AZURE_SPEECH_REGION"
        )

    return AzureCredentials(key=key, region=region)


def load_bridge_credentials() -> BridgeCredentials:
    values = read_env_file(BRIDGE_CONFIG_PATH)
    url = values.get("BRIDGE_URL")
    token = values.get("BRIDGE_TOKEN")

    if not url or not token:
        raise RuntimeError(
            "state/bridge.env debe contener BRIDGE_URL y BRIDGE_TOKEN"
        )

    return BridgeCredentials(url=url, token=token)


GEMINI_CONFIG_PATH = Path.home() / ".config" / "jarvis-voice" / "gemini.env"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TIMEOUT_SECONDS = 130


def load_gemini_credentials() -> GeminiCredentials:
    """Carga la configuración privada de Gemini sin imprimirla."""
    values = read_env_file(GEMINI_CONFIG_PATH)
    api_key = values.get("GEMINI_API_KEY")
    model = values.get("GEMINI_MODEL", GEMINI_MODEL)

    if not api_key:
        raise RuntimeError("gemini.env debe contener GEMINI_API_KEY")

    return GeminiCredentials(api_key=api_key, model=model)
