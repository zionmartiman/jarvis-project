"""
Orquestación de la conversación.

Esta clase es el "cerebro" del flujo: decide qué hacer con cada frase
reconocida, pero no sabe nada de Vosk, Azure ni Vento. Solo conoce las
interfaces (SpeechRecognizer, SpeechSynthesizer, AssistantBridge,
SystemController), así que se puede probar con implementaciones falsas
(mocks/stubs) sin tocar hardware real ni gastar cuota de Azure.
"""

from __future__ import annotations

import sys

from audio.microphone_stream import MicrophoneStream
from core import intents
from core.interfaces import (
    AssistantBridge,
    AssistantStatus,
    SpeechRecognizer,
    SpeechSynthesizer,
    StatusIndicator,
    SystemController,
)


class ConversationOrchestrator:
    """Mantiene el bucle principal: esperar activación y conversar."""

    def __init__(
        self,
        microphone: MicrophoneStream,
        recognizer: SpeechRecognizer,
        synthesizer: SpeechSynthesizer,
        bridge: AssistantBridge,
        power_controller: SystemController,
        status_indicator: StatusIndicator,
        max_history_items: int,
    ):
        self._microphone = microphone
        self._recognizer = recognizer
        self._synthesizer = synthesizer
        self._bridge = bridge
        self._power_controller = power_controller
        self._status_indicator = status_indicator
        self._max_history_items = max_history_items

    def run_forever(self) -> None:
        """Bucle principal: espera la palabra de activación y conversa."""

        self._speak("Sistemas listos y esperando instrucciones señor.")

        while True:
            self._set_status(AssistantStatus.WAITING)
            print("Esperando la palabra «Jarvis»...", flush=True)
            self._recognizer.wait_for_wake_word()
            print("Activación detectada.", flush=True)

            try:
                self._run_conversation()
            except Exception as error:
                print(
                    f"Error iniciando la conversación: {error}",
                    file=sys.stderr,
                    flush=True,
                )
                self._microphone.clear()

    def _run_conversation(self) -> None:
        """Mantiene turnos consecutivos hasta recibir una orden de cierre."""

        history: list[dict] = []

        self._speak("Sí señor?")

        while True:
            print("Escuchando el siguiente mensaje...", flush=True)
            command = self._listen_for_sentence()
            print(f"Usuario: {command}", flush=True)

            power_result = self._handle_power_command(command)
            if power_result is True:
                return
            if power_result is False:
                continue

            if intents.wants_to_end_conversation(command):
                self._speak(
                    "Servicio detenido hasta que me llame por mi nombre, "
                    "señor."
                )
                return

            self._handle_turn(command, history)

    def _handle_power_command(self, command_text: str) -> bool | None:
        """
        Gestiona "apaga la raspberry" / "reinicia la raspberry" con
        confirmación previa.

        Devuelve None si `command_text` no es un comando de apagado o
        reinicio. Si lo es, devuelve True cuando la acción se ha
        ejecutado (fin de la conversación) o False cuando se ha
        cancelado (la conversación continúa).
        """

        if intents.wants_to_shutdown(command_text):
            return self._confirm_and_run(
                question="¿Está seguro de que quiere apagar la Raspberry, "
                "señor?",
                confirmed_reply="De acuerdo, señor. Apagando la Raspberry.",
                cancelled_reply="Apagado cancelado, señor.",
                action=self._power_controller.shutdown,
            )

        if intents.wants_to_reboot(command_text):
            return self._confirm_and_run(
                question="¿Está seguro de que quiere reiniciar la "
                "Raspberry, señor?",
                confirmed_reply="De acuerdo, señor. Reiniciando la "
                "Raspberry.",
                cancelled_reply="Reinicio cancelado, señor.",
                action=self._power_controller.reboot,
            )

        return None

    def _confirm_and_run(
        self,
        question: str,
        confirmed_reply: str,
        cancelled_reply: str,
        action,
    ) -> bool:
        self._speak(question)

        print("Esperando confirmación...", flush=True)
        confirmation = self._listen_for_sentence()
        print(f"Confirmación: {confirmation}", flush=True)

        if intents.is_confirmation(confirmation):
            self._speak(confirmed_reply)
            action()
            return True

        self._speak(cancelled_reply)
        return False

    def _handle_turn(self, command: str, history: list[dict]) -> None:
        try:
            self._set_status(AssistantStatus.PROCESSING)
            print("Consultando a Jarvis...", flush=True)
            reply = self._bridge.ask(command, history)
            print(f"Jarvis: {reply}", flush=True)

            history.extend(
                [
                    {"role": "user", "text": command},
                    {"role": "assistant", "text": reply},
                ]
            )

            # Evita que el historial local crezca indefinidamente.
            if len(history) > self._max_history_items:
                del history[: -self._max_history_items]

            self._speak(reply)

            # Al terminar de reproducir, el bucle vuelve directamente a
            # escuchar. No hace falta decir "Jarvis" de nuevo.
            self._microphone.clear()

        except Exception as error:
            print(
                f"Error procesando el mensaje: {error}",
                file=sys.stderr,
                flush=True,
            )

            try:
                self._speak(
                    "Lo siento, he tenido un problema al procesar la "
                    "petición. Puede repetirla."
                )
            except Exception as speech_error:
                print(
                    f"Error adicional de voz: {speech_error}",
                    file=sys.stderr,
                    flush=True,
                )

            # Aunque haya fallado un turno, permanece en conversación.
            self._microphone.clear()

    def _listen_for_sentence(self) -> str:
        self._set_status(AssistantStatus.LISTENING)
        return self._recognizer.listen_for_sentence()

    def _set_status(self, status: AssistantStatus) -> None:
        """Actualiza el indicador físico sin interrumpir la conversación."""

        try:
            self._status_indicator.set_status(status)
        except Exception as error:
            print(
                f"Error actualizando el LED de estado: {error}",
                file=sys.stderr,
                flush=True,
            )

    def _speak(self, text: str) -> None:
        self._set_status(AssistantStatus.SPEAKING)

        # Durante la respuesta no queremos que el micrófono capture la
        # propia voz de Jarvis.
        self._microphone.stop_capture()
        self._synthesizer.speak(text)
