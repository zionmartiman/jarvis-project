"""Gemini REST bridge for Jarvis Voice."""

from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from config import settings
from config.settings import GeminiCredentials
from core.interfaces import AssistantBridge


class GeminiBridge(AssistantBridge):
    """Sends text to Google Gemini without a Python SDK dependency."""

    def __init__(self, credentials: GeminiCredentials, history_limit: int, timeout_seconds: int = 130,
                 system_prompt_path: str | Path | None = None, include_system_prompt: bool = True):
        self._credentials = credentials
        self._history_limit = history_limit
        self._timeout_seconds = timeout_seconds
        self._system_prompt = self._load_system_prompt(system_prompt_path) if include_system_prompt else ""

    @staticmethod
    def _load_system_prompt(system_prompt_path: str | Path | None) -> str:
        default_path = Path(__file__).resolve().parent.parent / "system.md"
        prompt_path = Path(system_prompt_path) if system_prompt_path else default_path
        if not prompt_path.exists():
            return ""
        return prompt_path.read_text(encoding="utf-8").strip()

    def build_request_payload(self, message: str, history: list[dict]) -> dict:
        summaries = [str(item.get("text", "")) for item in history if item.get("role") == "summary" and item.get("text")]
        messages = [item for item in history if item.get("role") != "summary"]
        contents = [{"role": "model" if item.get("role") == "assistant" else "user",
                     "parts": [{"text": str(item.get("text", ""))}]}
                    for item in messages[-self._history_limit:] if item.get("text")]
        contents.append({"role": "user", "parts": [{"text": message}]})

        payload: dict = {"contents": contents, "generationConfig": {"temperature": 0.7}}
        instructions = [self._system_prompt] if self._system_prompt else []
        if summaries:
            instructions.append("Memoria a largo plazo del usuario: " + summaries[-1])
        if instructions:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(instructions)}]}
        return payload

    def ask(self, message: str, history: list[dict]) -> str:
        encoded_model = urllib.parse.quote(self._credentials.model, safe="-_.")

        endpoint = ("https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{encoded_model}:generateContent")
        payload = json.dumps(self.build_request_payload(message, history), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(endpoint, data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "x-goog-api-key": self._credentials.api_key,
                     "User-Agent": "JarvisVoice/2.0 (Raspberry Pi)"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                return self._extract_reply(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = self._extract_http_error_message(error)
            message = f"Gemini no está disponible ({error.code})"
            if detail:
                message += f": {detail}"
            raise RuntimeError(message) from error
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
            reply = "".join(str(part.get("text", "")) for part in parts if part.get("text")).strip()
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("Gemini devolvió una respuesta no válida") from error
        if not reply:
            raise RuntimeError("Gemini devolvió una respuesta vacía")
        return reply


def create_configured_gemini_bridge(
    history_limit: int,
    system_prompt_path: str | Path | None = None,
    include_system_prompt: bool = True,
) -> GeminiBridge:
    """Build every Gemini client with the same configured model and timeout."""
    return GeminiBridge(
        credentials=settings.load_gemini_credentials(),
        history_limit=history_limit,
        timeout_seconds=settings.GEMINI_TIMEOUT_SECONDS,
        system_prompt_path=system_prompt_path,
        include_system_prompt=include_system_prompt,
    )
