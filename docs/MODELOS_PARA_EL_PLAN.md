# Modelo y esfuerzo recomendados por fase del plan de refactor

Guía para ejecutar [PLAN_REFACTOR.md](PLAN_REFACTOR.md). Una fase por sesión: no empieces la siguiente hasta que los tests de la anterior pasen.

| Fase | Contenido | Modelo recomendado | Esfuerzo | Motivo |
| --- | --- | --- | --- | --- |
| 0 | Red de seguridad: tests de caracterización y arreglo de los tests que fallan | `claude-sonnet-5-5` | medio | Tareas acotadas; los tests fijan el comportamiento actual. |
| 1 | Limpieza, secretos fuera de Git, mover `main.cs` a `ARDUINO/main.cs` | `claude-sonnet-5-5` | medio | Operaciones de Git y ficheros; hay que revisar bien qué se borra. |
| 2 | Paquete `jarvis/`: config, dominio y puertos (código nuevo, sin tocar el antiguo) | `claude-sonnet-5-5` | medio | Código nuevo y puro, con tests que no dependen de hardware. |
| 3 | Infraestructura: Arduino, IPC, audio, voz, asistentes, web | `claude-sonnet-5-5` | alto | Adaptadores que deben mantener el formato de red, de serie y de ficheros. |
| 4 | Aplicación: `PeriodicTask`, depósito, botones, memoria | `claude-sonnet-5-5` | alto | Hilos y concurrencia; la lógica de avisos debe quedar idéntica. |
| 5 | Conversación: dividir `core/conversation.py` en clases pequeñas | `claude-opus-5-5` (o `claude-sonnet-5-5` con esfuerzo máximo si no está disponible) | alto o máximo | Fase de mayor riesgo: comparar cada clase con el original línea a línea. |
| 6 | Arranque, `bootstrap/`, servicio de avisos y shims de compatibilidad | `claude-sonnet-5-5` | alto | Orden de construcción y arranque que no debe cambiar. |
| 7 | Retirar código antiguo, borrar `ARDUINO/arduino_mega_connection.py` y actualizar documentación | `claude-sonnet-5-5` | medio | Limpieza final y revisión de la documentación. |

## Notas

- **No uses Haiku para las fases 3 a 6.** Sirve para las fases 0 a 2 y 7, pero el riesgo de romper el flujo de voz sin que lo detecte la suite de tests es demasiado alto para el resto.
- **Cambiar de modelo entre fases:** usa `/model` en Claude Code. El esfuerzo se ajusta con el selector de esfuerzo; no se puede cambiar desde dentro de la conversación.
- **Antes de cada commit:** revisa que los tests pasen con `python -m unittest discover -s tests -t .` y pide confirmación al propietario, como indica el plan.
