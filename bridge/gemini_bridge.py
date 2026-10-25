"""Gemini bridge for the legacy conversation code.

Wraps jarvis.infrastructure.assistants.gemini.GeminiAssistant and keeps the legacy
``history: list[dict]`` signature until phase 5.
"""

from __future__ import annotations

from pathlib import Path

from bridge.legacy_context import history_to_context
from config import settings
from config.settings import GeminiCredentials
from core.interfaces import AssistantBridge
from jarvis.infrastructure.assistants.gemini import GeminiAssistant


class GeminiBridge(AssistantBridge):
    """Sends text to Google Gemini without a Python SDK dependency."""

    def __init__(self, credentials: GeminiCredentials, history_limit: int, timeout_seconds: int = 130,
                 system_prompt_path: str | Path | None = None, include_system_prompt: bool = True):
        system_prompt = self._load_system_prompt(system_prompt_path) if include_system_prompt else ""
        self._assistant = GeminiAssistant(credentials, history_limit, timeout_seconds, system_prompt)

    @staticmethod
    def _load_system_prompt(system_prompt_path: str | Path | None) -> str:
        default_path = Path(__file__).resolve().parent.parent / "system.md"
        prompt_path = Path(system_prompt_path) if system_prompt_path else default_path
        if not prompt_path.exists():
            return ""
        return prompt_path.read_text(encoding="utf-8").strip()

    def build_request_payload(self, message: str, history: list[dict]) -> dict:
        return self._assistant.build_request_payload(message, history_to_context(history))

    def ask(self, message: str, history: list[dict]) -> str:
        return self._assistant.ask(message, history_to_context(history))


def create_configured_gemini_bridge(
    history_limit: int,
    system_prompt_path: str | Path | None = None,
    include_system_prompt: bool = True,
) -> GeminiBridge:
    """Build every Gemini client with the same configured model and timeout."""
    return GeminiBridge(
        credentials=settings.load_gemini_credentials(),
        history_limit=history_limit,
        timeout_seconds=settings.GEMINI_TIMEOUT_SECONDS,
        system_prompt_path=system_prompt_path,
        include_system_prompt=include_system_prompt,
    )
