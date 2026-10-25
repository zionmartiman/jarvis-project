"""Builds the AI assistants (Gemini and Vento) and the Gemini summarizer of the memory."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from jarvis.config.credentials import load_gemini_credentials, load_vento_credentials
from jarvis.config.settings import Settings
from jarvis.domain.assistant_model import AssistantModel
from jarvis.domain.conversation import ConversationContext
from jarvis.infrastructure.assistants.gemini import GeminiAssistant
from jarvis.infrastructure.assistants.vento import VentoAssistant
from jarvis.ports.assistant import AssistantBridge

_SUMMARY_HISTORY_MESSAGES = 1


def build_assistant(model: AssistantModel, settings: Settings) -> AssistantBridge:
    """Create the assistant for ``model``, reading its private credentials just now."""
    if model is AssistantModel.GEMINI:
        return _build_gemini(
            settings,
            history_limit=settings.memory.gemini_history_messages,
            system_prompt=_read_system_prompt(settings.gemini.system_prompt_path),
        )
    if model is AssistantModel.VENTO:
        return VentoAssistant(
            load_vento_credentials(settings.vento.credentials_path),
            settings.conversation.short_term_history_messages,
            settings.vento.timeout_seconds,
        )
    raise ValueError(f"Unsupported assistant model: {model}")


def build_memory_summarizer(settings: Settings) -> Callable[[str], str]:
    """Return the function that asks Gemini, without the system prompt, to update the memory."""

    def summarize(prompt: str) -> str:
        summarizer = _build_gemini(settings, history_limit=_SUMMARY_HISTORY_MESSAGES)
        return summarizer.ask(prompt, ConversationContext())

    return summarize


def _build_gemini(
    settings: Settings,
    history_limit: int,
    system_prompt: str = "",
) -> GeminiAssistant:
    """Every Gemini client uses the same configured model and timeout."""
    credentials = load_gemini_credentials(
        settings.gemini.credentials_path, settings.gemini.default_model
    )
    return GeminiAssistant(
        credentials, history_limit, settings.gemini.timeout_seconds, system_prompt
    )


def _read_system_prompt(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()
