"""Non-secret settings grouped by concern, plus the loader that resolves project paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.domain.memory_source import MemorySource
from jarvis.infrastructure.runtime import runtime_dir

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PRIVATE_CONFIG_DIR = Path.home() / ".config" / "jarvis-voice"


@dataclass(frozen=True)
class AudioSettings:
    """Microphone, speaker, speech recognition model and Azure voice."""

    vosk_model_path: Path
    azure_credentials_path: Path
    sample_rate: int = 16000
    input_device: int = 1
    output_device: str = "plughw:0,0"
    azure_voice: str = "es-ES-AlvaroNeural"


@dataclass(frozen=True)
class ConversationSettings:
    """Limits of the in-process conversation."""

    short_term_history_messages: int = 6


@dataclass(frozen=True)
class MemorySettings:
    """Which durable memory is saved and recalled, plus the conversation log and its compaction."""

    path: Path
    # Master switches. CONVERSATION_LOG = state/conversation.jsonl (recent exchanges + summary),
    # GRAPH = state/knowledge_graph.sqlite3, BOTH, or NONE. They are independent: Jarvis can keep
    # saving to one flow while recalling from the other.
    storage: MemorySource = MemorySource.BOTH  # where each answered exchange is saved
    retrieval: MemorySource = MemorySource.GRAPH  # where Gemini's long-term context is read from
    max_bytes: int = 4096
    compact_after_messages: int = 10
    recent_exchanges: int = 5
    gemini_history_messages: int = 11


@dataclass(frozen=True)
class GeminiSettings:
    credentials_path: Path
    system_prompt_path: Path
    default_model: str = "gemini-2.5-flash"
    timeout_seconds: int = 130


@dataclass(frozen=True)
class VentoSettings:
    credentials_path: Path
    timeout_seconds: int = 130


@dataclass(frozen=True)
class ArduinoSettings:
    """Serial link to the Arduino Mega and its local control socket."""

    alert_light_socket_path: Path
    serial_port: str = "/dev/ttyACM0"
    baudrate: int = 115200
    button_poll_seconds: float = 0.1


@dataclass(frozen=True)
class AnnouncementSettings:
    """Local queue of spoken announcements and the speaker lock they share."""

    socket_path: Path
    playback_lock_path: Path
    max_characters: int = 500
    max_datagram_bytes: int = 2048


@dataclass(frozen=True)
class TankSettings:
    """Rainwater tank calibration and alert thresholds."""

    state_path: Path
    poll_interval_seconds: float = 5.0
    empty_distance_cm: float = 80.0
    full_distance_cm: float = 9.0
    min_change_percentage: int = 5
    min_alert_interval_seconds: float = 5.0


@dataclass(frozen=True)
class KnowledgeGraphSettings:
    """Graph memory: its database and the Gemini extraction (on/off lives in MemorySettings)."""

    path: Path
    extraction_model: str | None = None  # None -> GEMINI_MODEL of gemini.env
    extraction_thinking: dict | None = None  # e.g. {"thinkingBudget": 0} on 2.5 Flash


@dataclass(frozen=True)
class WebSettings:
    host: str = "0.0.0.0"
    port: int = 8765


@dataclass(frozen=True)
class Settings:
    audio: AudioSettings
    conversation: ConversationSettings
    memory: MemorySettings
    gemini: GeminiSettings
    vento: VentoSettings
    arduino: ArduinoSettings
    announcements: AnnouncementSettings
    tank: TankSettings
    web: WebSettings
    knowledge: KnowledgeGraphSettings


def load_settings(base_dir: Path | None = None) -> Settings:
    """Build the settings; project paths are resolved against ``base_dir``."""
    root = base_dir if base_dir is not None else _PROJECT_ROOT
    state_dir = root / "state"
    runtime = runtime_dir()
    return Settings(
        audio=AudioSettings(
            vosk_model_path=root / "models" / "vosk-model-small-es-0.42",
            azure_credentials_path=_PRIVATE_CONFIG_DIR / "azure.env",
        ),
        conversation=ConversationSettings(),
        memory=MemorySettings(path=state_dir / "conversation.jsonl"),
        gemini=GeminiSettings(
            credentials_path=_PRIVATE_CONFIG_DIR / "gemini.env",
            system_prompt_path=root / "prompts" / "system.md",
        ),
        vento=VentoSettings(credentials_path=state_dir / "bridge.env"),
        arduino=ArduinoSettings(
            alert_light_socket_path=runtime / "jarvis-arduino-control.sock",
        ),
        announcements=AnnouncementSettings(
            socket_path=runtime / "jarvis-announcer.sock",
            playback_lock_path=runtime / "jarvis-speech.lock",
        ),
        tank=TankSettings(state_path=state_dir / "rainwater_tank_state.json"),
        web=WebSettings(),
        knowledge=KnowledgeGraphSettings(path=state_dir / "knowledge_graph.sqlite3"),
    )
