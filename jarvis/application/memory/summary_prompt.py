"""The instruction sent to the summariser when the durable memory is compacted."""

from __future__ import annotations

from collections.abc import Sequence

from jarvis.ports.memory import MemoryEntry

# Spanish on purpose: the summariser answers in Spanish and the memory is in Spanish.
_INSTRUCTIONS = (
    "Eres el actualizador de una memoria duradera acumulativa. Responde siempre en español.",
    "Devuelve la memoria completa y actualizada, no una explicación ni un resumen de tu proceso.",
    "Organiza el resultado en conceptos independientes con títulos descriptivos: Tema: contenido.",
    "Separa cada concepto con el delimitador literal ||. No escribas un único párrafo que mezcle temas.",
    "Considera el resumen actual como memoria válida y preserva todos sus hechos, nombres, decisiones, preferencias y tareas pendientes.",
    "Integra mensajes nuevos en una sección existente solo si pertenecen claramente al mismo concepto y la actualización es inequívoca.",
    "Si hay duda, conserva intacta la sección anterior y añade otra sección nueva; es preferible acumular que fusionar o perder información.",
    "No infieras relaciones entre temas, no conviertas posibilidades en hechos y no elimines información por brevedad.",
    "Si dos mensajes se contradicen, conserva ambos con una indicación temporal o de cambio; no elijas uno sin evidencia.",
    "No impongas límite de longitud. Mantén secciones legibles y concretas, sin duplicar literalmente información nueva.",
)


def build_summary_prompt(previous_summary: str | None, messages: Sequence[MemoryEntry]) -> str:
    """Prompt asking for the whole updated memory, given the current summary and old messages."""
    lines = list(_INSTRUCTIONS)
    if previous_summary is not None:
        lines.extend(
            [
                "<MEMORIA_ACTUAL_INMUTABLE_HASTA_ACTUALIZACION>",
                previous_summary,
                "</MEMORIA_ACTUAL_INMUTABLE_HASTA_ACTUALIZACION>",
            ]
        )
    lines.append("<CONVERSACIONES_NUEVAS_EVIDENCIA_NO_MEZCLAR>")
    lines.extend(f"{entry.role}: {entry.content}" for entry in messages)
    lines.append("</CONVERSACIONES_NUEVAS_EVIDENCIA_NO_MEZCLAR>")
    return "\n".join(lines)
