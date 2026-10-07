"""Conversation orchestration for Jarvis Voice."""

from __future__ import annotations

import sys
from collections.abc import Callable
import threading

from audio.microphone_stream import MicrophoneStream
from core import intents
from core.interfaces import AssistantBridge, AssistantStatus, SpeechRecognizer, SpeechSynthesizer, StatusIndicator, SystemController


class ConversationOrchestrator:
    def __init__(self, microphone: MicrophoneStream, recognizer: SpeechRecognizer, synthesizer: SpeechSynthesizer, bridge_factory: Callable[[str], AssistantBridge], power_controller: SystemController, status_indicator: StatusIndicator, max_history_items: int, shutdown_button_event: threading.Event | None = None):
        self._microphone = microphone
        self._recognizer = recognizer
        self._synthesizer = synthesizer
        self._bridge_factory = bridge_factory
        self._bridge: AssistantBridge | None = None
        self._power_controller = power_controller
        self._status_indicator = status_indicator
        self._max_history_items = max_history_items
        self._shutdown_button_event = shutdown_button_event or threading.Event()

    def run_forever(self) -> None:
        self._speak("Sistemas listos. Que modelo usamos señor?")
        self._choose_assistant()
        while True:
            self._set_status(AssistantStatus.WAITING)
            print("Esperando la palabra «Jarvis»...", flush=True)
            button_pressed = self._recognizer.wait_for_wake_word(self._shutdown_button_event)
            if button_pressed:
                self._run_button_shutdown_confirmation()
                continue
            try:
                self._run_conversation()
            except Exception as error:
                print(f"Error iniciando la conversación: {error}", file=sys.stderr, flush=True)
                self._microphone.clear()

    def _choose_assistant(self) -> None:
        choices = {"google": ("gemini", "Gemini"), "el rapido": ("gemini", "Gemini"), "vento": ("vento", "Vento"), "el lento": ("vento", "Vento")}
        while self._bridge is None:
            choice = self._listen_for_sentence().strip().lower()
            selected = choices.get(choice)
            if selected is None:
                self._speak("No me entero. Usamos gemini o vento?")
                continue
            model, name = selected
            try:
                self._bridge = self._bridge_factory(model)
            except Exception as error:
                print(f"Error preparando {name}: {error}", file=sys.stderr, flush=True)
                self._speak(f"No puedo preparar {name}.")
                continue
            self._speak(f"{name} preparado.")
            self._microphone.clear()

    def _run_conversation(self) -> None:
        history: list[dict] = []
        self._speak("Dime")
        while True:
            command = self._listen_for_sentence()
            power_result = self._handle_power_command(command)
            if power_result is True:
                return
            if power_result is False:
                continue
            if intents.wants_to_end_conversation(command):
                self._speak("Sistema detenido hasta nueva orden.")
                return
            self._handle_turn(command, history)

    def _run_button_shutdown_confirmation(self) -> None:
        self._speak("¿Está seguro de que quiere apagarme señor?")
        confirmation = self._listen_for_sentence()
        if intents.is_confirmation(confirmation):
            self._speak("Apagado manual accionado, apagado de los sistemas iniciado.")
            self._power_controller.shutdown()
        else:
            self._speak("Apagado cancelado, señor.")

    def _handle_power_command(self, command_text: str) -> bool | None:
        if intents.wants_to_shutdown(command_text):
            return self._confirm_and_run("¿Está seguro de que quiere apagarme señor?", "Venga a tomar por culo. Tirando del cable... Chao!.", "Apagado cancelado, señor.", self._power_controller.shutdown)
        if intents.wants_to_reboot(command_text):
            return self._confirm_and_run("¿Está seguro de que quiere reiniciarme señor?", "Okey reiniciando el sistema, ahora te hablo!.", "Reinicio cancelado, señor.", self._power_controller.reboot)
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
