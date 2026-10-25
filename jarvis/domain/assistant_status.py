"""Logical states of the assistant, mirrored by the physical status light."""

from __future__ import annotations

from enum import Enum


class AssistantStatus(Enum):
    WAITING = "waiting"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
