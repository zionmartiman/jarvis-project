"""Keeps the active assistant and switches between Gemini and Vento."""

from __future__ import annotations

import logging
from collections.abc import Callable

from jarvis.application.conversation.voice import Voice
from jarvis.domain import phrases
from jarvis.domain.assistant_model import AssistantModel
from jarvis.ports.assistant import AssistantBridge

LOGGER = logging.getLogger(__name__)


class AssistantSelector:
    """Builds the bridge of the active model and swaps it when the user asks."""

    def __init__(
        self,
        factory: Callable[[AssistantModel], AssistantBridge],
        voice: Voice,
    ) -> None:
        self._factory = factory
        self._voice = voice
        self._model: AssistantModel | None = None
        self._bridge: AssistantBridge | None = None

    @property
    def model(self) -> AssistantModel | None:
        return self._model

    @property
    def bridge(self) -> AssistantBridge | None:
        return self._bridge

    def start(self, model: AssistantModel) -> None:
        """Select ``model`` even when its bridge cannot be built (the user is told)."""
        self._model = model
        try:
            self._bridge = self._factory(model)
        except Exception as error:
            self._report_failure(model, error)

    def switch(self) -> bool:
        """Change to the other model; return False, keeping the current one, if it fails."""
        model = self._model.other if self._model is not None else AssistantModel.GEMINI
        try:
            bridge = self._factory(model)
        except Exception as error:
            self._report_failure(model, error)
            return False
        self._bridge = bridge
        self._model = model
        self._voice.say(phrases.SWITCHED_TO[model])
        return True

    def _report_failure(self, model: AssistantModel, error: Exception) -> None:
        LOGGER.error("Unable to prepare %s: %s", model.display_name, error)
        self._voice.say(phrases.CANNOT_PREPARE.format(name=model.display_name))
