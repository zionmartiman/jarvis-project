"""
Reconocimiento de órdenes especiales dentro del texto transcrito.

Son funciones puras (texto adentro, booleano afuera), sin ninguna
dependencia externa. Se pueden probar con un test normal de Python,
sin micrófono, sin Azure y sin Vento.
"""

from __future__ import annotations

import unicodedata

_SHUTDOWN_COMMANDS = {
    "apaga la raspberry",
    "apagar la raspberry",
    "apaga el sistema",
    "apagar el sistema",
    "apagate",
    "apagar",
}

_REBOOT_COMMANDS = {
    "reinicia la raspberry",
    "reiniciar la raspberry",
    "reinicia el sistema",
    "reiniciar el sistema",
    "reiniciate",
    "reinicia",
}

_END_CONVERSATION_COMMANDS = {
    "buenas noches",
    "pausar",
    "pausate",
    "pausar conversacion",
    "espera",
    "esperate",
    "descansa",
}

_CONFIRMATION_COMMANDS = {
    "si",
    "dale",
    "confirmo",
    "confirmar",
    "adelante",
    "claro",
}


def normalize_text(text: str) -> str:
    """
    Quita mayúsculas, tildes y signos para comparar órdenes de cierre.
    """

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


def wants_to_shutdown(text: str) -> bool:
    """Detecta órdenes explícitas de apagar la Raspberry."""
    return normalize_text(text) in _SHUTDOWN_COMMANDS


def wants_to_reboot(text: str) -> bool:
    """Detecta órdenes explícitas de reiniciar la Raspberry."""
    return normalize_text(text) in _REBOOT_COMMANDS


def wants_to_end_conversation(text: str) -> bool:
    """
    Estas frases terminan la conversación activa y devuelven a Jarvis
    al modo de espera. El programa continúa ejecutándose.
    """
    return normalize_text(text) in _END_CONVERSATION_COMMANDS


def is_confirmation(text: str) -> bool:
    """Acepta confirmaciones claras."""
    return normalize_text(text) in _CONFIRMATION_COMMANDS
