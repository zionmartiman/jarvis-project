# Plan de implementación: memoria Markdown, Obsidian y Git

> **Nota (refactor):** las rutas de este documento son anteriores a la reestructuración en el paquete `jarvis/`. Equivalencias: `jarvis/application/conversation/turn_handler.py` → `jarvis/application/conversation/`; `jarvis/application/memory/conversation_memory.py` → `jarvis/application/memory/conversation_memory.py` (+ `jarvis/infrastructure/memory/jsonl_backend.py`); `core/intents.py` → `jarvis/domain/intents.py`; `jarvis/config/settings.py` → `jarvis/config/settings.py`; `bridge/gemini_bridge.py` → `jarvis/infrastructure/assistants/gemini.py`; `bridge/vento_bridge.py` → `jarvis/infrastructure/assistants/vento.py`; `prompts/system.md` → `prompts/system.md`; los tests están en `tests/unit/`. Los módulos nuevos que se creen deben respetar las capas descritas en `docs/CONTEXTO_DEL_PROYECTO.md` («Arquitectura por capas»).

**Estado:** sustituido como camino principal por [knowledge_graph_memory_plan.md](knowledge_graph_memory_plan.md) (memoria en grafo SQLite con visualización web en tiempo real); su exportación a Obsidian queda como fase opcional de ese plan  
**Fecha de preparación:** 2026-10-13  
**Alcance:** memoria duradera consultable en Jarvis, visualizable con Obsidian en el ordenador y sincronizada mediante un repositorio privado de GitHub.

## 1. Objetivo

Permitir que Jarvis convierta el resumen acumulativo que ya produce en notas Markdown locales, busque las notas pertinentes cuando el usuario pregunte algo relacionado y sincronice únicamente esas notas con GitHub. Obsidian se ejecutará en el ordenador del usuario; la Raspberry Pi solo leerá y escribirá archivos de texto y ejecutará Git.

El resultado debe funcionar sin red: Jarvis seguirá contestando con la memoria local disponible, guardará las notas localmente y reintentará la sincronización después. La memoria conversacional JSONL actual seguirá siendo el registro acotado de intercambios recientes y conservará su formato y sus copias de seguridad.

## 2. Decisiones de diseño

1. **Repositorio privado separado para la bóveda.** No automatizar commits ni pushes desde el repositorio de código Jarvis. La bóveda se clona por separado en el PC y en la Raspberry Pi. Obsidian abre la copia local del PC.
2. **Sin Obsidian en la Raspberry Pi.** El agente solo depende de archivos Markdown y Git. No se instalarán plugins, una interfaz gráfica ni una base de datos de grafos en la placa.
3. **Reutilizar el resumen existente.** `ConversationMemory` ya genera un resumen acumulativo con temas independientes separados por `||`. Tras una compactación correcta se exportarán esos temas como notas, sin una llamada adicional al modelo por cada intercambio.
4. **Separar historial y conocimiento.** `state/conversation.jsonl` continúa guardando intercambios recientes y su resumen de respaldo. La bóveda conserva las notas visibles, enlazadas y buscables. Cuando la búsqueda encuentra notas pertinentes, Gemini recibe esas notas y la ventana reciente, no el resumen temático completo; si no hay coincidencias, se mantiene el comportamiento actual como fallback.
5. **Recuperación local y determinista en la primera versión.** Buscar términos en títulos y contenido, ponderar coincidencias en títulos y seguir enlaces internos un nivel. No añadir embeddings, Kùzu, NetworkX, Pyvis ni dependencias de Python en esta entrega.
6. **Git nunca es requisito para responder.** Las operaciones de red se hacen en un worker serial, fuera del turno de voz. Los errores se registran sin borrar notas ni bloquear la conversación.
7. **Sin sobrescrituras destructivas.** No usar `git push --force`, `git reset`, `git clean`, `git checkout` para descartar cambios, ni resolver conflictos eligiendo automáticamente una versión.

## 3. Estado actual del proyecto

- `jarvis/config/settings.py` define `CONVERSATION_MEMORY_PATH`, el límite de tamaño y los umbrales de compactación.
- `jarvis/application/memory/conversation_memory.py` contiene `MemoryBackend`, `JsonlMemoryBackend` y `ConversationMemory`; escribe JSONL de forma durable, guarda backup y compacta en segundo plano.
- `main.py` crea `ConversationMemory` y lo inyecta en `ConversationOrchestrator`.
- `jarvis/application/conversation/turn_handler.py` usa la memoria persistida para Gemini y registra los intercambios completados. `GeminiBridge` interpreta los elementos con rol `summary` como instrucción de sistema.
- `tests/unit/application/memory/test_conversation_memory.py` cubre persistencia, compactación, backup y contexto. Las pruebas del orquestador y del payload de Gemini están en otros archivos de `tests/`.
- `.gitignore` actualmente solo ignora bytecode y `__pycache__`; no protege los archivos de estado del repo de Jarvis.
- En el momento de preparar este plan, `state/conversation.jsonl`, `state/conversation.jsonl.bak` y `state/rainwater_tank_state.json` aparecen modificados. Los dos archivos de conversación están versionados. **No modificar, revertir ni incluir esos cambios en commits del feature.** Antes de cualquier trabajo de implementación se deben conservar y revisar esos cambios locales.

## 4. Arquitectura objetivo

```text
Turno de voz
  -> buscar notas locales relevantes
  -> Gemini recibe notas encontradas + últimos intercambios
  -> registrar el intercambio en el JSONL actual

Compactación de ConversationMemory
  -> resumen acumulativo ya existente
  -> exportación local idempotente: un archivo Markdown por tema
  -> worker Git serial: fetch/fast-forward seguro, commit limitado, push

Ordenador
  -> clonar el mismo repositorio privado
  -> abrir la carpeta del clon con Obsidian
  -> editar notas y enlaces; Git sincroniza los cambios con la Raspberry Pi
```

Flujo de sincronización recomendado:

1. En el arranque, si el árbol de trabajo de la bóveda está limpio, hacer `git fetch` y avanzar solo con `git merge --ff-only`. Si no se puede avanzar de forma segura, conservar el estado local y continuar Jarvis offline.
2. Cuando cambien notas producidas por Jarvis, agrupar la tarea en la cola del worker y esperar una ventana breve de debounce configurable, para no generar un push por cada escritura intermedia.
3. Antes de preparar el commit, comprobar que el clon pertenece al repositorio de memoria configurado, que la rama permitida es la esperada y que no hay cambios staged ajenos. Añadir explícitamente solo el subdirectorio administrado por Jarvis.
4. Crear un commit solo si hay cambios nuevos en ese subdirectorio; hacer push al remoto y a la rama configurados explícitamente.
5. Si el push es rechazado porque el remoto avanzó, hacer fetch e intentar únicamente una integración fast-forward cuando la rama local lo permita. Si diverge o hay conflictos, no forzar ni elegir una versión: conservar los commits locales, registrar el estado y requerir intervención/reintento controlado.
6. Los cambios manuales editados en Obsidian llegan a la Raspberry Pi mediante sincronización periódica de fetch más fast-forward cuando la copia local está limpia. Nunca ejecutar pull sobre cambios locales no confirmados.

El único writer automatizado de notas será Jarvis dentro de su carpeta administrada. Las notas editables manualmente desde Obsidian se mantendrán en otra carpeta. Esto reduce las colisiones entre escrituras del programa y cambios humanos.

## 5. Repositorio de memoria y formato de archivos

Crear un repositorio privado nuevo, por ejemplo `jarvis-memory-vault`, distinto del repositorio de código. La URL concreta se configura en cada clon mediante Git; no se guarda en el código ni en un archivo versionado si contiene credenciales.

Estructura inicial sugerida:

```text
jarvis-memory-vault/
├── .gitignore
├── Jarvis/                 # Única carpeta que Jarvis puede crear o actualizar
│   ├── README.md
│   ├── preferencias/
│   ├── personas/
│   ├── proyectos/
│   ├── decisiones/
│   └── pendientes/
└── Manual/                 # Notas que el usuario gestiona desde Obsidian
```

Cada tema obtiene una ruta estable calculada a partir de un identificador/slug normalizado, de manera que volver a exportar el resumen actualice la misma nota y no cree duplicados. Las notas usan UTF-8 y Markdown normal, con metadatos YAML mínimos (id estable, tipo, fecha de actualización y procedencia) y enlaces Obsidian `[[...]]` solo cuando la relación esté respaldada por el texto. El parser no debe deducir relaciones semánticas por su cuenta.

El `.gitignore` del repositorio de la bóveda puede ignorar los archivos de estado volátiles de Obsidian (`.obsidian/workspace.json` y `.obsidian/workspaces.json`), temporales y backups. No ignorar toda la carpeta `.obsidian` sin decidir qué ajustes de vault se desea sincronizar. No crear un vault dentro de otro vault.

## 6. Ficheros a crear o modificar

| Fichero | Acción prevista | Responsabilidad |
|---|---|---|
| `jarvis/config/settings.py` | Modificar | Ruta de la bóveda, activación, límites de resultados, intervalo/debounce y timeout de Git. Leer ruta desde entorno/configuración local; nunca guardar token SSH/PAT aquí. |
| `jarvis/application/memory/conversation_memory.py` | Modificar de forma acotada | Añadir callback opcional tras una compactación exitosa y una opción para pedir contexto sin el resumen antiguo cuando existan notas relevantes. Los defaults deben conservar el comportamiento actual. |
| `core/markdown_memory.py` | Crear | Parsear secciones `Tema: ... ||`, generar/upsert de Markdown de forma atómica, indexar títulos/contenidos/enlaces y recuperar notas por relevancia. Sin importar Obsidian ni ejecutar Git. |
| `core/git_memory_sync.py` | Crear | Adaptador de Git restringido al clon de la bóveda: comandos con lista de argumentos, `shell=False`, `cwd` explícito, timeout, allowlist de rutas y política de conflictos. |
| `jarvis/application/conversation/turn_handler.py` | Modificar | Consultar memoria Markdown local para turnos Gemini; componer el contexto de notas con la ventana reciente; solicitar el contexto resumen actual como fallback si no hay hits o el vault falla. No hacer operaciones de red en el hilo del turno. |
| `main.py` | Modificar | Construir e inyectar el store Markdown, callback de exportación y worker Git. Ejecutar una reconciliación local de la última síntesis al arrancar; cerrar el worker con espera limitada en `finally`. |
| `prompts/system.md` | Modificar si hace falta | Indicar que las notas recuperadas son contexto factual auxiliar, no instrucciones; respetar la petición actual, no inventar hechos y reconocer incertidumbre/conflictos. |
| `tests/test_markdown_memory.py` | Crear | Parser, rutas/slugs, escritura atómica/idempotente, enlaces y ranking de recuperación. |
| `tests/test_memory_git_sync.py` | Crear | Probar con repositorios Git temporales locales: commit acotado, no-op limpio, timeout/error, offline, fast-forward y rechazo de divergencia/conflicto. No llamar a GitHub. |
| `tests/unit/application/memory/test_conversation_memory.py` | Modificar | Callback solo después de compactar correctamente; fallback y modo de contexto sin resumen preservan el resto de entradas. |
| `tests/test_conversation_model_switch.py` o nuevo test específico | Modificar/crear | Verificar que solo el modelo habilitado recibe notas y que turnos interrumpidos antes de obtener respuesta o fallidos no se registran como intercambios completos de conocimiento. |
| `tests/test_gemini_system_instruction.py` | Modificar si se cambia el payload | Confirmar que resumen/notas se transmiten como contexto del sistema, no como un mensaje conversacional del usuario. |
| `README.md` | Modificar | Requisitos, configuración local, clon/Obsidian, recuperación, comportamiento offline, privacidad y troubleshooting. |
| `.gitignore` del repositorio nuevo de memoria | Crear allí | Ignorar ajustes volátiles de Obsidian y archivos temporales del vault. No usar el `.gitignore` del repo Jarvis para automatizar el commit de memoria. |

No se prevén nuevas dependencias de Python. Se requiere Git instalado en la Raspberry Pi y en el ordenador, acceso SSH configurado a la bóveda privada y Obsidian instalado únicamente en el ordenador.

## 7. Implementación paso a paso

### Fase 0: proteger el estado y preparar el repositorio

- [ ] Guardar una copia recuperable de los archivos modificados detectados, sin reemplazarlos ni alterar el árbol de trabajo.
- [ ] Revisar por separado qué contenido de `state/conversation.jsonl` está versionado y si debe permanecer en el repositorio de código. No incluir esta limpieza de historial en el feature ni hacer reescritura de historial sin una decisión explícita.
- [ ] Crear en GitHub un repositorio **privado** dedicado a la bóveda y restringir colaboradores/permisos.
- [ ] En el PC y la Raspberry Pi, comprobar `git --version` y configurar acceso SSH de mínimo privilegio. Verificar `ssh -T git@github.com` sin poner claves/tokens en el repositorio.
- [ ] Clonar el repositorio en una carpeta propia en ambos equipos. Abrir el clon del PC con Obsidian como vault local.
- [ ] Crear estructura `Jarvis/` y `Manual/`, README inicial y `.gitignore`; hacer el commit inicial de forma manual.

**Salida de la fase:** la misma bóveda se abre con Obsidian en el PC y se clona en la Raspberry Pi; no se ha cambiado ni sincronizado el repositorio de código.

### Fase 1: exportación local del resumen

- [ ] Implementar en `core/markdown_memory.py` el parser del formato acumulativo actual (`||` separa temas; `Tema:` precede al contenido). Validar entradas vacías, temas repetidos, caracteres de ruta y respuestas incompletas sin borrar notas existentes.
- [ ] Definir el identificador estable y slug de nota; normalizar Unicode/acentos para búsqueda, pero conservar tildes y texto original en Markdown.
- [ ] Upsert atómico: escribir un temporal en el mismo directorio y sustituir el archivo; evitar archivos parciales si se interrumpe la Raspberry Pi.
- [ ] Registrar un checksum local de la última síntesis exportada o usar comparación de contenido para que reexportar al arrancar sea idempotente.
- [ ] Añadir el callback opcional a `ConversationMemory.compact()`. Invocarlo solo después de guardar correctamente la compactación y fuera de la sección crítica/bloqueo del JSONL.
- [ ] Al iniciar, leer la última entrada `summary` del JSONL y reconciliarla con `Jarvis/`. Así se recupera el caso en que el proceso terminara entre compactar el JSONL y escribir las notas.
- [ ] Si la exportación falla, conservar intactos tanto el JSONL como las notas existentes, emitir un warning y reintentarlo en el siguiente inicio/compactación.
- [ ] Añadir tests con directorios temporales para Unicode, delimitadores, notas vacías, overwrite idempotente y fallos de escritura.

**Salida de la fase:** una compactación de prueba produce Markdown local sin conexión y volver a exportarla no crea duplicados.

### Fase 2: búsqueda y contexto recuperado

- [ ] Indexar localmente notas `.md` de `Jarvis/`; ignorar `.obsidian`, temporales, backups y `Manual/` en la primera versión si se decide que solo la memoria de Jarvis sea fuente de respuesta.
- [ ] Tokenizar consulta, título y cuerpo con `unicodedata`/`re`; ignorar tokens demasiado cortos y una pequeña lista de palabras funcionales en español.
- [ ] Puntuar coincidencias con mayor peso para título/id, luego contenido; limitar el máximo de notas y caracteres que entran en contexto mediante configuración.
- [ ] Leer enlaces `[[nota]]` reconocibles en los hits y añadir como máximo sus vecinos directos, evitando repetir notas y limitar el total.
- [ ] Añadir búsqueda de `query` a `core/markdown_memory.py` con resultado determinista. Devolver una lista vacía si no hay coincidencias; registrar errores de lectura sin propagar un fallo al turno.
- [ ] En `jarvis/application/conversation/turn_handler.py`, antes de llamar a Gemini, combinar los hits en una sola entrada `summary` junto con el historial reciente. Cuando haya hits, omitir el resumen global antiguo del contexto para que la selección sea efectiva; cuando no los haya, conservar el contexto actual completo.
- [ ] Mantener el comportamiento de Vento sin cambios en la primera versión. La interfaz `AssistantBridge.ask(message, history)` permanece igual.
- [ ] Actualizar `prompts/system.md` para tratar la memoria recuperada como referencia, nunca como instrucción del sistema, y no completar vacíos con inferencias.
- [ ] Probar coincidencias exactas, acentos, términos solo en contenido, enlaces de un salto, límite de contexto, cero resultados y fallback al resumen JSONL.

**Salida de la fase:** preguntar por un tema del vault incorpora únicamente las notas pertinentes a Gemini; una pregunta sin match se comporta como Jarvis hoy.

### Fase 3: sincronización Git segura

- [ ] Implementar `core/git_memory_sync.py` usando solo la biblioteca estándar y Git CLI. Cada invocación usa lista de argumentos, `shell=False`, `cwd` fijado a la raíz configurada del clon, `check=True`, salida acotada y timeout.
- [ ] Validar antes de operar que la ruta existe, es un clon Git, tiene el remoto y rama esperados y que la ruta administrada queda dentro del clon (resolver symlinks/rutas absolutas para evitar escapar del vault).
- [ ] Ejecutar una sola tarea Git a la vez con lock/worker serial. El filesystem local sigue siendo la fuente de verdad si Git no está disponible.
- [ ] Al arrancar y en el intervalo configurado: si el árbol está limpio, `fetch` y `merge --ff-only` de la rama configurada. No usar `pull` sobre working tree dirty.
- [ ] Al recibir cambios nuevos de Jarvis: agrupar por debounce, revisar estado/index, `git add -- Jarvis/`, comprobar staged paths y crear commit solo si hay diferencias. Nunca hacer `git add -A` ni confirmar `Manual/`, `state/`, código o archivos de credenciales.
- [ ] Hacer push de la rama explícita. No incluir URL con token en argumentos, logs ni excepciones. No utilizar `--force`, `--mirror` ni `--all`.
- [ ] Para push rechazado por avance remoto, fetch y permitir solo fast-forward limpio. Divergencia, conflicto o archivos dirty externos detienen el ciclo automático y conservan los datos para intervención; el worker reintenta más tarde con backoff limitado.
- [ ] Añadir modo `enabled=false` y modo dry-run/log para despliegue inicial. El error de autenticación/red no debe impedir arranque ni respuesta de Jarvis.
- [ ] Pruebas con repositorio bare/local temporal para casos OK, no-op, remoto adelantado, no-fast-forward, conflicto, directorio inválido, executable ausente y timeout. No hacer pruebas contra credenciales reales.

**Salida de la fase:** commits automáticos posibles solo en el repositorio de memoria y dentro de `Jarvis/`; las divergencias no pierden datos ni afectan la voz.

### Fase 4: configuración, inyección y ciclo de vida

- [ ] Añadir en `jarvis/config/settings.py` opciones tipadas con defaults conservadores: ruta de clon (por ejemplo desde `JARVIS_MEMORY_VAULT_PATH`), enable/disable, rama/remoto, número máximo de notas y caracteres de contexto, debounce, intervalo de fetch, timeout y backoff.
- [ ] Validar configuración al iniciar: si la función está deshabilitada o el clon no existe, mantener el funcionamiento actual y avisar una sola vez; no clonar ni crear repositorio automáticamente desde Jarvis.
- [ ] En `main.py`, construir `MarkdownMemory` y `GitMemorySync` separados y pasarlos como dependencias. Mantener `JsonlMemoryBackend` y el `ConversationMemory` existentes.
- [ ] Iniciar worker después de validar paths; reconciliar la última síntesis de JSONL local primero. Programar primer fetch solo si el repo está limpio.
- [ ] En el bloque `finally`, parar el worker y esperar un tiempo acotado; si hay tareas pendientes, las notas locales quedan y se volverán a sincronizar en el próximo arranque.
- [ ] No exponer credenciales Git en `jarvis/config/settings.py`, `state/bridge.env`, logs o documentación. Autenticación mediante agente/clave SSH del usuario de servicio y `known_hosts` verificado.

**Salida de la fase:** configuración incompleta/offline degrada a memoria local y la aplicación puede arrancar normalmente.

### Fase 5: documentación y despliegue progresivo

- [ ] Documentar en `README.md` la instalación de Git, creación del repo privado, SSH, clon en ambos dispositivos, apertura de vault en Obsidian, rutas y diagnóstico.
- [ ] Probar primero con un vault temporal de prueba y `MEMORY_GIT_SYNC_ENABLED=false` para validar notas y retrieval.
- [ ] Habilitar Git en una rama de pruebas o repo de prueba; crear una nota, observar commit/push y verificar que aparece en el PC.
- [ ] Editar una nota `Manual/` desde Obsidian, sincronizarla y verificar que llega a la Raspberry Pi sin que Jarvis la confirme.
- [ ] Probar sin red, con push rechazado y con conflicto real entre clones. Comprobar que no se bloquean consultas y no se pierde ninguna versión.
- [ ] Activar el repo privado de producción solo después de validar allowlist de rutas e inspeccionar el diff/staging.
- [ ] Revisar el uso de RAM/CPU, latencia del worker, frecuencia de commits y tamaño de la bóveda en la Raspberry Pi durante varios días antes de ajustar intervalos.

**Salida de la fase:** despliegue reversible y verificable, sin dependencia de Obsidian en la placa ni impacto en la selección del modelo.

## 8. Especificación de pruebas y comandos

La implementación debe conservar la suite existente y añadir pruebas unitarias sin red. Comandos previstos desde la raíz del proyecto:

```powershell
python -m unittest tests.test_conversation_memory
python -m unittest tests.test_markdown_memory
python -m unittest tests.test_memory_git_sync
python -m unittest discover -s tests
```

Si los tests no son importables como módulo por la configuración del entorno, usar `python -m unittest discover -s tests -p "test_conversation_memory.py"` para las pruebas focalizadas.

Matriz mínima de aceptación:

| Caso | Resultado requerido |
|---|---|
| Resumen con dos temas | Dos notas Markdown estables, UTF-8 y sin pérdida de tildes. |
| Mismo resumen exportado otra vez | Sin notas duplicadas ni diff adicional. |
| Resumen vacío/malformado | No elimina ni trunca notas existentes; se registra advertencia. |
| Búsqueda con acentos | Encuentra contenido con/sin tilde y ordena título antes que coincidencia débil en cuerpo. |
| Enlace `[[...]]` | Añade solo vecinos directos, deduplicados y dentro del límite de contexto. |
| Hit de memoria | Gemini recibe notas encontradas + intercambios recientes; no recibe el resumen global redundante. |
| Sin hit/vault deshabilitado | El prompt conserva la memoria JSONL y el comportamiento anterior. |
| Vento activo | Su historial y payload no cambian en esta versión. |
| Compactación fallida | No hay exportación destructiva; queda el JSONL original. |
| Sin conexión GitHub | Jarvis arranca, escribe localmente y responde; error con reintento posterior. |
| Push no-fast-forward/conflicto | No hay force push ni resolución automática; los datos locales siguen presentes. |
| Aislamiento Git | `git status` del repo de código no recibe archivos de la bóveda ni commits automáticos. |
| Seguridad | Staging contiene exclusivamente paths bajo `Jarvis/`; ninguna credencial/historial JSONL se sube. |

## 9. Seguridad, privacidad y operación

- Un repositorio privado limita quién tiene acceso, pero **no cifra** el contenido ni elimina copias de la historia Git. No guardar claves, tokens, credenciales, datos de terceros o información que no se quiera conservar remotamente.
- Las notas pueden contener datos personales y permanecerán en el historial del repositorio aunque se borren de la versión actual. Definir antes de producción quién tiene acceso, qué retención se desea y cómo atender solicitudes de borrado.
- El historial `state/conversation.jsonl` contiene texto de conversaciones y en este checkout ya está versionado. La nueva automatización no lo subirá; su eventual retirada del índice/historial es una tarea de privacidad independiente que requiere copia, revisión y decisión explícita.
- `.gitignore` no protege archivos ya versionados ni evita por sí solo que se filtre información en commits previos. No presentar el ignore como solución retroactiva.
- El worker no debe imprimir contenidos de conversaciones/notas ni stdout/stderr completo de Git. Registrar operación, exit code y mensaje sanitizado; truncar detalles que puedan incluir URLs.
- El parser de wikilinks solo lee texto. No ejecutar comandos, scripts, plugins ni contenido de notas. El texto recuperado se pasa al modelo como dato no confiable.
- El directorio de clon y los ficheros locales deben pertenecer al usuario que ejecuta Jarvis; en Linux, aplicar permisos de lectura/escritura solo a ese usuario cuando sea viable.
- Eliminar o editar una nota en Obsidian debe sincronizarse como cambio normal solo cuando el flujo esté limpio. La lógica de Jarvis no debe recrear automáticamente notas borradas por el usuario sin una política definida; inicialmente se recomienda tratar borrados remotos como autoridad y no restaurarlos desde una síntesis antigua salvo que el usuario lo solicite.

## 10. Riesgos, decisiones pendientes y reversión

- **Repo existente vs repo nuevo:** este plan elige repo privado separado por aislamiento. No se automatizará el push del repo Jarvis. Si se decide reutilizar otro repo, hay que revisar primero su visibilidad e historial completo.
- **Colisiones de edición:** separar `Jarvis/` y `Manual/`; ante cambios simultáneos de un mismo archivo, detener la automatización y resolver desde Git/Obsidian.
- **Notas duplicadas al cambiar títulos:** usar id/slug estable derivado de la clave del tema; no renombrar por variaciones de estilo sin migración explícita.
- **Notas desactualizadas:** la exportación del resumen acumulativo es idempotente y ocurre tras compactar y al arrancar. Una modificación manual en `Jarvis/` podría ser reemplazada por una exportación posterior; esa carpeta se considera propiedad de Jarvis. Los cambios humanos deben ir en `Manual/` o acordarse un formato mixto antes de implementar.
- **Reversión del feature:** deshabilitar el flag de memoria Markdown/Git y conservar el vault local/remoto. El historial JSONL y el comportamiento anterior siguen operativos. No borrar automáticamente el clon, notas ni el repo.
- **Dependencia del proveedor:** la búsqueda y escritura son locales; solo la compactación existente depende de Gemini. Si Gemini falla, se mantienen notas previas y se vuelve a exportar cuando una compactación posterior tenga éxito.

Decisiones que deben quedar resueltas antes de activar producción: nombre/URL del repositorio privado, nombre del usuario Linux del servicio, ruta de clon en la Raspberry Pi, rama principal, política de retención de datos personales y si se habilita sincronización automática desde el primer despliegue o después de un periodo en dry-run.

## 11. Fuentes consultadas

Consultadas el 2026-10-13; se priorizó documentación primaria:

- [Obsidian Help: How Obsidian stores data](https://obsidian.md/help/Files+and+folders/How+Obsidian+stores+data): vault como carpeta local, notas de texto plano, cambios externos, configuración `.obsidian` y recomendación sobre archivos de workspace al usar Git.
- [Git: git-pull](https://git-scm.com/docs/git-pull): `pull` combina fetch e integración; `--ff-only` falla si hay divergencia y los conflictos requieren manejo.
- [Git: git-fetch](https://git-scm.com/docs/git-fetch): descargar referencias sin integrar el árbol de trabajo.
- [Git: git-push](https://git-scm.com/docs/git-push): actualización fast-forward por defecto y riesgos de `--force`.
- [GitHub Docs: About repositories](https://docs.github.com/en/repositories/creating-and-managing-repositories/about-repositories): repositorios públicos/privados y controles de acceso.
- [GitHub Docs: About secret scanning](https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning): las credenciales comprometidas deben revocarse/rotarse; borrar el archivo del último commit no quita el secreto del historial.
- [Python: subprocess](https://docs.python.org/3/library/subprocess.html): preferir `subprocess.run`, secuencia de argumentos, `shell=False`, `check` y `timeout`.
