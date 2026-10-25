"""Recognition of reserved spoken commands inside transcribed text."""

from __future__ import annotations

import unicodedata
from enum import Enum


class Intent(Enum):
    SHUTDOWN = "shutdown"
    REBOOT = "reboot"
    END_CONVERSATION = "end_conversation"
    SWITCH_MODEL = "switch_model"
    QUESTION = "question"


_COMMANDS: dict[Intent, frozenset[str]] = {
    Intent.SHUTDOWN: frozenset({
        "apaga la raspberry",
        "apagar la raspberry",
        "apaga el sistema",
        "apagar el sistema",
        "apagate",
        "apagar",
    }),
    Intent.REBOOT: frozenset({
        "reinicia la raspberry",
        "reiniciar la raspberry",
        "reinicia el sistema",
        "reiniciar el sistema",
        "reiniciate",
        "reinicia",
    }),
    Intent.END_CONVERSATION: frozenset({
        "buenas noches",
        "pausar",
        "pausate",
        "pausar conversacion",
        "espera",
        "esperate",
        "descansa",
    }),
    Intent.SWITCH_MODEL: frozenset({"cambiar de modelo"}),
}

_CONFIRMATIONS = frozenset({"si", "dale", "confirmo", "confirmar", "adelante", "claro"})


def normalize_text(text: str) -> str:
    """Remove case, accents and punctuation so commands compare reliably."""
    text = text.casefold()

    text = "".join(
        character
        for character in unicodedata.normalize("NFD", text)
        if unicodedata.category(character) != "Mn"
    )

    text = "".join(
        character if character.isalnum() or character.isspace() else " "
        for character in text
    )

    return " ".join(text.split())


def classify(text: str) -> Intent:
    """Return the reserved command in ``text``, or QUESTION for anything else."""
    normalized = normalize_text(text)
    for intent, commands in _COMMANDS.items():
        if normalized in commands:
            return intent
    return Intent.QUESTION


def is_confirmation(text: str) -> bool:
    return normalize_text(text) in _CONFIRMATIONS
