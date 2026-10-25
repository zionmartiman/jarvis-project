"""The AI assistants Jarvis can talk to."""

from __future__ import annotations

from enum import Enum


class AssistantModel(Enum):
    GEMINI = "gemini"
    VENTO = "vento"

    @property
    def display_name(self) -> str:
        return "Gemini" if self is AssistantModel.GEMINI else "Vento"

    @property
    def uses_long_term_memory(self) -> bool:
        """Only Gemini receives the durable memory; Vento gets the short-term history."""
        return self is AssistantModel.GEMINI

    @property
    def other(self) -> AssistantModel:
        """The model that "cambiar de modelo" switches to."""
        return AssistantModel.VENTO if self is AssistantModel.GEMINI else AssistantModel.GEMINI
