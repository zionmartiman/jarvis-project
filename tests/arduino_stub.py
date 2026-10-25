"""Registers a fake `Arduino` package so legacy modules can be imported in tests.

The legacy code imports `Arduino.arduino_mega_connection`, but the folder is `ARDUINO/`.
This only matters on case-sensitive systems, and it disappears with the phase 6 refactor.
"""

import sys
from types import ModuleType


def install() -> None:
    arduino_package = ModuleType("Arduino")
    arduino_package.__path__ = []
    arduino_connection = ModuleType("Arduino.arduino_mega_connection")
    arduino_connection.ArduinoMegaConnection = object
    sys.modules.setdefault("Arduino", arduino_package)
    sys.modules.setdefault("Arduino.arduino_mega_connection", arduino_connection)
