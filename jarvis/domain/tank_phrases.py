"""Spoken texts about the rainwater tank (Spanish). Keep identical to the original."""

from __future__ import annotations

from jarvis.domain.tank import TankLevel, TankStatus

STATUS_PHRASES: dict[TankStatus, str] = {
    TankStatus.FULL: "Depósito lleno.",
    TankStatus.NEARLY_FULL: "Depósito casi lleno.",
    TankStatus.GOOD: "Buenos niveles de agua.",
    TankStatus.LOW: "Niveles de agua bajos.",
    TankStatus.VERY_LOW: "Niveles de agua muy bajos, se está a punto de quedar sin agua.",
    TankStatus.EMPTY: "Depósito vacío.",
}


def level_phrase(level: TankLevel) -> str:
    return f"Deposito al {level.fill_percentage} por ciento."
