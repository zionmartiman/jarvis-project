"""
Configuración general de Jarvis Voice.

Aquí viven las rutas, constantes y la carga de los archivos de
configuración privados (claves de Azure, credenciales del puente de
Vento). Es el único sitio del proyecto que debería tocarse para
cambiar un dispositivo de audio, una ruta o un límite de historial.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Raíz del proyecto (la carpeta que contiene main.py), calculada de
# forma relativa a este fichero para que funcione igual si systemd
# lo ejecuta desde otro directorio de trabajo.
BASE_DIR = Path(__file__).resolve().parent.parent

SAMPLE_RATE = 16000

# Dispositivo PortAudio del micrófono Plantronics.
# Se puede consultar con:
# python -c "import sounddevice as sd; print(sd.query_devices())"
INPUT_DEVICE = 1

# Salida ALSA de los auriculares Plantronics.
# Cuando cambies de altavoz, solo hay que modificar este valor.
OUTPUT_DEVICE = "plughw:0,0"

MODEL_PATH = BASE_DIR / "models" / "vosk-model-small-es-0.42"

AZURE_CONFIG_PATH = Path.home() / ".config" / "jarvis-voice" / "azure.env"

BRIDGE_CONFIG_PATH = BASE_DIR / "state" / "bridge.env"

AZURE_VOICE = "es-ES-AlvaroNeural"

# Conservamos los últimos tres intercambios completos (usuario +
# Jarvis) en el historial que se envía al puente.
MAX_HISTORY_ITEMS = 6

# Arduino Mega conectado por USB para el indicador RGB de estado.
ARDUINO_SERIAL_PORT = "/dev/ttyACM0"
ARDUINO_BAUDRATE = 115200

# Local queue used by the independent spoken-announcement receiver.
ANNOUNCEMENT_SOCKET_PATH = Path('/run/user') / str(__import__('os').getuid()) / 'jarvis-announcer.sock'
MAX_ANNOUNCEMENT_CHARACTERS = 500
MAX_ANNOUNCEMENT_DATAGRAM_BYTES = 2048


@dataclass(frozen=True)
class AzureCredentials:
    """Credenciales necesarias para usar Azure Speech."""

    key: str
    region: str


@dataclass(frozen=True)
class BridgeCredentials:
    """Credenciales necesarias para hablar con el puente de Vento."""

    url: str
    token: str


def read_env_file(path: Path) -> dict[str, str]:
    """
    Lee un archivo KEY=VALUE.

    No imprime claves ni tokens en pantalla.
    """

    if not path.exists():
        raise RuntimeError(f"No existe la configuración: {path}")

    values: dict[str, str] = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    return values


def load_azure_credentials() -> AzureCredentials:
    """Carga y valida la configuración privada de Azure."""

    values = read_env_file(AZURE_CONFIG_PATH)

    key = values.get("AZURE_SPEECH_KEY")
    region = values.get("AZURE_SPEECH_REGION")

    if not key or not region:
        raise RuntimeError(
            "azure.env debe contener AZURE_SPEECH_KEY y AZURE_SPEECH_REGION"
        )

    return AzureCredentials(key=key, region=region)


def load_bridge_credentials() -> BridgeCredentials:
    """Carga la URL y el token privado del puente de Vento."""

    values = read_env_file(BRIDGE_CONFIG_PATH)

    url = values.get("BRIDGE_URL")
    token = values.get("BRIDGE_TOKEN")

    if not url or not token:
        raise RuntimeError(
            "state/bridge.env debe contener BRIDGE_URL y BRIDGE_TOKEN"
        )

    return BridgeCredentials(url=url, token=token)
