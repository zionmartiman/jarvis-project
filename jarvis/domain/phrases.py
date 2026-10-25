"""Everything Jarvis says out loud (Spanish). Keep the texts identical to the original."""

from __future__ import annotations

from jarvis.domain.assistant_model import AssistantModel

SYSTEMS_READY = "Sistemas listos."
WAKE_ACK = "Dime"
STANDBY = "Sistema detenido hasta nueva orden."
INTERRUPT_ACK = "¿Sí?"
PROCESSING_ERROR = "Lo siento, he tenido un problema al procesar la petición. Puede repetirla."
CANNOT_PREPARE = "No puedo preparar {name}."

SWITCHED_TO = {
    AssistantModel.VENTO: "Cambiando a Vento.",
    AssistantModel.GEMINI: "Cambiando a Gemini.",
}

SHUTDOWN_QUESTION = "¿Está seguro de que quiere apagarme señor?"
SHUTDOWN_CONFIRMED = "Venga a tomar por culo. Tirando del cable... Chao!."
SHUTDOWN_CANCELLED = "Apagado cancelado, señor."

REBOOT_QUESTION = "¿Está seguro de que quiere reiniciarme señor?"
REBOOT_CONFIRMED = "Okey reiniciando el sistema, ahora te hablo!."
REBOOT_CANCELLED = "Reinicio cancelado, señor."

EMERGENCY_SHUTDOWN = "Apagado manual accionado!, apagando sistemas. Venga, chao!"
