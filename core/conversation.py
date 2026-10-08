"""Conversation orchestration for Jarvis Voice."""

from __future__ import annotations

import sys
from collections.abc import Callable
import threading
from typing import TYPE_CHECKING

from core import intents
from core.interfaces import AssistantBridge, AssistantStatus, SpeechRecognizer, SpeechSynthesizer, StatusIndicator, SystemController

if TYPE_CHECKING:
    from audio.microphone_stream import MicrophoneStream


class ConversationOrchestrator:
    def __init__(self, microphone: MicrophoneStream, recognizer: SpeechRecognizer, synthesizer: SpeechSynthesizer, bridge_factory: Callable[[str], AssistantBridge], power_controller: SystemController, status_indicator: StatusIndicator, max_history_items: int, shutdown_button_event: threading.Event | None = None, response_interrupt_event: threading.Event | None = None):
        self._microphone = microphone
        self._recognizer = recognizer
        self._synthesizer = synthesizer
        self._bridge_factory = bridge_factory
        self._bridge: AssistantBridge | None = None
        self._active_model: str | None = None
        self._power_controller = power_controller
        self._status_indicator = status_indicator
        self._max_history_items = max_history_items
        self._shutdown_button_event = shutdown_button_event or threading.Event()
        self._response_interrupt_event = response_interrupt_event or threading.Event()
        self._shutdown_started = threading.Event()
        self._model_reply_active = threading.Event()
        self._model_reply_interrupted = threading.Event()
        self._speech_lock = threading.Lock()

    def run_forever(self) -> None:
        threading.Thread(
            target=self._watch_shutdown_button,
            name="shutdown-button-watcher",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._watch_response_interrupt_button,
            name="response-interrupt-button-watcher",
            daemon=True,
        ).start()
        self._speak("Sistemas listos.")
        self._initialize_assistant()
        while True:
            self._set_status(AssistantStatus.WAITING)
            print("Esperando la palabra «Jarvis»...", flush=True)
            self._recognizer.wait_for_wake_word()
            try:
                self._run_conversation()
            except Exception as error:
                print(f"Error iniciando la conversación: {error}", file=sys.stderr, flush=True)
                self._microphone.clear()

    def _initialize_assistant(self) -> None:
        self._active_model = "gemini"
        try:
            self._bridge = self._bridge_factory(self._active_model)
        except Exception as error:
            print(f"Error preparando Gemini: {error}", file=sys.stderr, flush=True)
            self._speak("No puedo preparar Gemini.")

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
            if intents.wants_to_change_model(command):
                self._switch_model()
                continue
            if intents.wants_to_end_conversation(command):
                self._speak("Sistema detenido hasta nueva orden.")
                return
            self._handle_turn(command, history)

    def _switch_model(self) -> None:
        model = "vento" if self._active_model == "gemini" else "gemini"
        name = "Vento" if model == "vento" else "Gemini"
        try:
            bridge = self._bridge_factory(model)
        except Exception as error:
            print(f"Error preparando {name}: {error}", file=sys.stderr, flush=True)
            self._speak(f"No puedo preparar {name}.")
            return
        self._bridge = bridge
        self._active_model = model
        reply = "Cambiando a Vento." if model == "vento" else "Cambiar a Gemini."
        self._speak(reply)
        self._microphone.clear()

    def _run_button_shutdown(self) -> None:
        if self._shutdown_started.is_set():
            return
        self._shutdown_started.set()
        print("Botón de apagado: interrumpiendo Jarvis y apagando el sistema.", flush=True)
        self._microphone.stop_capture()

        while not self._speech_lock.acquire(timeout=0.05):
            try:
                self._synthesizer.interrupt()
            except Exception as error:
                print(f"Error interrumpiendo la voz: {error}", file=sys.stderr, flush=True)

        try:
            self._synthesizer.interrupt()
            self._set_status(AssistantStatus.SPEAKING)
            self._synthesizer.speak("Apagado manual accionado!, apagando sistemas. Venga, chao!")
        except Exception as error:
            print(f"Error reproduciendo el aviso de apagado: {error}", file=sys.stderr, flush=True)
        finally:
            self._speech_lock.release()

        try:
            self._power_controller.shutdown()
        except Exception as error:
            print(f"Error apagando el sistema: {error}", file=sys.stderr, flush=True)

    def _watch_shutdown_button(self) -> None:
        self._shutdown_button_event.wait()
        self._run_button_shutdown()

    def _watch_response_interrupt_button(self) -> None:
        while not self._shutdown_started.is_set():
            self._response_interrupt_event.wait()
            self._response_interrupt_event.clear()
            if self._shutdown_started.is_set():
                return
            if not self._model_reply_active.is_set():
                continue
            self._model_reply_interrupted.set()
            try:
                self._synthesizer.interrupt()
            except Exception as error:
                print(f"Error interrumpiendo la respuesta del modelo: {error}", file=sys.stderr, flush=True)

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
            assistant_name = "Gemini" if self._active_model == "gemini" else "Vento"
            print(f"{assistant_name}: {reply}", flush=True)
            history.extend([{"role": "user", "text": command}, {"role": "assistant", "text": reply}])
            if len(history) > self._max_history_items:
                del history[:-self._max_history_items]
            self._speak_model_reply(reply)
            self._microphone.clear()
        except Exception as error:
            print(f"Error procesando el mensaje: {error}", file=sys.stderr, flush=True)
            self._speak("Lo siento, he tenido un problema al procesar la petición. Puede repetirla.")
            self._microphone.clear()

    def _speak_model_reply(self, reply: str) -> None:
        self._model_reply_interrupted.clear()
        self._model_reply_active.set()
        try:
            self._speak(reply)
        finally:
            self._model_reply_active.clear()

        was_interrupted = self._model_reply_interrupted.is_set()
        self._model_reply_interrupted.clear()
        if was_interrupted and not self._shutdown_started.is_set():
            self._speak("Sí, dime")

    def _listen_for_sentence(self) -> str:
        self._set_status(AssistantStatus.LISTENING)
        sentence = self._recognizer.listen_for_sentence()
        print(f"Yo: {sentence}", flush=True)
        return sentence

    def _set_status(self, status: AssistantStatus) -> None:
        try:
            self._status_indicator.set_status(status)
        except Exception as error:
            print(f"Error actualizando el LED de estado: {error}", file=sys.stderr, flush=True)

    def _speak(self, text: str) -> None:
        if self._shutdown_started.is_set():
            return
        with self._speech_lock:
            if self._shutdown_started.is_set():
                return
            self._set_status(AssistantStatus.SPEAKING)
            self._microphone.stop_capture()
            try:
                self._synthesizer.speak(text)
            except Exception:
                if not self._shutdown_started.is_set():
                    raise
