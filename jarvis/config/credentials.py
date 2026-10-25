"""Private credentials for Azure Speech, Gemini and the Vento bridge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.config.env_file import read_env_file


@dataclass(frozen=True)
class AzureCredentials:
    """Credentials required by Azure Speech."""

    key: str
    region: str


@dataclass(frozen=True)
class GeminiCredentials:
    """Credentials and model name required by Gemini."""

    api_key: str
    model: str


@dataclass(frozen=True)
class VentoCredentials:
    """Credentials required by the Vento bridge."""

    url: str
    token: str


def load_azure_credentials(path: Path) -> AzureCredentials:
    values = read_env_file(path)
    key = values.get("AZURE_SPEECH_KEY")
    region = values.get("AZURE_SPEECH_REGION")

    if not key or not region:
        raise RuntimeError(
            "azure.env debe contener AZURE_SPEECH_KEY y AZURE_SPEECH_REGION"
        )

    return AzureCredentials(key=key, region=region)


def load_gemini_credentials(path: Path, default_model: str) -> GeminiCredentials:
    """Load the private Gemini configuration without printing it."""
    values = read_env_file(path)
    api_key = values.get("GEMINI_API_KEY")
    model = values.get("GEMINI_MODEL", default_model)

    if not api_key:
        raise RuntimeError("gemini.env debe contener GEMINI_API_KEY")

    return GeminiCredentials(api_key=api_key, model=model)


def load_vento_credentials(path: Path) -> VentoCredentials:
    values = read_env_file(path)
    url = values.get("BRIDGE_URL")
    token = values.get("BRIDGE_TOKEN")

    if not url or not token:
        raise RuntimeError(
            "state/bridge.env debe contener BRIDGE_URL y BRIDGE_TOKEN"
        )

    return VentoCredentials(url=url, token=token)
