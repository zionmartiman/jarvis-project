"""Gemini REST bridge for Jarvis Voice."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from config.settings import GeminiCredentials
from core.interfaces import AssistantBridge


class GeminiBridge(AssistantBridge):
    """Sends text to Google Gemini without a Python SDK dependency."""

    def __init__(self, credentials: GeminiCredentials, history_limit: int, timeout_seconds: int = 130):
        self._credentials = credentials
        self._history_limit = history_limit
        self._timeout_seconds = timeout_seconds

    def ask(self, message: str, history: list[dict]) -> str:
        contents = [{"role": "model" if item.get("role") == "assistant" else "user",
                     "parts": [{"text": str(item.get("text", ""))}]}
                    for item in history[-self._history_limit:] if item.get("text")]
        contents.append({"role": "user", "parts": [{"text": message}]})
        encoded_model = urllib.parse.quote(self._credentials.model, safe="-_.")

        endpoint = ("https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{encoded_model}:generateContent")
        payload = json.dumps({"contents": contents, "generationConfig": {"temperature": 0.7}},
                             ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(endpoint, data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "x-goog-api-key": self._credentials.api_key,
                     "User-Agent": "JarvisVoice/2.0 (Raspberry Pi)"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                return self._extract_reply(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Gemini no está disponible ({error.code})") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"No se pudo contactar con Gemini: {error.reason}") from error

    @staticmethod
    def _extract_reply(body: str) -> str:
        try:
            payload = json.loads(body)
            parts = payload["candidates"][0]["content"]["parts"]
            reply = "".join(str(part.get("text", "")) for part in parts if part.get("text")).strip()
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("Gemini devolvió una respuesta no válida") from error
        if not reply:
            raise RuntimeError("Gemini devolvió una respuesta vacía")
        return reply
