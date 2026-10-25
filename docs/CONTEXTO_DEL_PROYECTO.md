# Jarvis Project: contexto del sistema

## Propósito

Jarvis es un asistente de voz pensado para ejecutarse en una Raspberry Pi conectada a un Arduino Mega. El proyecto combina reconocimiento de voz local, una conversación con un proveedor de IA seleccionable, síntesis de voz de Azure, indicadores físicos y supervisión de un depósito de agua pluvial.

Este documento describe lo que está implementado en el código de este repositorio. Una configuración externa de Vento, del sistema operativo o del hardware puede añadir o cambiar comportamientos; esos casos se identifican como pendientes de comprobación, no como capacidades demostradas por el código Python.

## Vista general

```text
Micrófono USB
  -> captura local de audio
  -> Vosk local (palabra de activación y transcripción)
  -> agente activo: Gemini (por defecto) o Vento (se alterna con «cambiar de modelo»)
  -> respuesta de texto
  -> Azure Speech (voz es-ES-AlvaroNeural)
  -> reproducción PCM por aplay y salida de audio

Arduino Mega
  -> LED RGB de estado de Jarvis
  -> LED independiente para avisos
  -> sensor ultrasónico HC-SR04
  -> botón físico de apagado maestro y botón de interrupción de respuesta
  -> lecturas y estado de ambos botones consultados por el proceso Python

Proceso Python
  -> estado actual del depósito en JSON
  -> servidor HTTP con panel y API de nivel
  -> avisos locales de cambios de nivel, si el receptor de anuncios está activo
  -> monitor independiente de los botones físicos
```

El punto de composición principal es [main.py](main.py). La configuración central está en [config/settings.py](config/settings.py); los valores privados se cargan desde archivos separados y no se incluyen en este documento.

## Hardware y conexiones declaradas

- Raspberry Pi 3B como equipo previsto para ejecutar el programa.
- Micrófono USB, capturado como audio mono de 16 bits a 16 kHz. El índice de dispositivo configurado es `1`.
- Salida de audio configurada como `plughw:0,0`.
- Arduino Mega conectado por puerto serie USB, configurado por defecto como `/dev/ttyACM0` a `115200` baudios.
- En el firmware versionado, el LED RGB de cátodo común usa rojo en D9, verde en D10 y azul en D11.
- El HC-SR04 usa TRIG en D7 y ECHO en D8. El firmware mide el pulso de eco y responde a peticiones serie; no transmite una lectura por iniciativa propia cada segundo.
- El pulsador de apagado maestro se conecta entre D2 y GND. D2 está configurado como `INPUT_PULLUP`, por lo que no requiere resistencia externa: en reposo lee HIGH y al pulsar lee LOW. Debe ser un pulsador normalmente abierto; no se debe conectar D2 a 5 V.
- El pulsador para interrumpir una respuesta hablada se conecta entre D3 y GND. D3 también está configurado como `INPUT_PULLUP`; no requiere resistencia externa y debe usarse un pulsador normalmente abierto.
- El LED independiente de avisos está declarado como **rojo** en D12. El código no declara un LED blanco. Si la instalación física tiene uno blanco, el color del componente real no queda reflejado en el firmware.

Las conexiones aparecen documentadas en el firmware [ARDUINO/main.cs](ARDUINO/main.cs). La longitud de 10 metros del cable hacia el depósito forma parte del contexto físico descrito por el propietario, pero no es verificable desde el código.

## Arranque y selección del agente

1. `main.py` construye el micrófono, el reconocedor Vosk, Azure Speech, la conexión Arduino, el indicador de estado, el monitor de botones, el medidor y el servidor web.
2. El monitor de botones, el medidor y el servidor web se inician antes de entrar en el bucle de conversación.
3. Jarvis dice «Sistemas listos.» y prepara **Gemini** como agente inicial; no hay selección hablada («uno»/«dos») al arrancar. Si Gemini no se puede preparar (por ejemplo, falta `gemini.env`), dice «No puedo preparar Gemini.» y sigue funcionando.
4. Durante una conversación, la frase «cambiar de modelo» alterna entre Gemini y Vento: crea el puente del otro agente, dice «Cambiando a Vento.» o «Cambiar a Gemini.» y descarta el audio pendiente del micrófono. Si el otro agente no se puede preparar, dice «No puedo preparar Vento.» (o Gemini) y conserva el actual. Gemini usa por defecto `gemini-2.5-flash`; Vento envía texto al puente configurado.
5. La conversación conserva hasta seis elementos de historial temporal (tres pares usuario/asistente) durante la sesión activa. Ese historial se reinicia al volver al modo de espera; además existe una memoria duradera local descrita en la sección siguiente.

La síntesis de voz Azure se configura al construir el sistema, antes de preparar el agente. Por tanto, Azure y su archivo de credenciales son necesarios siempre, con cualquiera de los dos agentes. Las credenciales de Vento (`state/bridge.env`) solo se leen la primera vez que se cambia a Vento. El modelo de Vosk se carga localmente desde `models/vosk-model-small-es-0.42`.

### Memoria de conversación

El proyecto mantiene dos capas de historial distintas:

- **Historial temporal:** hasta seis mensajes (tres intercambios completos) en memoria del proceso. Se conserva durante la conversación activa, incluso al cambiar entre Gemini y Vento, y se descarta al volver al modo de espera. No sobrevive al reinicio del proceso.
- **Memoria duradera local:** después de recibir una respuesta, `ConversationMemory` guarda el intercambio en `state/conversation.jsonl`, tanto si se atendió con Gemini como con Vento. Esto significa que se archivan los turnos de ambos agentes, pero **no que ambos recuperen o reciban esta memoria duradera**. Cada línea es un objeto JSON con `timestamp` UTC, `role` (`user` o `assistant`) y `content`. Los comandos reservados que no se envían al modelo y las peticiones que fallan antes de obtener respuesta no se registran como intercambios.

Al iniciar, la memoria lee el JSONL existente; si el fichero no existe, comienza vacía. Las escrituras añaden las dos líneas de cada intercambio y fuerzan su persistencia en disco. La configuración actual comprueba si debe compactar al arrancar y después de cada intercambio: lo hace si hay más de diez mensajes de conversación almacenados (normalmente al completar el sexto intercambio) o si el fichero supera 4096 bytes. El umbral de tamaño provoca la compactación, no limita el tamaño máximo del fichero.

La compactación se ejecuta en segundo plano y **genera el resumen mediante una petición real a Gemini**. Usa las credenciales, el modelo configurado para Gemini (por defecto `gemini-2.5-flash`) y el timeout general; para esta petición desactiva el prompt de sistema de Jarvis y envía una instrucción específica de actualización de memoria. El prompt contiene el resumen previo, si ya existe, y los intercambios antiguos que van a compactarse, expresados como roles y textos (sin sus timestamps). Indica a Gemini que devuelva la memoria acumulativa completa en español, organizada por temas separados por `||`, conservando hechos, nombres, decisiones, preferencias y tareas pendientes; también le pide no inventar relaciones, no perder información por brevedad y mantener visibles las contradicciones en vez de decidirlas sin evidencia.

La respuesta no se guarda como si fuera otro turno hablado: se recorta y se escribe como una entrada JSONL con `role: "summary"`, timestamp y el texto generado. En el fichero principal queda un único resumen actualizado seguido por los cinco intercambios completos más recientes. Esos intercambios conservan sus entradas normales `role: "user"` y `role: "assistant"`; `assistant` es la respuesta del agente que atendió ese turno, Gemini o Vento. Los intercambios anteriores incluidos en el resumen dejan de estar como transcripciones individuales en el fichero principal. En la siguiente compactación, Gemini recibe el resumen ya guardado junto con los nuevos intercambios antiguos para producir el resumen acumulativo actualizado, y se vuelven a conservar aparte los cinco intercambios más recientes.

Antes de sustituir el fichero se crea o reemplaza `state/conversation.jsonl.bak` con una copia de la versión anterior; el JSONL nuevo se escribe mediante sustitución atómica. Si la llamada a Gemini falla o devuelve un resumen vacío, se registra una advertencia y se conserva el historial original sin compactar. La compactación puede volver a intentarse al arrancar de nuevo o después de otro intercambio. Un final de fichero truncado se descarta al leer; una línea corrupta en medio del fichero provoca un error.

**Recuperación para los agentes:** solo Gemini consulta la memoria duradera: en cada petición, Jarvis carga el último resumen disponible y hasta cinco intercambios completos recientes del JSONL. Gemini recibe el resumen como instrucción de sistema y las conversaciones recientes como historial; el puente admite hasta once mensajes de historial previos, sin contar la petición actual. Normalmente esta memoria aporta diez mensajes de historial (cinco pares) y el resumen. Vento no consulta ni recibe la memoria duradera ni su resumen. Recibe únicamente el historial temporal compartido de la conversación activa, limitado a los últimos seis mensajes (tres pares); por eso puede tener contexto de turnos recientes de Gemini o Vento dentro de esa sesión. Al cambiar de agente ese historial temporal se mantiene, pero al volver al modo de espera se pierde. Los turnos de Vento sí se guardan como mensajes `user`/`assistant` y pueden reaparecer en el resumen o en los cinco intercambios recientes que posteriormente recupera Gemini.

Esta memoria se guarda únicamente en los ficheros locales indicados. El código actual no la sincroniza con Obsidian ni la convierte a notas Markdown.

## Flujo de voz

### Reconocimiento

Vosk procesa el audio en la Raspberry. Según la documentación y el código de [jarvis/infrastructure/speech/vosk_recognizer.py](jarvis/infrastructure/speech/vosk_recognizer.py), el audio del micrófono no se envía a Gemini ni a Vento: el puente de Vento recibe texto y el historial, no audio.

Tras preparar el agente inicial, Jarvis queda esperando la palabra «Jarvis». La detección se realiza sobre resultados finales de Vosk. Al activarse, Jarvis pronuncia «Dime» y después escucha la instrucción.

### Fin de frase

No hay un corte configurado como «1,5 segundos exactos». Vosk decide cuándo finaliza un segmento de voz y, tras reconocer texto, el código añade un margen de continuación de **1 segundo**. Una nueva voz parcial reinicia ese margen. Por ello, el tiempo real depende de cuándo Vosk dé por finalizado el segmento y del tamaño de los bloques de audio; no es un temporizador fijo desde el último sonido.

### Respuesta

El texto se envía al agente activo. Cuando llega la respuesta, Azure Speech sintetiza voz con `es-ES-AlvaroNeural`. Se configura audio PCM mono de 24 kHz y se reproduce progresivamente mediante `aplay`; no se genera un archivo de audio completo como paso obligatorio intermedio. Una exclusión mutua local evita que dos reproducciones usen el altavoz a la vez.

## Indicador RGB de estado

El mapeo del orquestador y el firmware versionados es:

| Estado lógico | Indicador RGB |
| --- | --- |
| Espera de la palabra de activación (`WAITING`) | Rojo fijo |
| Escucha de una frase (`LISTENING`) | Verde fijo |
| Procesamiento/espera de respuesta (`PROCESSING`) | Azul con animación de respiración |
| Reproducción de voz (`SPEAKING`) | Amarillo intermitente |

El azul sube y baja con una semionda de un segundo; el amarillo cambia de estado cada 125 ms. Al detectar «Jarvis», primero se reproduce el acuse «Dime» (estado de voz/amarillo) y luego se abre la escucha de la instrucción (verde). Al terminar una instrucción, el estado pasa a azul mientras se consulta al agente; al reproducir la respuesta vuelve a amarillo.

«Descansa» y otras frases reservadas terminan la conversación activa y devuelven el programa a espera de «Jarvis»; no detienen el proceso. También existen frases para solicitar apagado o reinicio, con confirmación hablada. La implementación de las frases está en [core/intents.py](core/intents.py), y las acciones de sistema en [jarvis/infrastructure/system/power_controller.py](jarvis/infrastructure/system/power_controller.py). Apagar/reiniciar depende de que el sistema operativo permita `sudo -n` para esos comandos.

### Botones físicos

Ambos pulsadores se sondean independientemente del medidor mediante [system/arduino_button_monitor.py](system/arduino_button_monitor.py). El monitor consulta `BUTTON STATUS` al Arduino cada 0,1 segundos; el firmware responde `BUTTON_SHUTDOWN` para el botón de D2, `BUTTON_INTERRUPT` para el botón de D3 y `BUTTON_IDLE` cuando no hay una pulsación pendiente. Las dos entradas tienen antirrebote y detección de flanco en [ARDUINO/main.cs](ARDUINO/main.cs).

El botón de D2 activa el apagado maestro en cualquier fase: detiene la captura del micrófono, interrumpe la síntesis/reproducción activa de Azure y `aplay`, anuncia «Apagado manual accionado!, apagando sistemas. Venga, chao!» y llama a `poweroff`. Las operaciones para interrumpir el audio están en [jarvis/infrastructure/speech/azure_synthesizer.py](jarvis/infrastructure/speech/azure_synthesizer.py) y [jarvis/infrastructure/audio/playback.py](jarvis/infrastructure/audio/playback.py).

El botón de D3 solo actúa mientras hay una respuesta de Gemini o Vento en curso, en cualquiera de sus dos fases: mientras Jarvis **espera** a que el modelo genere el texto (abandona la petición y no reproduce la respuesta tardía) o mientras **reproduce** en voz alta la respuesta (corta la locución). En ambos casos dice «¿Sí?» y el siguiente paso del diálogo escucha una nueva instrucción. Pulsarlo durante otras locuciones (acuse «Dime», confirmaciones, avisos) o durante la escucha no interrumpe esas fases.

La solicitud de apagado del sistema depende de que `sudo -n /usr/sbin/poweroff` esté autorizado para el usuario que ejecuta Jarvis. El botón de D2 no solicita confirmación hablada.

## Depósito de agua pluvial

### Lectura y cálculo

El medidor Python pide al Arduino `SENSOR DISTANCE` cada **5 segundos**. El Arduino mide la distancia con el HC-SR04 y devuelve centímetros; el cálculo del porcentaje lo realiza Python, no Vento ni el navegador. Este sondeo mantiene actualizado el último nivel y permite detectar cambios y cruces de umbral para los avisos.

Los valores de calibración actuales son 80 cm para depósito vacío y 9 cm para lleno. El porcentaje se calcula linealmente entre esos extremos, se redondea a entero y se limita al intervalo 0–100 %. Las mediciones no válidas se descartan. Las lecturas correctas se imprimen en consola y se escriben de forma atómica en `state/rainwater_tank_state.json`.

### Avisos de nivel

El medidor no anuncia cada lectura. Después de la primera lectura, puede encolar un aviso porcentual cuando el nivel cambia al menos cinco puntos respecto al último nivel anunciado y han pasado al menos cinco segundos desde el aviso porcentual anterior. Además, anuncia cruces de umbral direccionales con histéresis:

- Al subir: nivel bueno desde 80 %, casi lleno desde 90 % y lleno desde 100 %.
- Al bajar: nivel bajo al cruzar hacia 20 % o menos, muy bajo al cruzar hacia 10 % o menos y vacío al cruzar por debajo de 5 %.
- Un mismo aviso de umbral se rearma al alejarse tres puntos del umbral correspondiente.

El callback envía texto a un socket Unix local mediante [notifications/announcement_client.py](notifications/announcement_client.py), que delega en `SocketAnnouncer` (si el servicio de avisos no escucha, solo registra un aviso de una línea). El componente [notifications/announcement_service.py](notifications/announcement_service.py) consume esos mensajes en orden, usa Azure para hablarlos y activa el indicador de alerta durante la reproducción.

**Límite importante:** `main.py` inicia el cliente y puede encolar avisos, pero no inicia `AnnouncementService`. Ese receptor debe ejecutarse como proceso/servicio independiente para que los avisos se oigan. No se encontró en este repositorio una suscripción Python a alertas entrantes de Vento ni un servicio que conecte esas alertas con el receptor local. El mecanismo de encolado es local y no demuestra por sí mismo una suscripción a Vento.

### Panel web

El servidor HTTP se enlaza por defecto a `0.0.0.0:8765`, de modo que escucha en todas las interfaces de red. Expone el panel en `/` y el nivel actual en `/api/rainwater-tank/current-level`. Un dispositivo de la red puede abrir `http://<IP-de-la-Raspberry>:8765/`, sujeto a conectividad y reglas de red.

El panel muestra el porcentaje, una representación visual del depósito, la distancia y una gráfica seleccionable entre 5 minutos y 24 horas. Consulta la API cada 500 ms, pero esa consulta solo obtiene el último nivel en memoria; no provoca una lectura nueva del sensor. Los datos del sensor se actualizan cada 5 segundos. **El histórico de la gráfica se guarda en `localStorage` del navegador de cada dispositivo**, no en el servidor; se pierden sus muestras si se borra el almacenamiento local o se usa otro navegador.

El contador de litros no proviene de un caudalímetro ni de un sensor de lluvia. Es una estimación de subida neta del nivel dentro del rango seleccionado, basada en una capacidad fija codificada de 1000 litros. Puede no representar litros reales si esa capacidad no coincide con el depósito; tampoco suma el agua que entra y vuelve a salir durante el rango.

El panel y la API no tienen autenticación en el servidor versionado y permiten CORS desde cualquier origen. En consecuencia, cualquier cliente que alcance ese puerto puede consultar el nivel y cargar el panel. La exposición efectiva depende de la red y del firewall del equipo.

## Avisos hablados y dos indicadores

Hay dos rutas distintas:

1. **Indicador RGB principal:** lo controla la conversación con estados serie del Arduino.
2. **Aviso local independiente:** el servicio de anuncios habla textos recibidos por socket Unix y solicita encender/apagar el LED de alerta de D12 mediante el receptor de control que `main.py` sí inicia.

El código del firmware declara que el indicador independiente es rojo. El usuario ha descrito un LED blanco observado en su instalación; ese detalle físico no coincide con la definición del repositorio y debe comprobarse en el hardware/firmware desplegado.

## Integraciones y límites de acceso

### Gemini y Vento

- Gemini recibe texto y el historial de conversación a través de su puente.
- Vento recibe texto e historial mediante una petición HTTP configurada con `BRIDGE_URL` y `BRIDGE_TOKEN`.
- La clase `VentoBridge` de este repositorio implementa solicitudes/respuestas del agente conversacional. No contiene una conexión de eventos entrantes para suscribirse a alertas.

### Agente de dispositivo Vento

El documento auxiliar [docs/INSTALAR_AGENTE_VENTO.md](INSTALAR_AGENTE_VENTO.md) describe otro componente: descarga un agente Linux ARM64 y configura funciones de sistema, archivos, comandos y notificaciones, además de `remote_agent_mode: full-access`. Esa configuración permite inferir la intención de dar acceso amplio al agente de dispositivo, pero el repositorio no permite verificar qué proceso está instalado/ejecutándose en la Raspberry ni los permisos efectivos del usuario del sistema. No confundir esa configuración externa con el puente de voz `VentoBridge`.

En ese documento la clave de dispositivo está sustituida por el marcador `<DEVICE_KEY>`. La clave real que antes estaba en el fichero sigue en el historial de Git (ver «Secretos expuestos en el historial de Git»).

## Configuración y credenciales

| Integración | Ruta/valor por defecto | Contenido esperado |
| --- | --- | --- |
| Azure Speech | `~/.config/jarvis-voice/azure.env` | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` |
| Gemini | `~/.config/jarvis-voice/gemini.env` | `GEMINI_API_KEY`, opcionalmente `GEMINI_MODEL` |
| Puente Vento | `state/bridge.env` (plantilla: `state/bridge.env.example`) | `BRIDGE_URL`, `BRIDGE_TOKEN` |
| Modelo Vosk | `models/vosk-model-small-es-0.42` | Archivos del modelo local español |
| Memoria conversacional | `state/conversation.jsonl` y `state/conversation.jsonl.bak` | Historial JSONL local y copia previa a compactaciones |
| Estado del depósito | `state/rainwater_tank_state.json` | Última medida válida, generada localmente por el programa y excluida de Git |
| Acceso SFTP desde VS Code | `.vscode/sftp.json` (plantilla: `.vscode/sftp.example.json`) | Host, usuario y contraseña SSH de la Raspberry; excluido de Git |

Todo el contenido de `state/` está excluido de Git (`/state/*` en `.gitignore`) salvo `state/.gitkeep` y las plantillas `state/*.example`. Las credenciales y el historial de conversación se crean y mantienen solo en cada equipo.

### Secretos expuestos en el historial de Git

Los secretos y las conversaciones privadas ya no están versionados (`state/bridge.env`, `state/conversation.jsonl(.bak)` y `.vscode/sftp.json` se sacaron del índice; las contraseñas y la clave de dispositivo se eliminaron de `docs/`), pero **siguen en el historial de Git**, que no se ha reescrito. El propietario debe rotar:

- el token del puente Vento (`BRIDGE_TOKEN`),
- la clave de dispositivo del agente Vento,
- la contraseña SSH del usuario `jarvis` de la Raspberry. En la copia local de `.vscode/sftp.json` coincide con el nombre de usuario, por lo que es débil; cámbiala por una distinta, no solo por una nueva igual de corta.

Las rutas, dispositivo de audio, puerto serie, modelo Gemini, voz Azure, intervalo de lectura y rutas de socket están centralizados en [config/settings.py](config/settings.py) y en los valores por defecto de sus clases. Este documento no contiene claves ni tokens.

## Diferencias y comprobaciones pendientes en la instalación

Estos puntos afectan a la diferencia entre el repositorio y la instalación descrita; no se han validado en hardware ni en servicios externos:

1. **Capitalización de import Arduino:** desde la Fase 3 el código ya no importa `Arduino.arduino_mega_connection` (el cliente serie vive en `jarvis/infrastructure/arduino/serial_connection.py`), así que el arranque ya no puede fallar por la carpeta `ARDUINO`. El fichero original `ARDUINO/arduino_mega_connection.py` sigue en el repositorio, sin usar, hasta la Fase 7. Pendiente de comprobar en la Raspberry: que el arranque con el código nuevo funciona (sobre todo los sockets Unix del LED de alerta y de los avisos, que no se pueden probar en Windows).
2. **Proceso de avisos:** confirmar que `python -m notifications.announcement_service` (o una unidad de servicio equivalente) se inicia junto a Jarvis. `main.py` no lo inicia.
3. **Alertas de Vento:** identificar el proceso/configuración desplegados que reciben notificaciones de Vento y llaman al cliente de avisos. No aparecen en el flujo Python del repositorio inspeccionado.
4. **LED de alerta:** contrastar el montaje físico y la versión desplegada del firmware con la declaración roja de D12.
5. **Parámetros físicos:** confirmar que el sensor está instalado y que 80 cm/9 cm y la capacidad estimada de 1000 litros corresponden al depósito real.
6. **Permisos de apagado/reinicio:** confirmar la unidad de ejecución y las reglas `sudoers`; la presencia del código no prueba que el sistema autorice esas órdenes.
7. **Seguridad de red y credenciales:** revisar si el puerto 8765 está limitado a la LAN deseada; rotar las claves que quedaron expuestas en el historial de Git (los ficheros ya no se versionan; ver «Secretos expuestos en el historial de Git»). El puente Vento incorpora su token en la URL de petición, por lo que también deben considerarse los registros HTTP del servicio intermedio.

## Mapa de código

- Arranque e integración de dependencias: [main.py](main.py)
- Orquestación, selección del agente y estados: [core/conversation.py](core/conversation.py) (el que se ejecuta hoy); su sustituto, dividido en clases, está en [jarvis/application/conversation/](jarvis/application/conversation/) y aún no está conectado
- Persistencia y recuperación de memoria conversacional: [jarvis/application/memory/conversation_memory.py](jarvis/application/memory/conversation_memory.py) (fachada antigua con contexto `list[dict]` en [core/memory.py](core/memory.py))
- Comandos reservados: [core/intents.py](core/intents.py)
- Configuración y carga de credenciales: [config/settings.py](config/settings.py)
- Captura y reconocimiento local: [jarvis/infrastructure/audio/microphone.py](jarvis/infrastructure/audio/microphone.py), [jarvis/infrastructure/speech/vosk_recognizer.py](jarvis/infrastructure/speech/vosk_recognizer.py)
- Puentes Gemini y Vento: [bridge/gemini_bridge.py](bridge/gemini_bridge.py) y [bridge/vento_bridge.py](bridge/vento_bridge.py) (fachadas con la firma antigua `history: list[dict]`); el trabajo lo hacen `gemini.py`, `vento.py` y `vento_reply_parser.py` en [jarvis/infrastructure/assistants/](jarvis/infrastructure/assistants/)
- Síntesis Azure y reproducción: [jarvis/infrastructure/speech/azure_synthesizer.py](jarvis/infrastructure/speech/azure_synthesizer.py), [jarvis/infrastructure/audio/playback.py](jarvis/infrastructure/audio/playback.py)
- Monitor de botones físicos: [jarvis/application/button_monitor.py](jarvis/application/button_monitor.py) (`ButtonMonitor`); fachada antigua [system/arduino_button_monitor.py](system/arduino_button_monitor.py)
- Indicadores y medidor: [Indicators/arduino_rgb_indicator.py](Indicators/arduino_rgb_indicator.py) (fachada sobre `ArduinoStatusLight`, `ArduinoAlertLight` y `AlertLightControlServer`), [jarvis/application/tank_monitor.py](jarvis/application/tank_monitor.py) (`TankMonitor`; fachada antigua [Sensors/rainwater_tank_meter.py](Sensors/rainwater_tank_meter.py))
- Adaptadores Arduino: [jarvis/infrastructure/arduino/](jarvis/infrastructure/arduino/)
- Sockets Unix (LED de alerta y avisos): [jarvis/infrastructure/ipc/](jarvis/infrastructure/ipc/)
- Panel web: [jarvis/infrastructure/web/tank_web_server.py](jarvis/infrastructure/web/tank_web_server.py) y [jarvis/infrastructure/web/static/rainwater_tank.html](jarvis/infrastructure/web/static/rainwater_tank.html); receptor de avisos: [notifications/announcement_service.py](notifications/announcement_service.py)
- Firmware Arduino (solo para flashear la placa): [ARDUINO/main.cs](ARDUINO/main.cs)
- Control de energía: [jarvis/infrastructure/system/power_controller.py](jarvis/infrastructure/system/power_controller.py)
- Memoria JSONL y estado del depósito: [jarvis/infrastructure/memory/jsonl_backend.py](jarvis/infrastructure/memory/jsonl_backend.py), [jarvis/infrastructure/tank/state_file.py](jarvis/infrastructure/tank/state_file.py)

## Refactor planificado

Existe un plan de refactor y reestructuración en [docs/PLAN_REFACTOR.md](PLAN_REFACTOR.md): paquete único `jarvis/` por capas, limpieza de backups y código muerto, retirada de secretos de Git y corrección de los tests que fallan. Ejecutadas hasta ahora: **Fase 0** (red de seguridad: tests de caracterización y arreglo de los 3 tests rotos), **Fase 1** (limpieza de backups y código muerto, secretos fuera de Git, documentación movida) **Fase 2** (nuevo paquete `jarvis/` con configuración, dominio y puertos), **Fase 3** (adaptadores de infraestructura), **Fase 4** (capa de aplicación: hilos de fondo, depósito, botones y memoria) y **Fase 5** (conversación dividida en clases pequeñas, sin conectar todavía). El resto de fases está pendiente. Mientras no se ejecuten, el programa que arranca sigue siendo la orquestación antigua (`core/conversation.py`), que ya trabaja sobre los adaptadores nuevos y sobre `TankMonitor`, `ButtonMonitor` y `ConversationMemory` (ver «Infraestructura (Fase 3)» y «Aplicación (Fase 4)»); el orquestador nuevo (ver «Conversación (Fase 5)») lo conecta la Fase 6.

### Paquete `jarvis/` (Fase 2: configuración, dominio y puertos)

Código puro (sin I/O pesado). El código antiguo solo lo usa de forma parcial (ver Fase 3) y el comportamiento de la Raspberry no cambia:

- `jarvis/config/`: `env_file.py` (`read_env_file`, quita comillas), `credentials.py` (`AzureCredentials`, `GeminiCredentials`, `VentoCredentials` y sus `load_*`, que reciben la ruta) y `settings.py` (dataclasses inmutables por grupo con los mismos valores actuales y `load_settings(base_dir)`; la raíz del proyecto es `parents[2]` de ese fichero).
- `jarvis/domain/`: `AssistantStatus`, `AssistantModel` (Gemini/Vento), `ChatMessage`/`ConversationContext`/`ShortTermHistory`, `Intent` + `classify()` + `is_confirmation()`, `phrases.py` y `tank_phrases.py` (todas las frases habladas, en español), y `tank.py` (`TankLevel`, `TankCalibration`, `TankStatus`, `TankAlertPolicy`, que es la lógica de avisos del depósito copiada del medidor actual).
- `jarvis/ports/`: interfaces `ABC` (`AudioInput`, `SpeechRecognizer`, `SpeechSynthesizer`, `PlaybackAwareSynthesizer`, `AssistantBridge`, `StatusIndicator`, `AlertLight`, `ButtonPanel`, `DistanceSensor`, `PowerController`, `MemoryBackend`/`MemoryEntry`, `Announcer`, `TankStateStore`).
- `jarvis/infrastructure/runtime.py`: `runtime_dir()` (`/run/user/<uid>`, uid 1000 si el sistema no tiene `os.getuid`).

### Infraestructura (Fase 3)

Los adaptadores concretos viven en `jarvis/infrastructure/` y cada uno implementa su puerto. `main.py` y los módulos antiguos ya los usan; la lógica de conversación, el medidor y el monitor de botones siguen siendo los antiguos hasta las Fases 4 a 6.

- `arduino/`: `protocol.py` (comandos serie; debe coincidir con `ARDUINO/main.cs`), `serial_connection.py` (`ArduinoSerialConnection`, copia del cliente serie original, y el `Protocol` `SerialRequester`), `status_light.py`, `alert_light.py`, `button_panel.py` y `distance_sensor.py`.
- `ipc/`: `unix_datagram.py` (`UnixDatagramServer`, `send_datagram`), `alert_light_server.py` (`AlertLightControlServer`), `alert_light_client.py` (`AlertLightClient`) y `announcer.py` (`SocketAnnouncer`).
- `audio/` y `speech/`: `SoundDeviceMicrophone`, `PlaybackLock(lock_path)` + `AplayPcmPlayer`, `VoskSpeechRecognizer` (ya sin `interrupt_event`) y `AzureSpeechSynthesizer` (recibe la ruta del bloqueo de altavoz).
- `assistants/`: `GeminiAssistant`, `VentoAssistant` y `parse_vento_reply`; reciben un `ConversationContext`. Formato de red, cabeceras y mensajes de error idénticos a los anteriores.
- `memory/jsonl_backend.py`, `system/power_controller.py` (`SudoPowerController`), `tank/state_file.py` (`JsonTankStateFile`) y `web/tank_web_server.py` (`TankWebServer`, con el panel en `web/static/`).

Cómo conviven con el código antiguo hasta la Fase 7:

- `core/interfaces.py` reexporta `AssistantStatus`, `StatusIndicator`, `AlertLight`, `SpeechRecognizer`, `SpeechSynthesizer` y `SystemController` desde `jarvis`. `AssistantBridge` conserva la firma antigua. `core/memory.py` solo conserva `ConversationMemory` y reexporta el almacenamiento. `config/settings.py` reutiliza `read_env_file` y las credenciales de `jarvis.config`, y añade `PLAYBACK_LOCK_PATH`.
- `bridge/gemini_bridge.py` y `bridge/vento_bridge.py` son fachadas que convierten el historial antiguo (`list[dict]`) en un `ConversationContext` con `bridge/legacy_context.py` y delegan en los asistentes nuevos.
- `Indicators/arduino_rgb_indicator.py`, `system/arduino_button_monitor.py` y `Sensors/rainwater_tank_meter.py` mantienen su API pero usan los adaptadores nuevos. Desde la Fase 4 el medidor y el monitor de botones delegan en `TankMonitor` (con `TankAlertPolicy`) y `ButtonMonitor`.
- `RainwaterTankLevel` es ahora un alias de `TankLevel`. `notifications/announcement_service.py` conserva su propio bucle de socket hasta la Fase 6.

Cambios de comportamiento permitidos por el plan: `SocketAnnouncer` registra un aviso de una línea (sin traceback) si el servicio de avisos no escucha, en lugar de lanzar `OSError`; así, el medidor da por anunciado un aviso aunque el servicio no esté en marcha. Los mensajes de consola de Vosk, el micrófono y el cliente serie pasan a `logging` en inglés, y `main.py` configura `logging.basicConfig` a nivel INFO para que se sigan viendo. Las líneas `Yo:`, `Gemini:` y `Vento:` y los `print` del orquestador, del medidor y del monitor de botones no se han tocado.

### Aplicación (Fase 4)

`jarvis/application/` solo importa `jarvis.domain`, `jarvis.ports` y a sí misma (lo comprueba `tests/unit/application/test_layering.py`). Ya la usan los módulos antiguos a través de fachadas:

- `periodic_task.py`: `PeriodicTask(name, interval_seconds, action)`, hilo daemon que ejecuta `action` y espera con `Event.wait`. `start()` es idempotente, `close(timeout)` lo detiene y una excepción de `action` se registra y no detiene el bucle.
- `tank_monitor.py`: `TankMonitor(sensor, calibration, store, alert_policy, poll_interval_seconds)`. `poll_once()` lee la distancia, crea el `TankLevel` (porcentaje con `TankCalibration`), lo guarda como último nivel, lo persiste con el `TankStateStore`, registra solo la primera lectura (`Rainwater tank distance: … cm | fill level: …%`) y se la pasa a `TankAlertPolicy.observe`. `publish(level)` hace lo mismo para un nivel ya medido. Las lecturas no válidas se descartan sin tocar el último nivel.
- `button_monitor.py`: `ButtonMonitor(panel, handlers, poll_interval_seconds)`. Cada ciclo (`poll_once()`) pregunta al `ButtonPanel` por una pulsación pendiente, la registra y llama al handler de su `ButtonPress`; si el handler falla, lo registra y sigue.
- `memory/summary_prompt.py`: `build_summary_prompt(previous_summary, messages)` con el texto exacto del prompt de compactación descrito en «Memoria de conversación».
- `memory/conversation_memory.py`: `ConversationMemory` con la misma lógica de compactación, bloqueos e hilos que antes. `get_context()` devuelve ahora un `ConversationContext` (`messages` con los últimos cinco intercambios completos y `summary` con el último resumen o `None`), no una lista con un falso mensaje `role: "summary"`.

Cómo conviven con el código antiguo hasta la Fase 6:

- `core/memory.py` es una subclase fina de la `ConversationMemory` nueva que convierte `get_context()` al formato antiguo (`list[dict]` con el resumen como primer elemento `role: "summary"`) que espera el orquestador antiguo.
- `Sensors/rainwater_tank_meter.py` (`RainwaterTankMeter`) y `system/arduino_button_monitor.py` (`ArduinoButtonMonitor`) mantienen su API pero delegan en `TankMonitor` y `ButtonMonitor`. El medidor usa ya `TankAlertPolicy` (calibración 80/9 cm, cambio mínimo de 5 puntos y 5 s) y traduce `TankStatus` a su valor de texto (`"good"`, …) para los callbacks antiguos.

Cambios de comportamiento permitidos por el plan: la primera lectura del depósito y las pulsaciones de botón se muestran ahora por `logging` en inglés (`Rainwater tank distance: …`, `Button press detected: shutdown|interrupt`) en lugar de los `print` anteriores; el fallo de un aviso del depósito se registra con el logger `jarvis.domain.tank`.

### Conversación (Fase 5)

`jarvis/application/conversation/` divide `core/conversation.py` en clases pequeñas que reciben sus dependencias por constructor. **Todavía no están conectadas:** `main.py` sigue arrancando el orquestador antiguo, así que el comportamiento de la Raspberry no cambia hasta la Fase 6 (que construirá este grafo en `bootstrap/`). Solo importan `domain`, `ports` y la propia capa de aplicación (lo vigila `test_layering.py`).

- `safe_status.py`: `SafeStatusIndicator`, decorador de un `StatusIndicator` que registra y no relanza los fallos (sustituye a `_set_status`).
- `voice.py`: `Voice` (todo lo que se dice en voz alta). `say()` equivale a `_speak` (nada si se está apagando, bloqueo de voz, estado SPEAKING, silencia el micrófono); `interrupt()` corta la locución registrando errores; `say_last_words()` toma el altavoz interrumpiendo a quien hable y habla aunque se esté apagando.
- `listener.py`: `SentenceListener.listen()` (estado LISTENING y línea `Yo: <texto>`).
- `transcript.py` y el logger `jarvis.transcript`: las líneas `Yo: ...` / `Gemini: ...` / `Vento: ...` se emiten por ese logger (la Fase 6 lo configurará con formato `%(message)s` a stdout para que el log siga igual).
- `reply_interrupt.py`: `ReplyInterruptGate` sustituye a los tres `Event` de la respuesta y al hilo vigilante del botón D3: `begin()`/`end()` delimitan el ciclo de una respuesta, `request()` (lo llamará el botón) la abandona y, si se está locutando, corta la voz, y `speaking()` marca la locución.
- `emergency_shutdown.py`: `EmergencyShutdown.trigger()` (botón D2), idempotente; activa el aviso de apagado y lanza el hilo `emergency-shutdown` que corta el micrófono, dice la despedida y apaga.
- `assistant_selector.py`: `AssistantSelector` mantiene el modelo y el puente activos; `start()` fija el modelo aunque falle el puente y `switch()` alterna sin cambiar nada si el otro no se puede preparar.
- `power_commands.py`: `PowerCommandHandler.handle(intent)` devuelve `PowerOutcome` (`NOT_HANDLED`, `EXECUTED`, `CANCELLED`) tras la confirmación hablada.
- `turn_handler.py`: `TurnHandler.handle()` es un turno completo (petición en un hilo `assistant-model-request` que se abandona con el botón, historial corto o memoria duradera según el modelo, registro del intercambio y locución).
- `orchestrator.py`: `ConversationOrchestrator` solo contiene el bucle (espera de «Jarvis» y conversación). Orden de intenciones idéntico al original: apagado/reinicio, cambio de modelo, fin y, si no, pregunta.

Cambios de comportamiento permitidos por el plan: «Cambiando a Gemini.» sustituye a «Cambiar a Gemini.» (solo en el orquestador nuevo; el antiguo sigue diciendo la frase anterior), y los mensajes de error y de estado del orquestador pasan a `logging` en inglés. El aviso «Esperando la palabra «Jarvis»...» pasa a `Waiting for the wake word "Jarvis"`.

`tests/unit/test_import_case.py` compara cada import de `jarvis/`, `main.py` y `tests/` con los nombres reales de ficheros distinguiendo mayúsculas, para detectar en Windows lo que fallaría en la Raspberry. Desde la Fase 3 su lista de excepciones conocidas (`KNOWN_LEGACY_VIOLATIONS`) está vacía, porque `main.py` ya no importa `Arduino`.

## Pruebas

Los tests se ejecutan en el PC de desarrollo (Windows), no en la Raspberry:

```text
python -m unittest discover -s tests -t .
```

Estado actual: 263 tests, 6 omitidos: `tests/test_main_gemini_config.py` (necesita `sounddevice`, `vosk`, `azure` y `serial`, que no están instalados en el PC; se reescribirá en la Fase 6) y 5 pruebas de sockets Unix (`UnixDatagramServer` y `AlertLightControlServer`), que solo se ejecutan en Linux porque Python en Windows no ofrece `socket.AF_UNIX`. Esos sockets se han comprobado con un socket falso en memoria, no con sockets reales: queda pendiente probarlos en la Raspberry. `tests/` es un paquete (`tests/__init__.py`). Los tests de caracterización de la Fase 0 fijan el comportamiento actual de las frases reservadas (`tests/test_intents.py`), los avisos del depósito (`tests/test_tank_alerts.py`), el parseo y la petición del puente Vento (`tests/test_vento_reply_parsing.py`) y los flujos de conversación (`tests/test_conversation_flows.py`). Los tests del código nuevo están en `tests/unit/` (`config/`, `domain/`, `application/`, `infrastructure/` y `test_import_case.py`); `tests/unit/application/conversation/` cubre las clases de la Fase 5 con los fakes compartidos de `tests/fakes.py` (incluye los casos de `test_conversation_flows.py` y `test_conversation_model_switch.py` migrados a la API pública); `tests/unit/application/` cubre `PeriodicTask`, `TankMonitor` (con un sensor falso y un almacén en memoria), `ButtonMonitor`, el prompt de resumen, `ConversationMemory` (movido desde `tests/test_conversation_memory.py`) y las dependencias permitidas de la capa; `tests/unit/infrastructure/` cubre los asistentes, el almacenamiento JSONL y del depósito, el servidor web (en `127.0.0.1`), los adaptadores Arduino (con un `FakeSerial`), los sockets Unix y las fachadas antiguas; varios replican casos de los tests antiguos (frases reservadas, avisos del depósito, `read_env_file`) y los antiguos se borrarán en la Fase 7.

`read_env_file` (`config/settings.py`) ya elimina las comillas simples o dobles que rodean un valor de los ficheros `.env`.

## Alcance de esta descripción

Esta revisión se basa en el código y configuración visibles en el repositorio. No se conectó a la Raspberry, Arduino, Azure, Gemini ni Vento; por tanto, no certifica el estado actual de esos servicios, la red, los periféricos, los procesos externos ni los permisos efectivos.