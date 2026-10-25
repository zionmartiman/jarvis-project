"""Gemini REST assistant, without a Python SDK dependency."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping

from jarvis.config.credentials import GeminiCredentials
from jarvis.domain.conversation import ConversationContext, Role
from jarvis.ports.assistant import AssistantBridge

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_TEMPERATURE = 0.7


class GeminiHttpError(RuntimeError):
    """Gemini answered with an HTTP error; ``status`` is its code."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class GeminiAssistant(AssistantBridge):
    """Sends text to Google Gemini and returns its reply."""

    def __init__(
        self,
        credentials: GeminiCredentials,
        history_limit: int,
        timeout_seconds: int = 130,
        system_prompt: str = "",
        generation_config: Mapping[str, object] | None = None,
    ) -> None:
        self._credentials = credentials
        self._history_limit = history_limit
        self._timeout_seconds = timeout_seconds
        self._system_prompt = system_prompt
        self._generation_config = dict(generation_config or {})

    def build_request_payload(self, message: str, context: ConversationContext) -> dict:
        contents = [
            {
                "role": "model" if item.role is Role.ASSISTANT else "user",
                "parts": [{"text": item.text}],
            }
            for item in context.messages[-self._history_limit:]
            if item.text
        ]
        contents.append({"role": "user", "parts": [{"text": message}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {"temperature": _TEMPERATURE, **self._generation_config},
        }
        instructions = [self._system_prompt] if self._system_prompt else []
        if context.summary:
            instructions.append("Memoria a largo plazo del usuario: " + context.summary)
        if instructions:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(instructions)}]}
        return payload

    def ask(self, message: str, context: ConversationContext) -> str:
        encoded_model = urllib.parse.quote(self._credentials.model, safe="-_.")
        payload = json.dumps(
            self.build_request_payload(message, context), ensure_ascii=False
        ).encode("utf-8")
        request = urllib.request.Request(
            _ENDPOINT.format(model=encoded_model),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-goog-api-key": self._credentials.api_key,
                "User-Agent": "JarvisVoice/2.0 (Raspberry Pi)",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                return self._extract_reply(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = self._extract_http_error_message(error)
            failure = f"Gemini no está disponible ({error.code})"
            if detail:
                failure += f": {detail}"
            raise GeminiHttpError(failure, error.code) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"No se pudo contactar con Gemini: {error.reason}") from error

    @staticmethod
    def _extract_http_error_message(error: urllib.error.HTTPError) -> str:
        try:
            payload = json.loads(error.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        details = payload.get("error")
        if not isinstance(details, dict):
            return ""
        message = details.get("message")
        return message.strip() if isinstance(message, str) else ""

    @staticmethod
    def _extract_reply(body: str) -> str:
        try:
            payload = json.loads(body)
            parts = payload["candidates"][0]["content"]["parts"]
            reply = "".join(
                str(part.get("text", "")) for part in parts if part.get("text")
            ).strip()
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("Gemini devolvió una respuesta no válida") from error
        if not reply:
            raise RuntimeError("Gemini devolvió una respuesta vacía")
        return reply
