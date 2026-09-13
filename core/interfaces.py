"""
Interfaces (contratos) del sistema.

Igual que en .NET defines una interfaz para poder inyectar distintas
implementaciones, aquí usamos clases abstractas (ABC) de Python con el
mismo objetivo: el resto del código depende de estos contratos, nunca
de una librería concreta (Vosk, Azure, Vento...).

Para cambiar de proveedor de voz, de reconocimiento o de backend de
IA, basta con crear una nueva clase que implemente la interfaz
correspondiente y pasarla en main.py. El resto del proyecto (sobre
todo core/conversation.py) no cambia ni una línea.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from enum import Enum


class SpeechRecognizer(ABC):
    """Convierte voz capturada por el micrófono en texto."""

    @abstractmethod
    def wait_for_wake_word(self) -> None:
        """Bloquea hasta detectar la palabra de activación."""
        raise NotImplementedError

    @abstractmethod
    def listen_for_sentence(self) -> str:
        """Bloquea hasta escuchar una frase completa y la devuelve."""
        raise NotImplementedError


class SpeechSynthesizer(ABC):
    """Convierte texto en voz y lo reproduce por los altavoces."""

    @abstractmethod
    def speak(self, text: str) -> None:
        """Sintetiza `text` y lo reproduce. Bloquea hasta terminar."""
        raise NotImplementedError


class AssistantBridge(ABC):
    """Envía mensajes de texto al asistente de IA y recibe su respuesta."""

    @abstractmethod
    def ask(self, message: str, history: list[dict]) -> str:
        """Envía `message` junto al `history` y devuelve la respuesta."""
        raise NotImplementedError


class SystemController(ABC):
    """Acciones privilegiadas sobre el sistema operativo."""

    @abstractmethod
    def shutdown(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def reboot(self) -> None:
        raise NotImplementedError

class AssistantStatus(Enum):
    WAITING = "waiting"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"

class StatusIndicator(ABC):
    """Representa físicamente el estado del asistente."""

    @abstractmethod
    def set_status(self, status: AssistantStatus) -> None:
        raise NotImplementedError