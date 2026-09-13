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
                "Accept": "text/plain, application/json",
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

    @staticmethod
    def _extract_reply(body: str, content_type: str) -> str:
        """El puente puede responder con texto plano o con JSON."""

        body = body.strip()

        if not body:
            raise RuntimeError("Jarvis devolvió una respuesta vacía")

        looks_like_json = (
            "json" in content_type.lower() or body.startswith(("{", "["))
        )

        if looks_like_json:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return body

            if isinstance(payload, str):
                return payload.strip()

            if isinstance(payload, dict):
                reply = (
                    payload.get("reply")
                    or payload.get("message")
                    or payload.get("content")
                )

                if reply:
                    return str(reply).strip()

                raise RuntimeError("La respuesta JSON no contenía texto")

        return body
