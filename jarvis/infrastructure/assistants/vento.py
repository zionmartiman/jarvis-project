"""Text bridge to the jarvis_home agent through Vento. Only text is sent, never audio."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from jarvis.config.credentials import VentoCredentials
from jarvis.domain.conversation import ConversationContext
from jarvis.infrastructure.assistants.vento_reply_parser import parse_vento_reply
from jarvis.ports.assistant import AssistantBridge


class VentoAssistant(AssistantBridge):
    """Sends messages to the Vento AI assistant and returns its reply."""

    def __init__(
        self,
        credentials: VentoCredentials,
        history_limit: int,
        timeout_seconds: int = 130,
    ) -> None:
        self._credentials = credentials
        self._history_limit = history_limit
        self._timeout_seconds = timeout_seconds

    def ask(self, message: str, context: ConversationContext) -> str:
        # The long-term summary is never sent to Vento, only the recent messages.
        separator = "&" if "?" in self._credentials.url else "?"
        request_url = (
            f"{self._credentials.url}{separator}token="
            f"{urllib.parse.quote(self._credentials.token, safe='')}"
        )

        history = [
            {"role": item.role.value, "text": item.text}
            for item in context.messages[-self._history_limit:]
        ]
        payload = json.dumps(
            {"message": message, "history": history},
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
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
                return parse_vento_reply(body, response.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(
                f"Puente de Jarvis no disponible ({error.code}): {detail}"
            ) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"No se pudo contactar con Jarvis: {error.reason}") from error
