"""Conversation orchestration for Jarvis Voice."""

from __future__ import annotations

import sys
from collections.abc import Callable

from audio.microphone_stream import MicrophoneStream
from core import intents
from core.interfaces import AssistantBridge, AssistantStatus, SpeechRecognizer, SpeechSynthesizer, StatusIndicator, SystemController


class ConversationOrchestrator:
    def __init__(self, microphone: MicrophoneStream, recognizer: SpeechRecognizer, synthesizer: SpeechSynthesizer, bridge_factory: Callable[[str], AssistantBridge], power_controller: SystemController, status_indicator: StatusIndicator, max_history_items: int):
        self._microphone = microphone
        self._recognizer = recognizer
        self._synthesizer = synthesizer
        self._bridge_factory = bridge_factory
        self._bridge: AssistantBridge | None = None
        self._power_controller = power_controller
        self._status_indicator = status_indicator
        self._max_history_items = max_history_items

    def run_forever(self) -> None:
        self._speak("Sistemas listos. Para usar Gemini diga uno. Para usar Vento diga dos.")
        self._choose_assistant()
        while True:
            self._set_status(AssistantStatus.WAITING)
            print("Esperando la palabra «Jarvis»...", flush=True)
            self._recognizer.wait_for_wake_word()
            try:
                self._run_conversation()
            except Exception as error:
                print(f"Error iniciando la conversación: {error}", file=sys.stderr, flush=True)
                self._microphone.clear()

    def _choose_assistant(self) -> None:
        choices = {"uno": ("gemini", "Gemini"), "1": ("gemini", "Gemini"), "dos": ("vento", "Vento"), "2": ("vento", "Vento")}
        while self._bridge is None:
            choice = self._listen_for_sentence().strip().lower()
            selected = choices.get(choice)
            if selected is None:
                self._speak("No he entendido la opción. Diga uno para Gemini o dos para Vento.")
                continue
            model, name = selected
            try:
                self._bridge = self._bridge_factory(model)
            except Exception as error:
                print(f"Error preparando {name}: {error}", file=sys.stderr, flush=True)
                self._speak(f"No puedo preparar {name}. Diga uno para Gemini o dos para Vento.")
                continue
            self._speak(f"Usaré {name}, señor.")
            self._microphone.clear()

    def _run_conversation(self) -> None:
        history: list[dict] = []
        self._speak("Sí señor?")
        while True:
            command = self._listen_for_sentence()
            power_result = self._handle_power_command(command)
            if power_result is True:
                return
            if power_result is False:
                continue
            if intents.wants_to_end_conversation(command):
                self._speak("Servicio detenido hasta que me llame por mi nombre, señor.")
                return
            self._handle_turn(command, history)

    def _handle_power_command(self, command_text: str) -> bool | None:
        if intents.wants_to_shutdown(command_text):
            return self._confirm_and_run("¿Está seguro de que quiere apagar la Raspberry, señor?", "De acuerdo, señor. Apagando la Raspberry.", "Apagado cancelado, señor.", self._power_controller.shutdown)
        if intents.wants_to_reboot(command_text):
            return self._confirm_and_run("¿Está seguro de que quiere reiniciar la Raspberry, señor?", "De acuerdo, señor. Reiniciando la Raspberry.", "Reinicio cancelado, señor.", self._power_controller.reboot)
        return None

    def _confirm_and_run(self, question: str, confirmed_reply: str, cancelled_reply: str, action) -> bool:
        self._speak(question)
        confirmation = self._listen_for_sentence()
        if intents.is_confirmation(confirmation):
            self._speak(confirmed_reply)
            action()
            return True
        self._speak(cancelled_reply)
        return False

    def _handle_turn(self, command: str, history: list[dict]) -> None:
        try:
            self._set_status(AssistantStatus.PROCESSING)
            if self._bridge is None:
                raise RuntimeError("No hay un modelo de IA seleccionado")
            reply = self._bridge.ask(command, history)
            history.extend([{"role": "user", "text": command}, {"role": "assistant", "text": reply}])
            if len(history) > self._max_history_items:
                del history[:-self._max_history_items]
            self._speak(reply)
            self._microphone.clear()
        except Exception as error:
            print(f"Error procesando el mensaje: {error}", file=sys.stderr, flush=True)
            self._speak("Lo siento, he tenido un problema al procesar la petición. Puede repetirla.")
            self._microphone.clear()

    def _listen_for_sentence(self) -> str:
        self._set_status(AssistantStatus.LISTENING)
        return self._recognizer.listen_for_sentence()

    def _set_status(self, status: AssistantStatus) -> None:
        try:
            self._status_indicator.set_status(status)
        except Exception as error:
            print(f"Error actualizando el LED de estado: {error}", file=sys.stderr, flush=True)

    def _speak(self, text: str) -> None:
        self._set_status(AssistantStatus.SPEAKING)
        self._microphone.stop_capture()
        self._synthesizer.speak(text)
