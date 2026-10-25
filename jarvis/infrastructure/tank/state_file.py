"""Publishes the latest tank level as a JSON file."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path

from jarvis.domain.tank import TankLevel
from jarvis.ports.tank import TankStateStore

LOGGER = logging.getLogger(__name__)


class JsonTankStateFile(TankStateStore):
    """Writes the level atomically (temporary file plus rename) so readers never see half a file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def save(self, level: TankLevel) -> None:
        try:
            self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary_path = self._path.with_suffix(".tmp")
            temporary_path.write_text(
                json.dumps(asdict(level), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary_path, self._path)
        except OSError:
            LOGGER.exception("Unable to publish rainwater tank state.")
