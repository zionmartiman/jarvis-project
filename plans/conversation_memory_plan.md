# Plan e implementación: memoria de conversación

## Objetivo y alcance

La memoria guarda conversaciones de Jarvis en el dispositivo, reinyecta una síntesis duradera y limita el historial de Gemini a cinco interacciones completas. La versión implementada usa únicamente la biblioteca estándar para almacenamiento, concurrencia y serialización; reutiliza el puente REST Gemini ya presente para sintetizar recuerdos. Vento conserva el historial de sesión que ya recibía.

La persistencia local no requiere conexión. Si Gemini no está disponible durante la compactación, el archivo original se conserva y la síntesis se reintenta al superar de nuevo un umbral en un intercambio posterior.

## Fases

### Fase 1: persistencia local y control por tamaño

- `ConversationMemory` coordina persistencia, proyección de contexto y compactación; `MemoryBackend` abstrae el almacenamiento.
- `JsonlMemoryBackend` escribe un objeto por línea con `timestamp`, `role` y `content` UTF-8. Cada intercambio se añade con una sola escritura lógica y `fsync`.
- El tamaño se comprueba al iniciar el gestor y después de cada intercambio, sin un hilo de polling que despierte y consulte la MicroSD continuamente.
- El límite predeterminado es 4096 bytes. Una compactación guarda antes una copia `conversation.jsonl.bak`, escribe un temporal en el mismo directorio, sincroniza sus datos y sustituye el historial con `os.replace`.
- Al leer, solo se descarta una última línea incompleta, compatible con un corte durante un append. Una línea corrupta dentro del archivo se considera error y no se oculta ni se sobrescribe.

### Fase 2: ventana de contexto

- El prompt de Gemini recibe, cuando exista, una entrada con el resumen de largo plazo y exactamente los últimos cinco pares completos usuario/asistente.
- El gestor excluye intercambios incompletos y nunca corta un par para satisfacer el límite de mensajes.
- Gemini tiene capacidad de historial para once entradas: una síntesis y diez mensajes recientes. El mensaje nuevo sigue añadiéndose por `GeminiBridge`.
- Cinco interacciones son una cota determinista del historial, no una cota matemática de tokens: el tamaño de cada mensaje y `system.md` varía. La documentación de Google incluye la instrucción de sistema en el cómputo de tokens. Si se requiere un máximo exacto, debe añadirse `countTokens` más una política de reducción de entrada.

### Fase 3: síntesis y compactación

- Al superar diez registros de mensajes o 4096 bytes, se separa el material antiguo de los últimos diez registros y se solicita una síntesis en español que priorice entidades, nombres, preferencias, decisiones y tareas pendientes.
- El resumen se genera con `gemini-3.5-flash-lite`, modelo estable de bajo coste/alta velocidad según el catálogo consultado. La llamada se ejecuta en un hilo daemon para no bloquear la locución; no se inicia otra compactación en paralelo en la misma instancia.
- Se incorpora el resumen anterior en cada síntesis posterior. La copia de respaldo se actualiza antes de reemplazar el archivo principal.
- Si solo existen cinco interacciones y el tamaño excede 4 KiB, no se eliminan mensajes recientes: el límite físico puede superarse hasta que existan registros antiguos que resumir. La ventana conversacional prevalece sobre la cuota de bytes.

### Fase 4: backend de grafo

- `MemoryBackend` fija las operaciones de lectura, append, reemplazo, copia de respaldo y tamaño sin exponer detalles al orquestador.
- Un futuro `Neo4jMemoryBackend` debe implementar esa API con transacciones idempotentes e índices para entidades/relaciones, además de preservar `ConversationMemory.get_context()` y `record_exchange()`.
- Neo4j no se añade en esta entrega: introducir un servidor y su cliente elevaría consumo, operación y dependencias en la Raspberry Pi antes de que haya una necesidad confirmada.

## Integración en Jarvis

1. `main.py` crea el backend local en `state/conversation.jsonl` e inyecta un callback para síntesis.
2. `ConversationOrchestrator` obtiene contexto persistido solo para Gemini, y persiste intercambios completados de ambos modelos.
3. El API público del puente `ask(message, history)` no cambia.
4. Las pruebas verifican JSONL, corte de energía simulado mediante línea final parcial, rechazo de corrupción interior, ventana de cinco pares, backup, compactación y entrega del historial al puente.

## Operación y riesgos

- Un proceso Jarvis por archivo es el modo de operación asumido; el bloqueo actual protege hilos dentro del proceso, no escritores de procesos independientes.
- `fsync` y reemplazo atómico reducen la ventana de corrupción, pero no pueden garantizar durabilidad frente a firmware defectuoso, pérdida de alimentación del controlador de almacenamiento o hardware averiado.
- El `.bak` conserva la última compactación; no es un sistema de backup rotativo ni una protección frente a la pérdida de toda la tarjeta.
- La memoria puede contener información personal. La ruta hereda los permisos del directorio; el backend crea el archivo con permisos restrictivos cuando es POSIX, pero conviene aplicar permisos de servicio y una política de retención en despliegue.
- La síntesis remite conversaciones antiguas a la API de Gemini. Debe informarse al usuario y revisar política de privacidad, consentimiento, retención y costes antes de producción.
- Recomendación de despliegue: empezar con una copia de `state/`, validar pérdida simulada de energía y latencia del worker en la Raspberry Pi, y observar el tamaño y tasa de compactaciones antes de ajustar los 4 KiB.

## Fuentes oficiales consultadas (8 de octubre de 2026)

- [Gemini: modelos disponibles](https://ai.google.dev/gemini-api/docs/models): identifica `gemini-3.5-flash-lite` como estable y de bajo coste/alta velocidad; la página recomienda modelos recientes para proyectos nuevos.
- [Gemini: recuento de tokens](https://ai.google.dev/gemini-api/docs/tokens): explica límites de contexto y que la instrucción de sistema también consume tokens.
- [Gemini: generación de texto y conversaciones](https://ai.google.dev/gemini-api/docs/text-generation): describe instrucciones de sistema y estado de conversación administrado por API. Jarvis conserva su modo stateless actual y gestiona historial localmente.
- [Python: `os.replace` y `os.fsync`](https://docs.python.org/3/library/os.html#os.replace): reemplazo atómico cuando el sistema de archivos lo soporta y sincronización explícita del descriptor.
- [Python: `tempfile`](https://docs.python.org/3/library/tempfile.html): creación segura de temporales en el directorio de destino para mantener el reemplazo en el mismo sistema de archivos.