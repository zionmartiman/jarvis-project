"""Extracts the final reply text from a Vento bridge response (plain text, JSON or SSE)."""

from __future__ import annotations

import json

_TERMINAL_EVENTS = {"completed", "complete", "final", "reply"}
_FAILURE_EVENTS = {"failed", "error"}


def parse_vento_reply(body: str, content_type: str) -> str:
    """Return only the final message, even when it arrives as server-sent events."""
    body = body.strip()
    if not body:
        raise RuntimeError("Jarvis devolvió una respuesta vacía")

    if "text/event-stream" in content_type.lower() or body.startswith("data:"):
        return _extract_sse_reply(body)

    looks_like_json = "json" in content_type.lower() or body.startswith(("{", "["))
    if looks_like_json:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return body
        return _extract_json_reply(payload)

    return body


def _extract_sse_reply(body: str) -> str:
    """Read the SSE events and return only the terminal content."""
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
        if event_type in _TERMINAL_EVENTS:
            try:
                return _extract_json_reply(event)
            except RuntimeError:
                continue
        if event_type in _FAILURE_EVENTS:
            reply = event.get("reply")
            if isinstance(reply, dict):
                failure_message = str(reply.get("content") or "")
            failure_message = failure_message or (
                "El agente de Jarvis no pudo completar la petición."
            )

    if failure_message:
        raise RuntimeError(failure_message)
    raise RuntimeError("La transmisión de Jarvis terminó sin una respuesta final")


def _extract_json_reply(payload: object) -> str:
    """Get the text from the JSON shapes the bridge may use."""
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
