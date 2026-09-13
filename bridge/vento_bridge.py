"""
Puente de texto con jarvis_home a través de Vento.

Implementa la interfaz AssistantBridge. Solo se envía texto; nunca el
audio del micrófono. Si en el futuro cambias de backend de IA, crea
una nueva clase que implemente AssistantBridge y sustitúyela en
main.py.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from config.settings import BridgeCredentials
from core.interfaces import AssistantBridge


class VentoBridge(AssistantBridge):
    """Envía mensajes al asistente de IA de Vento y devuelve su respuesta."""

    def __init__(
        self,
        credentials: BridgeCredentials,
        history_limit: int,
        timeout_seconds: int = 130,
    ):
        self._credentials = credentials
        self._history_limit = history_limit
        self._timeout_seconds = timeout_seconds

    def ask(self, message: str, history: list[dict]) -> str:
        separator = "&" if "?" in self._credentials.url else "?"

        request_url = (
            f"{self._credentials.url}{separator}token="
            f"{urllib.parse.quote(self._credentials.token, safe='')}"
        )

        payload = json.dumps(
            {
                "message": message,
                "history": history[-self._history_limit :],
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            request_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/plain, application/json, text/event-stream",
                "User-Agent": "JarvisVoice/2.0 (Raspberry Pi)",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout_seconds
            ) as response:
                body = response.read().decode("utf-8", errors="replace")

                return self._extract_reply(
                    body, response.headers.get("Content-Type", "")
                )

        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:300]

            raise RuntimeError(
                f"Puente de Jarvis no disponible ({error.code}): {detail}"
            ) from error

        except urllib.error.URLError as error:
            raise RuntimeError(
                f"No se pudo contactar con Jarvis: {error.reason}"
            ) from error

    @classmethod
    def _extract_reply(cls, body: str, content_type: str) -> str:
        """Extrae solo el mensaje final, incluso si llega como SSE."""
        body = body.strip()
        if not body:
            raise RuntimeError("Jarvis devolvió una respuesta vacía")

        if "text/event-stream" in content_type.lower() or body.startswith("data:"):
            return cls._extract_sse_reply(body)

        looks_like_json = (
            "json" in content_type.lower() or body.startswith(("{", "["))
        )
        if looks_like_json:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return body
            return cls._extract_json_reply(payload)

        return body

    @classmethod
    def _extract_sse_reply(cls, body: str) -> str:
        """Lee los eventos SSE y devuelve únicamente el contenido terminal."""
        failure_message: str | None = None

        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            event_type = event.get("type")
            if event_type in {"completed", "complete", "final", "reply"}:
                try:
                    return cls._extract_json_reply(event)
                except RuntimeError:
                    continue
            if event_type in {"failed", "error"}:
                reply = event.get("reply")
                if isinstance(reply, dict):
                    failure_message = str(reply.get("content") or "")
                failure_message = failure_message or (
                    "El agente de Jarvis no pudo completar la petición."
                )

        if failure_message:
            raise RuntimeError(failure_message)
        raise RuntimeError(
            "La transmisión de Jarvis terminó sin una respuesta final"
        )

    @staticmethod
    def _extract_json_reply(payload: object) -> str:
        """Obtiene texto de las formas JSON admitidas por el puente."""
        if isinstance(payload, str):
            reply = payload
        elif isinstance(payload, dict):
            candidate = payload.get("reply")
            if isinstance(candidate, dict):
                candidate = (
                    candidate.get("content")
                    or candidate.get("message")
                    or candidate.get("text")
                )
            reply = (
                candidate
                or payload.get("message")
                or payload.get("content")
                or payload.get("text")
            )
        else:
            reply = None

        if isinstance(reply, str) and reply.strip():
            return reply.strip()
        raise RuntimeError("La respuesta JSON no contenía texto")

