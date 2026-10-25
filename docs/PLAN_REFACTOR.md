# Plan de refactor y reestructuración de Jarvis

> **Estado:** pendiente de ejecución (preparado el 2026-10-25).
> Quien ejecute este plan debe marcar aquí cada fase como completada al terminarla.

## Entorno de ejecución (restricción obligatoria)

> **Jarvis se ejecuta en Raspberry Pi OS (Linux, ARM64), no en Windows.** Los tests y el desarrollo
> se hacen en el PC Windows del propietario (VS Code). **En la Raspberry no se lanzan tests**: solo
> se arranca la aplicación. Quien ejecute este plan debe tenerlo siempre en cuenta:
>
> - **Linux distingue mayúsculas y minúsculas en rutas y en `import`.** Un nombre que funciona
>   en Windows puede fallar en la Raspberry. Por eso todos los paquetes nuevos van en minúsculas
>   (`jarvis/`, `jarvis/infrastructure/`…) y los imports deben coincidir exactamente con el nombre
>   real del fichero o carpeta. El error `No module named 'Arduino'` existe por esto: la carpeta es `ARDUINO/`.
> - **Rutas siempre POSIX** (`/`), nunca `\`. Usar `pathlib.Path` y no concatenar cadenas.
> - **Rutas de sistema solo en Linux:** `/run/user/<uid>` (sockets y lock), `/dev/ttyACM0`, `plughw:…`
>   (ALSA), `aplay`, `sudo -n /usr/sbin/poweroff`, `fcntl`. Los tests no deben depender de ellas
>   (ver regla 5 de §3); las que sí dependen se marcan con `skipUnless` de Linux.
> - **Los tests se ejecutan solo en Windows (VS Code).** Como Windows no distingue mayúsculas, un
>   import mal escrito pasa los tests pero falla en la Raspberry. Por eso existe la prueba de nombres
>   exactos (Fase 2, punto 7), que compara cada import con los ficheros reales distinguiendo mayúsculas.
> - **Mayúsculas al renombrar en Git desde Windows:** un cambio que solo cambia mayúsculas
>   (`Sensors` → `sensors`) no se detecta en un sistema de ficheros sin distinción de mayúsculas.
>   Usar `git mv -f` en dos pasos (`Sensors` → `tmp_sensors` → `sensors`) o renombrar directamente
>   el paquete nuevo en `jarvis/`; no se conservan carpetas en mayúsculas.
> - **Fin de línea y codificación:** UTF-8 y `\n`. Los ficheros de texto que lee la Raspberry
>   (`*.env`, JSON, `system.md`) no deben tener BOM.
> - **Permisos:** `os.chmod(..., 0o600)` y `0o700` tienen sentido solo en Linux; Windows los ignora.
>   No añadir lógica que dependa de ellos para pasar tests.

## Context

Jarvis (asistente de voz en Raspberry Pi + Arduino Mega) ha crecido por parches: hay
copias de seguridad versionadas, clases muertas, una clase de 280 líneas que lo hace todo
(`core/conversation.py`), otra escrita en estilo "golf" ilegible
(`Sensors/rainwater_tank_web_server.py`), lógica de dominio dentro de `main.py`, paquetes
con mayúsculas, comentarios en dos idiomas, secretos dentro de Git y documentación que ya
no coincide con el código. Además **3 tests fallan hoy** y `main.py` no puede importarse
desde este checkout (`ModuleNotFoundError: No module named 'Arduino'`, la carpeta se llama
`ARDUINO`. Windows ignora la diferencia entre mayúsculas y minúsculas, pero Linux (la Raspberry)
no, así que este fallo solo aparece en la Raspberry).

Objetivo: un único paquete `jarvis/` organizado por capas (dominio, puertos, aplicación,
infraestructura, arranque), clases pequeñas con una responsabilidad, dependencias
inyectadas por constructor (SOLID), sin código muerto ni secretos, con tests que pasen en
Windows (donde se ejecutan) y **sin cambiar el comportamiento observable** (salvo las excepciones
listadas).

Este plan está pensado para ejecutarse con un modelo más ligero: cada fase es pequeña,
autocontenida, termina con tests verdes y documentación actualizada.

### Decisiones tomadas con el propietario

| Tema | Decisión |
| --- | --- |
| Idioma | Identificadores, comentarios, docstrings y logs **en inglés**. Lo que Jarvis dice en voz alta sigue **en español** (centralizado en `jarvis/domain/phrases.py`). La documentación de `docs/` sigue en español. |
| Carpeta `ARDUINO/` | El firmware se conserva **versionado** porque sirve para flashear la placa (no tiene relación con el resto del proyecto). Se sube un nivel con `git mv`: `ARDUINO/Main program/main.cs` → `ARDUINO/main.cs`, **sin editar su contenido**. El cliente serie `ARDUINO/arduino_mega_connection.py` se **copia** a `jarvis/infrastructure/arduino/serial_connection.py` y después se **borra** (Fase 7). La carpeta `ARDUINO/__pycache__/` también se borra. |
| Profundidad | Paquete `jarvis/` por capas. `main.py` se queda en la raíz como punto de entrada para systemd. |
| Limpieza | Backups y código muerto **se borran** (quedan en el historial de Git). Secretos y estado local **se sacan de Git** y se añaden a `.gitignore`. No se reescribe el historial de Git. |

---

## 1. Diagnóstico (hallazgos del análisis)

### 1.1 Errores y riesgos reales
1. `from Arduino.arduino_mega_connection import ...` en `main.py`, `Indicators/arduino_rgb_indicator.py`, `Sensors/rainwater_tank_meter.py` y `system/arduino_button_monitor.py`, pero la carpeta es `ARDUINO/` → `main.py` no importa. El test del medidor lo esquiva inyectando módulos falsos en `sys.modules`.
2. Tests que fallan hoy:
   - `tests/test_config_settings.py`: `read_env_file` no quita comillas (`"secret-key"`).
   - `tests/test_gemini_system_instruction.py`: `system.md` no contiene «si hay duda, conserva ambos por separado».
   - `tests/test_main_gemini_config.py`: no importa (punto 1); además `build_bridge` no pasa `timeout_seconds` a `GeminiBridge`.
   - `python -m unittest discover -s tests` falla porque `tests/` no tiene `__init__.py`.
3. **Secretos versionados:** `state/bridge.env` (token del puente Vento), `.vscode/sftp.json` (contraseña SSH), `docs/instrucciones jarvis.txt` (contraseña SSH), `docs/instalar el agent ... .txt` (clave de dispositivo Vento). También `state/conversation.jsonl(.bak)` (conversaciones privadas).
4. `notifications/announcement_client.enqueue` lanza `OSError` si el servicio de avisos no corre; el medidor lo registra con traceback completo en cada aviso.

### 1.2 Código muerto / duplicado
- `backups/` entero, `main.py.before-*`, `Sensors/*.before-*`.
- `Sensors/rainwater_tank_http_server.py` (sustituido por `rainwater_tank_web_server.py`).
- `system/shutdown_button_monitor.py` (sustituido por `arduino_button_monitor.py`).
- Parámetro `interrupt_event` y retorno `bool` de `VoskSpeechRecognizer.wait_for_wake_word` (nadie lo usa; la interfaz dice `-> None`).
- `.vscode/Trer cambios desde raspberry.txt` duplica `scripts/hacer pull desde la raspberry.bat`.
- Patrón "hilo en bucle con start/close" repetido en medidor y monitor de botones.
- `config.settings.get_runtime_uid()` y `audio/player.PlaybackLock` calculan `/run/user/<uid>` cada uno a su manera.

### 1.3 Problemas de diseño (SOLID / acoplamiento)
- **`ConversationOrchestrator` (SRP):** bucle de diálogo + selección de modelo + historial + memoria + botones (2 hilos vigilantes, 5 `Event`s) + apagado de emergencia + confirmaciones + interrupción + LED. Modelos como strings mágicos `"gemini"`/`"vento"`; el bloque «¿Sí?» repetido 3 veces; `_handle_power_command` devuelve `True/False/None`; depende de la clase concreta `MicrophoneStream`.
- **`ArduinoRgbIndicator`:** indicador RGB + luz de alerta + servidor de socket Unix (3 responsabilidades) y su nombre no lo refleja.
- **`RainwaterTankMeter`:** lectura serie + cálculo + escritura de fichero + política de avisos + hilo de sondeo. Estados como strings (`"full"`, `"low"`...).
- **`main.py`:** contiene mensajes del depósito (`_TANK_STATUS_MESSAGES`) y devuelve una tupla de 6 elementos para gestionar el ciclo de vida a mano.
- **Memoria ↔ Gemini:** el "resumen" viaja como un mensaje falso con `role: "summary"` dentro del historial, y `GeminiBridge` tiene que filtrarlo. El historial es `list[dict]` sin tipo.
- **`AnnouncementService`:** depende de `AzureSpeechSynthesizer` concreto (usa `speak_with_playback_callbacks`, que no está en la interfaz) y lee `settings` global.
- Módulos de infraestructura leen `config.settings` global (`gemini_bridge`, `announcement_client`, `announcement_service`) en lugar de recibir configuración.
- Protocolo serie (`"STATE RED"`, `"BUTTON STATUS"`, `"SENSOR DISTANCE"`...) disperso en 3 ficheros.
- `config/settings.py` mezcla constantes, dataclasses de credenciales y lectura de ficheros; constantes de Gemini definidas después de las funciones.
- Paquetes con mayúsculas (`Indicators`, `Sensors`) frente a minúsculas en el resto.
- `print()` y `logging` mezclados; comentarios y logs en español e inglés.
- README explica conceptos de .NET y describe una estructura antigua; `docs/COMANDOS.md` cita `jarvis_voice_conversation.py`, que ya no existe.

### 1.4 Documentación desalineada con el código (el código manda)
`docs/CONTEXTO_DEL_PROYECTO.md` afirma cosas que el código no hace:
- No hay selección hablada «uno/dos» al arrancar: se prepara **Gemini** y se alterna con la frase «cambiar de modelo».
- Tras «Jarvis», el acuse es **«Dime»**, no «Sí señor?».
- El botón de interrumpir responde **«¿Sí?»**, no «Sí, dime», y también corta la **espera** de la respuesta del modelo, no solo la locución.
- El aviso de apagado manual es «Apagado manual accionado!, apagando sistemas. Venga, chao!».

---

## 2. Arquitectura objetivo

Regla de dependencias (de fuera hacia dentro, nunca al revés):

```
bootstrap  ──►  infrastructure  ──►  ports  ◄──  application  ──►  domain
                       └────────────────────────►  domain
```
- `domain/`: Python puro, sin I/O ni hilos. Datos, enums, reglas.
- `ports/`: interfaces (`ABC`) que la aplicación necesita.
- `application/`: casos de uso; solo importa `domain` y `ports`.
- `infrastructure/`: implementaciones concretas (Vosk, Azure, Gemini, Vento, Arduino, sockets, HTTP, ficheros).
- `bootstrap/`: único lugar que conoce clases concretas y lee la configuración (composition root).

### 2.1 Estructura de carpetas final

```
main.py                         # 3 líneas: from jarvis.bootstrap.app import run; run()
prompts/system.md               # antes system.md (prompt de sistema de Gemini)
ARDUINO/main.cs                 # firmware para flashear la placa (contenido sin cambios)
models/  state/  docs/  scripts/  tests/
jarvis/
  __init__.py
  config/
    env_file.py                 # read_env_file() (con soporte de comillas)
    credentials.py              # AzureCredentials, GeminiCredentials, VentoCredentials + load_*()
    settings.py                 # dataclasses frozen por grupo + load_settings()
  domain/
    assistant_model.py          # AssistantModel (enum GEMINI/VENTO)
    assistant_status.py         # AssistantStatus (WAITING/LISTENING/PROCESSING/SPEAKING)
    conversation.py             # Role, ChatMessage, ConversationContext, ShortTermHistory
    intents.py                  # Intent (enum), normalize_text(), classify(), is_confirmation()
    phrases.py                  # TODAS las frases habladas (español)
    tank.py                     # TankLevel, TankCalibration, TankStatus, TankAlertPolicy
    tank_phrases.py             # textos hablados del depósito (antes en main.py)
  ports/
    audio.py                    # AudioInput
    speech.py                   # SpeechRecognizer, SpeechSynthesizer, PlaybackAwareSynthesizer
    assistant.py                # AssistantBridge
    hardware.py                 # StatusIndicator, AlertLight, ButtonPanel, ButtonPress, DistanceSensor
    system.py                   # PowerController
    memory.py                   # MemoryEntry, MemoryBackend
    notifications.py            # Announcer
    tank.py                     # TankStateStore
  application/
    periodic_task.py            # PeriodicTask: hilo en bucle reutilizable (start/close)
    button_monitor.py           # ButtonMonitor (usa ButtonPanel + PeriodicTask)
    tank_monitor.py             # TankMonitor (sensor -> nivel -> store -> política de avisos)
    memory/
      conversation_memory.py    # ConversationMemory (compactación)
      summary_prompt.py         # build_summary_prompt()
    conversation/
      safe_status.py            # SafeStatusIndicator (decorador que nunca lanza)
      voice.py                  # Voice: todo lo que se dice en voz alta
      listener.py               # SentenceListener
      reply_interrupt.py        # ReplyInterruptGate
      emergency_shutdown.py     # EmergencyShutdown (botón D2)
      assistant_selector.py     # AssistantSelector
      power_commands.py         # PowerCommandHandler + PowerOutcome
      turn_handler.py           # TurnHandler (un turno pregunta/respuesta)
      orchestrator.py           # ConversationOrchestrator (solo el bucle)
  infrastructure/
    runtime.py                  # runtime_dir() -> /run/user/<uid>
    arduino/
      protocol.py               # constantes de comandos/respuestas serie
      serial_connection.py      # ArduinoSerialConnection (copia de ARDUINO/arduino_mega_connection.py, que se borra en la Fase 7)
      status_light.py           # ArduinoStatusLight(StatusIndicator)
      alert_light.py            # ArduinoAlertLight(AlertLight)
      button_panel.py           # ArduinoButtonPanel(ButtonPanel)
      distance_sensor.py        # ArduinoDistanceSensor(DistanceSensor)
    ipc/
      unix_datagram.py          # UnixDatagramServer + send_datagram()
      alert_light_server.py     # AlertLightControlServer (socket -> AlertLight)
      alert_light_client.py     # AlertLightClient(AlertLight) (antes Indicators/arduino_alert_client.py)
      announcer.py              # SocketAnnouncer(Announcer) (antes announcement_client.enqueue)
    audio/
      microphone.py             # SoundDeviceMicrophone(AudioInput)
      playback.py               # PlaybackLock(path), AplayPcmPlayer
    speech/
      vosk_recognizer.py        # VoskSpeechRecognizer
      azure_synthesizer.py      # AzureSpeechSynthesizer(PlaybackAwareSynthesizer)
    assistants/
      gemini.py                 # GeminiAssistant(AssistantBridge)
      vento.py                  # VentoAssistant(AssistantBridge)
      vento_reply_parser.py     # extracción de texto plano/JSON/SSE
    memory/jsonl_backend.py     # JsonlMemoryBackend(MemoryBackend)
    system/power_controller.py  # SudoPowerController(PowerController)
    tank/state_file.py          # JsonTankStateFile(TankStateStore)
    web/
      tank_web_server.py        # TankWebServer (reescrito legible)
      static/rainwater_tank.html
  bootstrap/
    logging_setup.py            # configure_logging()
    assistants.py               # build_assistant(), build_memory_summarizer()
    app.py                      # Application, build_application(), run()
  services/
    announcement_service.py     # proceso independiente de avisos (python -m jarvis.services.announcement_service)
  cli/
    announce.py                 # CLI --base64 (python -m jarvis.cli.announce)
notifications/                  # SOLO 2 shims deprecados (ver Fase 6) hasta actualizar la Raspberry
```

### 2.2 Tabla de migración

| Origen | Destino |
| --- | --- |
| `main.py` | `main.py` (mínimo) + `jarvis/bootstrap/app.py` + `jarvis/bootstrap/assistants.py` |
| `main._TANK_STATUS_MESSAGES`, `announce_rainwater_tank_*` | `jarvis/domain/tank_phrases.py` + `TankMonitor` |
| `config/settings.py` | `jarvis/config/{env_file,credentials,settings}.py` |
| `core/interfaces.py` | `jarvis/ports/*.py` + `jarvis/domain/assistant_status.py` |
| `core/intents.py` | `jarvis/domain/intents.py` |
| `core/conversation.py` | `jarvis/application/conversation/*.py` |
| `core/memory.py` | `ports/memory.py` (MemoryEntry, MemoryBackend) + `application/memory/*` + `infrastructure/memory/jsonl_backend.py` |
| `ARDUINO/arduino_mega_connection.py` | **copia** en `infrastructure/arduino/serial_connection.py`; el original se **borra** en la Fase 7 |
| `ARDUINO/Main program/main.cs` | `ARDUINO/main.cs` (`git mv`, sin cambios de contenido) |
| `Indicators/arduino_rgb_indicator.py` | `arduino/status_light.py` + `arduino/alert_light.py` + `ipc/alert_light_server.py` |
| `Indicators/arduino_alert_client.py` | `ipc/alert_light_client.py` |
| `Sensors/rainwater_tank_meter.py` | `domain/tank.py` + `application/tank_monitor.py` + `arduino/distance_sensor.py` + `tank/state_file.py` |
| `Sensors/rainwater_tank_web_server.py` + `webs/rainwater_tank.html` | `infrastructure/web/` |
| `system/arduino_button_monitor.py` | `application/button_monitor.py` + `arduino/button_panel.py` |
| `system/power_control.py` | `infrastructure/system/power_controller.py` |
| `audio/*`, `speech/*` | `infrastructure/audio/*`, `infrastructure/speech/*` |
| `bridge/*` | `infrastructure/assistants/*` |
| `notifications/announcement_client.py` | `ipc/announcer.py` + `cli/announce.py` |
| `notifications/announcement_service.py` | `jarvis/services/announcement_service.py` |
| `system.md` | `prompts/system.md` |
| `plans/*` | `docs/plans/*` |

---

## 3. Reglas para quien ejecute el plan

1. **Sobre `ARDUINO/`, solo estas operaciones están permitidas:**
   - Fase 1: `git mv "ARDUINO/Main program/main.cs" ARDUINO/main.cs` y eliminar la carpeta vacía `ARDUINO/Main program/`.
   - Fase 7: `git rm ARDUINO/arduino_mega_connection.py` y borrar `ARDUINO/__pycache__/` (no versionada).
   - **Nunca** editar el contenido de `ARDUINO/main.cs`: el firmware se flashea tal cual.
2. **No cambiar comportamiento observable** (frases habladas, colores/estados del LED, tiempos, umbrales, formato de ficheros en `state/`, formato HTTP de Vento y Gemini, endpoints web). Únicas excepciones permitidas:
   - `read_env_file` quita comillas simples/dobles alrededor del valor.
   - «Cambiar a Gemini.» pasa a «Cambiando a Gemini.» (coherente con «Cambiando a Vento.»).
   - `SocketAnnouncer` registra un `warning` de una línea (sin traceback) si el servicio de avisos no está escuchando.
   - Los mensajes de consola pasan a `logging` en inglés, **excepto** las líneas de transcripción `Yo: <texto>` y `Gemini: <texto>` / `Vento: <texto>`, que se mantienen idénticas.
3. Mover con `git mv` cuando sea un traslado, para conservar el historial.
4. Al terminar cada fase: `python -m unittest discover -s tests -t .` en verde, `python -m compileall -q jarvis main.py`, actualizar `docs/CONTEXTO_DEL_PROYECTO.md` (regla de `CLAUDE.md`), marcar la fase en `docs/PLAN_REFACTOR.md` y **pedir permiso al usuario** para hacer un commit de punto de control.
5. Los tests deben poder ejecutarse en Windows: ningún test puede importar `vosk`, `sounddevice`, `azure`, `serial` ni `fcntl`. La capa `application/` solo importa `domain/` y `ports/`.
6. Si algo del plan no encaja con el código real, **parar y preguntar**; no improvisar diseño.

### 3.2 Checklist de cierre de fase (obligatoria)

Quien ejecute una fase debe completar esta lista y copiarla en el **Registro de ejecución** (§7).
Una fase no se marca como completada si falta algún punto; si alguno no aplica, márcalo como «N/A» y explícalo en comentarios.

| # | Punto | Criterio de cumplimiento |
| --- | --- | --- |
| 1 | Pasos de la fase | Todos los pasos hechos, ninguno a medias. |
| 2 | Tests en Windows | `python -m unittest discover -s tests -t .` pasa. Anotar número de tests y skips. |
| 3 | Compilación | `python -m compileall -q jarvis main.py` pasa. |
| 4 | Nombres exactos | `tests/unit/test_import_case.py` pasa (desde la Fase 2). |
| 5 | Git limpio | `git status` revisado: solo cambios esperados, sin ficheros de la fase sin añadir. |
| 6 | Textos idénticos | Frases habladas y líneas de transcripción iguales (§3, regla 2). |
| 7 | Documentación | `docs/CONTEXTO_DEL_PROYECTO.md` actualizado con los cambios. |
| 8 | Comentarios | Desviaciones del plan, decisiones y riesgos anotados en §7. |
| 9 | Commit | Permiso del propietario pedido para el commit de punto de control; hash anotado en §7. |

### 3.1 Guía de estilo
- Inglés para nombres, comentarios, docstrings y logs. Frases habladas solo en `domain/phrases.py` y `domain/tank_phrases.py`.
- `from __future__ import annotations` y type hints en todas las firmas públicas.
- Dependencias **por constructor**; ningún módulo fuera de `bootstrap/` importa `jarvis.config.settings`.
- `LOGGER = logging.getLogger(__name__)`; nada de `print()` en `jarvis/` salvo el logger de transcripción (ver Fase 5).
- Docstring de una línea en cada clase pública explicando su responsabilidad; comentarios solo para el *porqué*.
- Nada de código comentado ni ficheros `.bak/.before-*`: para eso está Git.
- Líneas ≤ 100 caracteres, PEP 8, una clase = una responsabilidad.
- Interfaces con `ABC` + `@abstractmethod` (como hoy). Los fakes de tests no necesitan heredar.

---

## 4. Fases

### Fase 0 — Red de seguridad (sin mover código)
1. (Hecho) Este plan ya está guardado en `docs/PLAN_REFACTOR.md`.
2. Crear `tests/__init__.py` (vacío). Comando estándar de tests: `python -m unittest discover -s tests -t .`.
3. Arreglar los fallos actuales:
   - `config/settings.read_env_file`: si el valor empieza y termina con la misma comilla (`"` o `'`), quitarla.
   - `system.md`, sección «Memoria de largo plazo»: añadir la línea `- Si dos secciones parecen relacionadas y hay duda, no las fusiones: si hay duda, conserva ambos por separado.`
   - `test_main_gemini_config.py` se reescribirá en la Fase 6; mientras tanto marcarlo con `@unittest.skip("Rewritten in phase 6: main.py cannot import 'Arduino'")`.
4. Añadir **tests de caracterización** (fijan el comportamiento actual para detectar regresiones):
   - `tests/test_intents.py`: cada frase de apagado/reinicio/fin/cambio/confirmación, con tildes y mayúsculas.
   - `tests/test_tank_alerts.py` (usando `RainwaterTankMeter._publish` y callbacks, igual que el test existente): subida 79→80 «good», 89→90 «nearly_full», 99→100 «full»; bajada 21→20 «low», 11→10 «very_low», 5→4 «empty»; no repite sin rearmar (rearme a ±3 puntos); aviso porcentual solo con cambio ≥5 y ≥5 s (parchear `time.monotonic`); primera lectura nunca avisa.
   - `tests/test_vento_reply_parsing.py`: texto plano, JSON (`reply` str, `reply.content`, `message`, `text`), SSE con evento `completed`, SSE con `failed` → `RuntimeError`, cuerpo vacío → `RuntimeError`; y el payload enviado (`{"message", "history"}` con `history` recortado) parcheando `urllib.request.urlopen`.
   - `tests/test_conversation_flows.py` (con los fakes de `test_conversation_model_switch.py`): apagado confirmado (dice pregunta + respuesta y llama `shutdown`), apagado cancelado, reinicio, «buenas noches» → «Sistema detenido hasta nueva orden.», error del bridge → frase de error, el historial de Vento se limita a 6 mensajes.
5. Corregir `docs/CONTEXTO_DEL_PROYECTO.md` según §1.4.

**Hecho cuando:** todos los tests pasan (1 skip) y la doc describe el comportamiento real.

### Fase 1 — Limpieza y secretos
1. `git rm -r backups/`, `git rm main.py.before-* Sensors/*.before-*`, `git rm Sensors/rainwater_tank_http_server.py system/shutdown_button_monitor.py`.
2. Pasar el contenido de `.vscode/Trer cambios desde raspberry.txt` a una sección «Sincronizar con la Raspberry» de `docs/COMANDOS.md` y borrar el `.txt`.
3. Sacar de Git sin borrar del disco: `git rm --cached state/bridge.env state/conversation.jsonl state/conversation.jsonl.bak .vscode/sftp.json`.
4. `.gitignore`: añadir `/state/*` con excepciones `!/state/.gitkeep` y `!/state/*.example`, `.vscode/sftp.json`, `.venv/`, `*.tmp`.
5. Crear `state/bridge.env.example` (`BRIDGE_URL=` / `BRIDGE_TOKEN=`) y `.vscode/sftp.example.json` con `"password": "<PASSWORD>"`.
6. `docs/instrucciones jarvis.txt` → `docs/INSTRUCCIONES_JARVIS.md` (Markdown, **sin la contraseña**). En `docs/instalar el agent ... .txt` sustituir la clave por `<DEVICE_KEY>` y renombrar a `docs/INSTALAR_AGENTE_VENTO.md`.
7. `git mv plans docs/plans`.
7b. `git mv "ARDUINO/Main program/main.cs" ARDUINO/main.cs` y eliminar la carpeta vacía `ARDUINO/Main program/`. Actualizar en `docs/CONTEXTO_DEL_PROYECTO.md` los enlaces a `ARDUINO/Main%20program/main.cs` → `ARDUINO/main.cs` (líneas de «Hardware», «Botones físicos» y «Mapa de código»).
8. En `docs/CONTEXTO_DEL_PROYECTO.md` (sección de seguridad) dejar un aviso: siguen en el historial de Git → **el propietario debe rotar** el token del puente Vento, la clave del agente Vento y la contraseña SSH del usuario `jarvis`. No reescribir el historial.

### Fase 2 — Paquete `jarvis/`: config, dominio y puertos (código nuevo puro)
Crear `jarvis/` con `__init__.py` en cada subpaquete. En esta fase el código antiguo **sigue funcionando**; solo se añade código nuevo con sus tests.

1. `jarvis/config/env_file.py`: `read_env_file(path) -> dict[str, str]` (copiar + soporte de comillas).
2. `jarvis/config/credentials.py`: `AzureCredentials(key, region)`, `GeminiCredentials(api_key, model)`, `VentoCredentials(url, token)` (antes `BridgeCredentials`) y `load_azure_credentials(path)`, `load_gemini_credentials(path, default_model)`, `load_vento_credentials(path)` con los mismos mensajes de error.
3. `jarvis/config/settings.py`: dataclasses `frozen` con **los mismos valores actuales**:
   - `AudioSettings(sample_rate=16000, input_device=1, output_device="plughw:0,0", vosk_model_path)`, `azure_voice="es-ES-AlvaroNeural"`.
   - `ConversationSettings(short_term_history_messages=6)`.
   - `MemorySettings(path, max_bytes=4096, compact_after_messages=10, recent_exchanges=5, gemini_history_messages=11)`.
   - `GeminiSettings(credentials_path, default_model="gemini-2.5-flash", timeout_seconds=130, system_prompt_path=<root>/prompts/system.md)`.
   - `VentoSettings(credentials_path=<root>/state/bridge.env, timeout_seconds=130)`.
   - `ArduinoSettings(serial_port="/dev/ttyACM0", baudrate=115200, alert_light_socket_path=runtime_dir()/"jarvis-arduino-control.sock", button_poll_seconds=0.1)`.
   - `AnnouncementSettings(socket_path=runtime_dir()/"jarvis-announcer.sock", max_characters=500, max_datagram_bytes=2048, playback_lock_path=runtime_dir()/"jarvis-speech.lock")`.
   - `TankSettings(state_path, poll_interval_seconds=5.0, empty_distance_cm=80.0, full_distance_cm=9.0, min_change_percentage=5, min_alert_interval_seconds=5.0)`.
   - `WebSettings(host="0.0.0.0", port=8765)`.
   - `Settings(...)` que agrupa todo y `load_settings(base_dir: Path | None = None) -> Settings`.
   - **Cuidado:** la raíz del proyecto es ahora `Path(__file__).resolve().parents[2]`.
   - `runtime_dir()` vive en `jarvis/infrastructure/runtime.py` (`/run/user/<uid>`, uid 1000 si no hay `os.getuid`).
4. `jarvis/domain/`:
   - `assistant_status.py`: copiar `AssistantStatus`.
   - `assistant_model.py`: `class AssistantModel(Enum)` con `GEMINI`, `VENTO` y propiedades `display_name` («Gemini»/«Vento»), `uses_long_term_memory` (solo Gemini) y `other` (el modelo al que se alterna).
   - `conversation.py`: `Role(str, Enum)` USER/ASSISTANT; `ChatMessage(role, text)`; `ConversationContext(messages: tuple[ChatMessage, ...] = (), summary: str | None = None)`; `ShortTermHistory(max_messages)` con `add_exchange(user_text, reply)` y `as_context()`.
   - `intents.py`: `normalize_text` (igual), `class Intent(Enum)`: SHUTDOWN, REBOOT, END_CONVERSATION, SWITCH_MODEL, QUESTION; `classify(text) -> Intent`; `is_confirmation(text) -> bool`. Mismos conjuntos de frases.
   - `phrases.py`: constantes con todas las frases de `core/conversation.py` (`SYSTEMS_READY`, `WAKE_ACK = "Dime"`, `STANDBY`, `INTERRUPT_ACK = "¿Sí?"`, `PROCESSING_ERROR`, `CANNOT_PREPARE = "No puedo preparar {name}."`, `SWITCHED_TO = {AssistantModel.VENTO: "Cambiando a Vento.", AssistantModel.GEMINI: "Cambiando a Gemini."}`, preguntas/respuestas de apagado y reinicio, `EMERGENCY_SHUTDOWN`).
   - `tank.py`: `TankLevel(distance_cm, fill_percentage, measured_at_unix_seconds)` (mismos nombres de campo: se serializan al JSON y a la API); `TankCalibration(empty_distance_cm, full_distance_cm)` con `fill_percentage(distance_cm) -> int` (misma fórmula); `TankStatus(str, Enum)` con valores `"full"`, `"nearly_full"`, `"good"`, `"low"`, `"very_low"`, `"empty"`; `TankAlertPolicy(min_change_percentage, min_interval_seconds, on_level_change, on_status_change, clock=time.monotonic)` con método `observe(level)` = **copia literal** de la lógica `_notify`, `_notify_fill_level_change`, `_notify_status_transition`, `_rearm_statuses` (incluido que solo se marca como anunciado si el callback no lanza). Sustituir los números mágicos por constantes con nombre (`_REARM_MARGIN = 3`, umbrales).
   - `tank_phrases.py`: `level_phrase(level) -> "Deposito al {n} por ciento."` y `STATUS_PHRASES: dict[TankStatus, str]` (textos de `main.py`, idénticos).
5. `jarvis/ports/`: interfaces de §2.1. Firmas:
   - `AudioInput`: `start_capture()`, `stop_capture()`, `clear()`, `read_chunk(timeout: float | None = None) -> bytes`.
   - `SpeechRecognizer`: `wait_for_wake_word() -> None`, `listen_for_sentence() -> str`.
   - `SpeechSynthesizer`: `speak(text)`, `interrupt()` (por defecto no hace nada). `PlaybackAwareSynthesizer(SpeechSynthesizer)`: `speak_with_playback_callbacks(text, on_started, on_finished)`.
   - `AssistantBridge`: `ask(message: str, context: ConversationContext) -> str`.
   - `StatusIndicator.set_status(status)`, `AlertLight.set_alert_active(bool)`, `ButtonPress(Enum)` SHUTDOWN/INTERRUPT, `ButtonPanel.read_pending_press() -> ButtonPress | None`, `DistanceSensor.read_distance_cm() -> float | None`.
   - `PowerController.shutdown()`, `.reboot()`.
   - `MemoryEntry` (copiar de `core/memory.py`) y `MemoryBackend` (copiar).
   - `Announcer.announce(text) -> None`. `TankStateStore.save(level) -> None`.
6. Tests en `tests/unit/domain/` para `intents`, `ShortTermHistory`, `TankCalibration`, `TankAlertPolicy` (mover aquí los casos de `test_tank_alerts.py` adaptados), y `tests/unit/config/` para env_file y `load_settings` (valores por defecto y rutas relativas a la raíz).
7. **Prueba de nombres exactos** `tests/unit/test_import_case.py` (obligatoria, se ejecuta en Windows): recorre con `ast` todos los `import jarvis...` y `from jarvis... import ...` de `jarvis/`, `main.py` y `tests/`. Para cada componente del módulo comprueba que existe en disco con **exactamente** esa capitalización, usando `os.listdir` (no `os.path.exists`, porque Windows ignora mayúsculas). Así detecta en Windows lo que fallaría en la Raspberry. Debe fallar hoy con `Arduino` (carpeta real `ARDUINO`) y pasar al terminar el refactor.

### Fase 3 — Infraestructura (adaptadores)
Mover/reescribir cada adaptador para implementar su puerto y recibir su configuración por constructor. Tras cada sub-paso, actualizar los imports de los módulos antiguos que lo usaban (`grep`) para que la app antigua siga arrancando con el adaptador nuevo.

1. **Arduino** (`jarvis/infrastructure/arduino/`):
   - `protocol.py`: constantes `STATE_RED = "STATE RED"`, `STATE_GREEN`, `STATE_BREATHING`, `STATE_YELLOW`, `LIGHT_ALERT_ON`, `LIGHT_ALERT_OFF`, `BUTTON_STATUS`, `BUTTON_SHUTDOWN`, `BUTTON_INTERRUPT`, `BUTTON_IDLE`, `SENSOR_DISTANCE`, `DISTANCE_PREFIX = "DISTANCE_CM "`, `OK = "OK"`. Comentario: «Must match ARDUINO/main.cs».
   - `serial_connection.py`: copia de `ArduinoMegaConnection` renombrada `ArduinoSerialConnection` (misma lógica: lock, reconexión, espera de 2 s, `request() -> str | None`). Docstring: «Copied from the former ARDUINO/arduino_mega_connection.py.»
   - `status_light.py` `ArduinoStatusLight(StatusIndicator)`: mapa estado→comando y deduplicación del último comando (de `ArduinoRgbIndicator`).
   - `alert_light.py` `ArduinoAlertLight(AlertLight)`: `LIGHT ALERT ON/OFF` con deduplicación.
   - `button_panel.py` `ArduinoButtonPanel(ButtonPanel)`: traduce la respuesta de `BUTTON STATUS` a `ButtonPress`.
   - `distance_sensor.py` `ArduinoDistanceSensor(DistanceSensor)`: copia de `_read_distance_cm` con sus validaciones y warnings.
   - Las 4 clases dependen de un `Protocol`/ABC mínimo `SerialRequester.request(command) -> str | None` definido en `serial_connection.py`, para testearlas con un fake.
2. **IPC** (`jarvis/infrastructure/ipc/`):
   - `unix_datagram.py`: `UnixDatagramServer(path, max_bytes, handler: Callable[[bytes], None], thread_name)` con `start()`/`close()` (crea carpeta 0o700, borra socket previo, `chmod 0o600`, hilo daemon, limpia al cerrar) y `send_datagram(path, payload: bytes)`. Elimina la duplicación entre el receptor del LED y el servicio de avisos.
   - `alert_light_server.py` `AlertLightControlServer(alert_light, socket_path)`: valida `{"alert_active": bool}` igual que hoy y llama a `alert_light.set_alert_active`.
   - `alert_light_client.py` `AlertLightClient(AlertLight)`: igual que `ArduinoAlertClient`.
   - `announcer.py` `SocketAnnouncer(Announcer)`: envía `{"text": ...}`; captura `OSError` y registra un warning de una línea.
3. **Audio y voz**:
   - `audio/microphone.py` `SoundDeviceMicrophone(AudioInput)`: mover `MicrophoneStream` (mismo comportamiento de cola y descarte del más antiguo); mantener `__enter__/__exit__`.
   - `audio/playback.py`: `PlaybackLock(lock_path)` (la ruta se inyecta) y `AplayPcmPlayer` (antes `RawPcmPlayer`).
   - `speech/vosk_recognizer.py`: quitar `interrupt_event` y el `bool` de retorno; `print` → logger; depende de `AudioInput`.
   - `speech/azure_synthesizer.py`: implementa `PlaybackAwareSynthesizer`; recibe `playback_lock_path`.
4. **Asistentes**:
   - `assistants/gemini.py` `GeminiAssistant(credentials, history_limit, timeout_seconds, system_prompt: str = "")`: el **prompt se pasa como texto** (lo lee `bootstrap`). `build_request_payload(message, context)`: `contents` = últimos `history_limit` mensajes de `context.messages` + mensaje actual; `systemInstruction` = prompt + `"Memoria a largo plazo del usuario: " + context.summary` (mismo formato y separador `"\n\n"` que hoy). Endpoint, cabeceras, `temperature 0.7` y mensajes de error idénticos.
   - `assistants/vento.py` `VentoAssistant(credentials, history_limit, timeout_seconds)`: **mismo formato de red**: `POST url?token=...` con `{"message": ..., "history": [{"role": "user"|"assistant", "text": ...}, ...]}` (últimos `history_limit`). El resumen nunca se envía a Vento (como hoy).
   - `assistants/vento_reply_parser.py`: `parse_vento_reply(body, content_type) -> str` con las funciones `_extract_*` actuales.
5. **Resto**: `memory/jsonl_backend.py` (mover `JsonlMemoryBackend` tal cual), `system/power_controller.py` `SudoPowerController`, `tank/state_file.py` `JsonTankStateFile` (escritura atómica idéntica: fichero `.tmp` + `os.replace`).
6. **Web**: `web/tank_web_server.py` `TankWebServer(latest_level: Callable[[], TankLevel | None], host, port, dashboard_path)` reescrito legible (`RequestHandler` con métodos `_send_html`, `_send_json`). Respuestas **idénticas**: `/` y `/index.html` → HTML; `/api/rainwater-tank/current-level` → `200` con JSON del nivel o `200` con `{"error":"measurement_unavailable"}`; otra ruta → `404` `{"error":"not_found"}`; cabeceras `Access-Control-Allow-Origin: *` y `Cache-Control: no-store`; sin logs de peticiones. `git mv webs/rainwater_tank.html jarvis/infrastructure/web/static/`.
7. Tests (`tests/unit/infrastructure/`): mover/adaptar los de Gemini (payload, errores HTTP, prompt con `prompts/system.md`), Vento (los de Fase 0), JSONL (de `test_conversation_memory.py`), `JsonTankStateFile`, `TankWebServer` (levantar en `127.0.0.1`, puerto 0, y pedir las 3 rutas), clases Arduino con un `FakeSerial`, `AlertLightControlServer` (con `@unittest.skipUnless(hasattr(socket, "AF_UNIX"))`).

### Fase 4 — Aplicación: hilos de fondo, depósito, botones y memoria
1. `application/periodic_task.py` `PeriodicTask(name, interval_seconds, action: Callable[[], None])`: `start()` idempotente, `close(timeout)`; el bucle llama a `action` y espera con `Event.wait(interval)`; si `action` lanza, `LOGGER.exception` y sigue.
2. `application/tank_monitor.py` `TankMonitor(sensor: DistanceSensor, calibration, store: TankStateStore, alert_policy: TankAlertPolicy, poll_interval_seconds)`:
   - `poll_once()`: lee distancia → `TankLevel` → guarda `latest` (con lock) → `store.save` → loguea solo la primera lectura (`"Rainwater tank distance: %.1f cm | fill level: %d%%"`) → `alert_policy.observe(level)`.
   - `latest_level()`, `start()`, `close()` (usa `PeriodicTask`).
   - Los callbacks de la política se construyen en bootstrap: `lambda level: announcer.announce(level_phrase(level))` y `lambda level, status: announcer.announce(STATUS_PHRASES[status])`.
3. `application/button_monitor.py` `ButtonMonitor(panel: ButtonPanel, handlers: Mapping[ButtonPress, Callable[[], None]], poll_interval_seconds)`: en cada ciclo `panel.read_pending_press()`, loguea la pulsación y llama al handler (capturando excepciones). Usa `PeriodicTask`.
4. `application/memory/summary_prompt.py`: `build_summary_prompt(previous_summary: str | None, messages: Sequence[MemoryEntry]) -> str` con **el mismo texto exacto** de `_build_summary_prompt`.
5. `application/memory/conversation_memory.py` `ConversationMemory`: misma lógica de compactación, bloqueo e hilos; `get_context()` devuelve ahora `ConversationContext(messages=..., summary=...)` en lugar de dicts con `role: "summary"`. El `summarizer` sigue siendo `Callable[[str], str]`.
6. Tests: `tests/unit/application/` para `TankMonitor` (con `FakeDistanceSensor`, store en memoria), `ButtonMonitor` (llamando al método de un ciclo directamente), `PeriodicTask`, y mover `test_conversation_memory.py` adaptado (el logger esperado pasa a `jarvis.application.memory.conversation_memory`).

### Fase 5 — Aplicación: conversación (fase de mayor riesgo)
Dividir `core/conversation.py` en clases pequeñas. **Comparar línea a línea con el original** al escribir cada una.

1. `safe_status.py` `SafeStatusIndicator(StatusIndicator)`: envuelve otro indicador y registra (no relanza) excepciones. Sustituye a `_set_status`.
2. `voice.py` `Voice(synthesizer, microphone: AudioInput, status: StatusIndicator, shutting_down: threading.Event)`:
   - `say(text)`: equivale a `_speak` (no hace nada si `shutting_down`; lock de voz; estado SPEAKING; `microphone.stop_capture()`; `synthesizer.speak`; ignora excepciones si ya se está apagando).
   - `interrupt()`: `synthesizer.interrupt()` registrando errores.
   - `say_last_words(text)`: lógica de `_run_button_shutdown` para la voz (interrumpe en bucle hasta obtener el lock cada 0,05 s, vuelve a interrumpir, estado SPEAKING, habla aunque `shutting_down` esté activo).
3. `listener.py` `SentenceListener(recognizer, status)`: `listen() -> str` (estado LISTENING + transcripción `Yo: <texto>`).
   - Transcripción: logger dedicado `jarvis.transcript`, configurado en `bootstrap/logging_setup.py` con formato `%(message)s` a `stdout`, para que las líneas sigan siendo exactamente `Yo: ...` / `Gemini: ...` en `jarvis-voice.log`.
4. `reply_interrupt.py` `ReplyInterruptGate(voice, shutting_down)` — reemplaza los 3 `Event`s `_model_reply_*` y el hilo vigilante:
   - `begin()` (abre ciclo y limpia petición), `end()`, `request()` (llamado por el botón: ignora si se está apagando o no hay ciclo abierto; marca petición; si se está locutando la respuesta → `voice.interrupt()`), `is_requested`, `speaking()` (context manager que marca la locución en curso).
5. `emergency_shutdown.py` `EmergencyShutdown(voice, microphone, power_controller, shutting_down)`: `trigger()` idempotente que lanza un hilo daemon `emergency-shutdown`: activa `shutting_down`, `microphone.stop_capture()`, `voice.say_last_words(EMERGENCY_SHUTDOWN)`, `power_controller.shutdown()` (registrando errores). Sustituye al `Event` del botón y su hilo vigilante.
6. `assistant_selector.py` `AssistantSelector(factory: Callable[[AssistantModel], AssistantBridge], voice)`:
   - `start(model)`: fija el modelo **aunque falle la creación** (como hoy) y, si falla, dice `CANNOT_PREPARE`.
   - `switch()`: crea el otro; si falla dice `CANNOT_PREPARE` y no cambia; si va bien cambia y dice `SWITCHED_TO[model]`. (El `microphone.clear()` posterior lo hace el orquestador.)
   - Propiedades `model` y `bridge`.
7. `power_commands.py` `PowerOutcome(Enum)`: `NOT_HANDLED`, `EXECUTED`, `CANCELLED`. `PowerCommandHandler(voice, listener, power_controller)` con `handle(intent) -> PowerOutcome` (tabla interna intent → pregunta/confirmado/cancelado/acción).
8. `turn_handler.py` `TurnHandler(selector, memory: ConversationMemory | None, voice, gate, microphone, status, shutting_down)`:
   - `handle(command, history: ShortTermHistory)` reproduce `_handle_turn` exactamente: estado PROCESSING; error si no hay bridge; `gate.begin()`; contexto = `memory.get_context()` si `model.uses_long_term_memory` y hay memoria, si no `history.as_context()`; petición interrumpible; si se interrumpió → `gate.end()`, `INTERRUPT_ACK`, `microphone.clear()`; transcripción `<Modelo>: <respuesta>`; `history.add_exchange`; `memory.record_exchange`; locución dentro de `gate.speaking()`; si se interrumpió → `INTERRUPT_ACK`; `microphone.clear()`; `finally: gate.end()`; cualquier excepción → `PROCESSING_ERROR` + `microphone.clear()`.
   - `_ask_interruptibly(bridge, command, context)`: hilo daemon `assistant-model-request` + cola, sondeo cada 0,05 s, devuelve `None` si `gate.is_requested` o `shutting_down`.
9. `orchestrator.py` `ConversationOrchestrator(voice, recognizer, listener, selector, turn_handler, power_commands, microphone, status, history_size)`:
   - `run_forever()`: `SYSTEMS_READY`, `selector.start(AssistantModel.GEMINI)`, bucle WAITING → log «Waiting for wake word» → `wait_for_wake_word()` → `_run_conversation()` (excepciones: log + `microphone.clear()`).
   - `_run_conversation()`: `WAKE_ACK`; crear `ShortTermHistory(history_size)`; bucle `listener.listen()` → `match classify(command)`: power (EXECUTED → return, CANCELLED → continue), SWITCH_MODEL (`selector.switch()` + `microphone.clear()` si cambió), END_CONVERSATION (`STANDBY` y return), QUESTION → `turn_handler.handle`.
   - Nota: el orden actual comprueba primero apagado/reinicio, luego cambio de modelo, luego fin; mantenerlo.
10. Tests `tests/unit/application/conversation/`: un fichero por clase + migrar **todas** las aserciones de `test_conversation_model_switch.py` y `test_conversation_flows.py` (Fase 0) a la nueva API pública (sin tocar atributos privados). Fakes compartidos en `tests/fakes.py`. Las líneas de transcripción se comprueban con `assertLogs("jarvis.transcript")`.

### Fase 6 — Arranque, servicio de avisos y entrada
1. `bootstrap/logging_setup.py` `configure_logging()`: `basicConfig(stream=sys.stdout, level=INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")` + logger `jarvis.transcript` con formato `%(message)s` y `propagate=False`.
2. `bootstrap/assistants.py` (solo importa stdlib + gemini/vento, testeable en Windows):
   - `build_assistant(model, settings) -> AssistantBridge`: Gemini con `history_limit=memory.gemini_history_messages` (11), `timeout_seconds` de settings y prompt leído de `prompts/system.md` (vacío si no existe); Vento con `history_limit=conversation.short_term_history_messages` (6).
   - `build_memory_summarizer(settings) -> Callable[[str], str]`: Gemini sin prompt de sistema, `history_limit=1`, mismo modelo y timeout; llama `ask(prompt, ConversationContext())`.
3. `bootstrap/app.py`:
   - `class Application`: recibe orquestador, micrófono y una lista de componentes con `start()`/`close()`; `run()` arranca componentes en orden, entra en `with microphone: orchestrator.run_forever()` y en `finally` los cierra en orden inverso.
   - `build_application(settings) -> Application`: mismo orden de construcción y arranque que el `main.py` actual (credenciales Azure → micrófono → Vosk → Azure → power → serial `connect()` → luces → `AlertLightControlServer` → `EmergencyShutdown`/`ReplyInterruptGate` → `ButtonMonitor` con handlers `{SHUTDOWN: emergency.trigger, INTERRUPT: gate.request}` → `TankMonitor` → `TankWebServer` → `ConversationMemory` → orquestador).
   - `run()`: `configure_logging()`, `load_settings()`, log «Jarvis voice is ready. Say "Jarvis".», `KeyboardInterrupt` → log «Jarvis stopped.».
4. `main.py`: `from jarvis.bootstrap.app import run` + `if __name__ == "__main__": run()`.
5. `jarvis/services/announcement_service.py`: `AnnouncementService(synthesizer: PlaybackAwareSynthesizer, alert_light: AlertLight, server_settings)` usando `UnixDatagramServer`; validación `_normalise_text` igual; `main()` construye Azure + `AlertLightClient`. `jarvis/cli/announce.py`: CLI `--base64` igual que hoy usando `SocketAnnouncer`.
6. **Compatibilidad con la Raspberry:** reemplazar `notifications/announcement_service.py` y `notifications/announcement_client.py` por shims de 3–5 líneas que llaman a `jarvis.services.announcement_service.main()` / `jarvis.cli.announce.main()` (y `enqueue` → `SocketAnnouncer`), con docstring «Deprecated: kept until the Raspberry Pi units and the Vento alert caller use the jarvis.* modules.» Así no se rompe el proceso externo que hoy invoca esos módulos.
7. `git mv system.md prompts/system.md`.
8. Tests: reescribir `test_main_gemini_config.py` como `tests/unit/bootstrap/test_assistants.py` (mismo modelo y timeout para conversación y resumen; Vento con límite 6; quitar el skip) y mover `test_gemini_bridge_factory.py` aquí.

### Fase 7 — Retirar lo antiguo y documentación
0. Borrar el cliente Python original (tras comprobar que `serial_connection.py` pasa sus tests): `git rm ARDUINO/arduino_mega_connection.py` y borrar `ARDUINO/__pycache__/`.
1. Borrar los paquetes antiguos ya vacíos: `core/`, `audio/`, `speech/`, `bridge/`, `system/`, `Indicators/`, `Sensors/`, `config/`, `webs/` (todo `notifications/` excepto los 2 shims y su `__init__.py`).
2. Comprobar que no quedan imports antiguos (ni referencias a `ARDUINO/arduino_mega_connection`): `rg -n "^(from|import) (core|audio|speech|bridge|system|Indicators|Sensors|config|Arduino)\b" --glob "*.py"` debe devolver solo nada (los shims importan `jarvis.*`).
3. Comprobar que no hay `print(` en `jarvis/`: `rg -n "print\(" jarvis`.
4. Tests: estructura final `tests/unit/{config,domain,application,infrastructure,bootstrap}` con `__init__.py`; borrar los tests antiguos ya migrados.
5. `requirements.txt`: dejar comentario `# Pin versions with "pip freeze" on the Raspberry Pi` (el pin real lo hace el propietario en la Pi).
6. Documentación:
   - `docs/CONTEXTO_DEL_PROYECTO.md`: reescribir «Vista general», «Mapa de código» (nueva estructura y capas), rutas de configuración (`prompts/system.md`, `state/*.example`), comando del servicio de avisos `python -m jarvis.services.announcement_service`, CLI `python -m jarvis.cli.announce --base64 ...`, shims deprecados, y que el firmware está en `ARDUINO/main.cs` (solo para flashear la placa; Python no lo usa). Actualizar también los enlaces a `ARDUINO/Main program/main.cs` de este documento y de `CONTEXTO_DEL_PROYECTO.md`.
   - `README.md`: reescribir corto y actual (qué es, arquitectura por capas con el diagrama de §2, cómo instalar, cómo ejecutar, cómo pasar los tests, cómo añadir un proveedor nuevo implementando un puerto). Quitar la explicación de .NET y la sección «Cuando llegue Arduino».
   - `docs/COMANDOS.md`: quitar las referencias a `jarvis_voice_conversation.py` (usar `main.py` y `python -m compileall jarvis main.py`).
   - `docs/BRIDGE_TROUBLESHOOTING.md`: nota al principio indicando que `jarvis_voice.py`/`test_bridge_inspect.py` son del sistema anterior y que el puente actual es `jarvis/infrastructure/assistants/vento.py`.
   - `docs/PLAN_REFACTOR.md`: marcar todas las fases como completadas.

---

## 5. Pendiente que solo puede hacer el propietario (no lo ejecuta el modelo)
1. **Rotar** el token del puente Vento, la clave del agente Vento y la contraseña SSH de `jarvis` (siguen en el historial de Git).
2. En la Raspberry: confirmar la ruta real (`/home/jarvis/jarvis-voice` en docs vs `/home/jarvis/jarvis-project` en `sftp.json`) y que `ExecStart` del servicio apunta a `main.py`.
3. Cambiar la unidad del servicio de avisos y el llamador de alertas de Vento a `jarvis.services.announcement_service` / `jarvis.cli.announce`; después, borrar los shims de `notifications/`.
4. Ejecutar `pip freeze` en la `.venv` de la Pi y fijar versiones en `requirements.txt`.
5. Opcional: decidir si `models/` debe seguir versionado en Git (pesa mucho) o descargarse en la instalación.

## 6. Verificación

**En el PC (cada fase):**
```
python -m unittest discover -s tests -t .
python -m compileall -q jarvis main.py
```
Al final además: los dos `rg` de la Fase 7 sin resultados, y `python -c "import jarvis.bootstrap.assistants"` funciona en Windows.

**Comprobación de mayúsculas (obligatoria al final, en Windows):** `tests/unit/test_import_case.py`
debe pasar. Es la única garantía de que los imports coinciden con los nombres reales en Linux.

**En la Raspberry (solo arranque, sin tests):** seguir la lista de comprobación de funcionamiento
de arriba, tras desplegar el código (por `scp`/SFTP) y reiniciar el servicio con `docs/COMANDOS.md`.

**En la Raspberry (fin del refactor, siguiendo `docs/COMANDOS.md`, servicio detenido y `python main.py` en primer plano):**
1. Arranca, dice «Sistemas listos.», LED rojo, log de la primera lectura del depósito.
2. «Jarvis» → «Dime» → LED verde; pregunta → LED azul respirando → respuesta en voz con LED amarillo; aparecen `Yo: ...` / `Gemini: ...` en el log y dos líneas nuevas en `state/conversation.jsonl`.
3. «cambiar de modelo» → «Cambiando a Vento.»; pregunta a Vento; volver → «Cambiando a Gemini.».
4. Botón D3 mientras espera respuesta y mientras habla → corta y dice «¿Sí?»; pulsarlo fuera de una respuesta no hace nada.
5. «apágate» → pregunta → «no» → «Apagado cancelado, señor.».
6. «descansa» → «Sistema detenido hasta nueva orden.» y vuelve al LED rojo.
7. `http://<IP>:8765/` muestra el panel; `/api/rainwater-tank/current-level` devuelve el JSON con `distance_cm`, `fill_percentage`, `measured_at_unix_seconds`.
8. Con el servicio de avisos en marcha: `python -m jarvis.cli.announce --base64 $(echo -n "Prueba de aviso" | base64)` → se oye y el LED de alerta D12 se enciende durante la locución. Repetir con el shim antiguo `python -m notifications.announcement_client --base64 ...`.
9. Botón D2 (último, apaga la Pi): corta lo que esté sonando, dice el aviso de apagado y apaga.

---

## 7. Registro de ejecución

Al terminar cada fase, marca su columna en la matriz (☑ cumplido, ✖ fallo, — no aplica) y anota
en la tabla de comentarios cualquier incidencia. Si todo ha ido bien, escribe «Sin incidencias».

**Fecha de inicio:** ____ · **Ejecutado por (modelo):** ____

### 7.1 Matriz de control

| Punto de control | F0 | F1 | F2 | F3 | F4 | F5 | F6 | F7 |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| Pasos de la fase completados (§3.2, punto 1) | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| Tests en Windows: nº tests / skips (§3.2, punto 2) | ____ | ____ | ____ | ____ | ____ | ____ | ____ | ____ |
| `compileall` OK (§3.2, punto 3) | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| `test_import_case` pasa (§3.2, punto 4) | — | — | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| `git status` revisado (§3.2, punto 5) | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| Textos y frases idénticos (§3.2, punto 6) | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| `CONTEXTO_DEL_PROYECTO.md` actualizado (§3.2, punto 7) | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| Commit de punto de control aprobado (§3.2, punto 9) | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| Secretos fuera de Git (`git ls-files`) | — | ☐ | — | — | — | — | — | — |
| Subpasos 3.1 a 3.7 completados | — | — | — | ☐ | — | — | — | — |
| Comparación línea a línea con `core/conversation.py` | — | — | — | — | — | ☐ | — | — |
| Orden de intenciones igual que el original | — | — | — | — | — | ☐ | — | — |
| Orden de arranque igual que `main.py` original | — | — | — | — | — | — | ☐ | — |
| Shims de `notifications/` probados en Windows | — | — | — | — | — | — | ☐ | — |
| `rg` de la Fase 7 sin resultados | — | — | — | — | — | — | — | ☐ |
| `ARDUINO/arduino_mega_connection.py` eliminado; `ARDUINO/main.cs` intacto | — | — | — | — | — | — | — | ☐ |

### 7.2 Comentarios e incidencias

| Fase | Comentarios | Hash del commit |
| --- | --- | --- |
| 0 — Red de seguridad | | |
| 1 — Limpieza y secretos | | |
| 2 — Paquete `jarvis/`: config, dominio y puertos | | |
| 3 — Infraestructura | | |
| 4 — Aplicación: hilos, depósito, botones y memoria | | |
| 5 — Conversación (riesgo alto) | | |
| 6 — Arranque, servicio de avisos y entrada | | |
| 7 — Retirar lo antiguo y documentación | | |

### 7.3 Pendientes del propietario (§5)

| Pendiente | Hecho | Comentarios |
| --- | :-: | --- |
| Rotación de tokens y contraseñas | ☐ | |
| Ruta real y `ExecStart` del servicio confirmados en la Raspberry | ☐ | |
| Unidad de avisos y llamador de Vento cambiados a `jarvis.*` | ☐ | |
| `pip freeze` fijado en `requirements.txt` | ☐ | |
| Arranque en la Raspberry verificado (§6, lista de 9 puntos) | ☐ | |
