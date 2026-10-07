# Jarvis Project: contexto del sistema

## Propósito

Jarvis es un asistente de voz pensado para ejecutarse en una Raspberry Pi conectada a un Arduino Mega. El proyecto combina reconocimiento de voz local, una conversación con un proveedor de IA seleccionable, síntesis de voz de Azure, indicadores físicos y supervisión de un depósito de agua pluvial.

Este documento describe lo que está implementado en el código de este repositorio. Una configuración externa de Vento, del sistema operativo o del hardware puede añadir o cambiar comportamientos; esos casos se identifican como pendientes de comprobación, no como capacidades demostradas por el código Python.

## Vista general

```text
Micrófono USB
  -> captura local de audio
  -> Vosk local (palabra de activación y transcripción)
  -> selección: Gemini o Vento
  -> respuesta de texto
  -> Azure Speech (voz es-ES-AlvaroNeural)
  -> reproducción PCM por aplay y salida de audio

Arduino Mega
  -> LED RGB de estado de Jarvis
  -> LED independiente para avisos
  -> sensor ultrasónico HC-SR04
  -> botón físico de apagado maestro
  -> lecturas y estado del botón consultados por el proceso Python

Proceso Python
  -> estado actual del depósito en JSON
  -> servidor HTTP con panel y API de nivel
  -> avisos locales de cambios de nivel, si el receptor de anuncios está activo
  -> monitor independiente del botón que activa el apagado maestro
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
- El LED independiente de avisos está declarado como **rojo** en D12. El código no declara un LED blanco. Si la instalación física tiene uno blanco, el color del componente real no queda reflejado en el firmware.

Las conexiones aparecen documentadas en el firmware [ARDUINO/Main program/main.cs](ARDUINO/Main%20program/main.cs). La longitud de 10 metros del cable hacia el depósito forma parte del contexto físico descrito por el propietario, pero no es verificable desde el código.

## Arranque y selección del agente

1. `main.py` construye el micrófono, el reconocedor Vosk, Azure Speech, la conexión Arduino, el indicador de estado, el monitor del botón, el medidor y el servidor web.
2. El monitor del botón, el medidor y el servidor web se inician antes de entrar en el bucle de conversación.
3. Jarvis solicita por voz elegir Gemini diciendo «uno» o «1», o Vento diciendo «dos» o «2».
4. Solo se crea el puente elegido. Gemini usa por defecto `gemini-2.5-flash`; Vento envía texto al puente configurado.
5. La conversación conserva hasta seis elementos de historial (tres pares usuario/asistente) durante la sesión activa. Ese historial se reinicia al volver al modo de espera.

La síntesis de voz Azure se configura al construir el sistema, antes de elegir el agente. Por tanto, Azure y su archivo de credenciales son necesarios incluso si se selecciona Gemini. El modelo de Vosk se carga localmente desde `models/vosk-model-small-es-0.42`.

## Flujo de voz

### Reconocimiento

Vosk procesa el audio en la Raspberry. Según la documentación y el código de [speech/vosk_recognizer.py](speech/vosk_recognizer.py), el audio del micrófono no se envía a Gemini ni a Vento: el puente de Vento recibe texto y el historial, no audio.

Tras seleccionar un agente, Jarvis queda esperando la palabra «Jarvis». La detección se realiza sobre resultados finales de Vosk. Al activarse, Jarvis pronuncia «Sí señor?» y después escucha la instrucción.

### Fin de frase

No hay un corte configurado como «1,5 segundos exactos». Vosk decide cuándo finaliza un segmento de voz y, tras reconocer texto, el código añade un margen de continuación de **1 segundo**. Una nueva voz parcial reinicia ese margen. Por ello, el tiempo real depende de cuándo Vosk dé por finalizado el segmento y del tamaño de los bloques de audio; no es un temporizador fijo desde el último sonido.

### Respuesta

El texto se envía al agente elegido. Cuando llega la respuesta, Azure Speech sintetiza voz con `es-ES-AlvaroNeural`. Se configura audio PCM mono de 24 kHz y se reproduce progresivamente mediante `aplay`; no se genera un archivo de audio completo como paso obligatorio intermedio. Una exclusión mutua local evita que dos reproducciones usen el altavoz a la vez.

## Indicador RGB de estado

El mapeo del orquestador y el firmware versionados es:

| Estado lógico | Indicador RGB |
| --- | --- |
| Espera de la palabra de activación (`WAITING`) | Rojo fijo |
| Escucha de una frase (`LISTENING`) | Verde fijo |
| Procesamiento/espera de respuesta (`PROCESSING`) | Azul con animación de respiración |
| Reproducción de voz (`SPEAKING`) | Amarillo intermitente |

El azul sube y baja con una semionda de un segundo; el amarillo cambia de estado cada 125 ms. Al detectar «Jarvis», primero se reproduce el acuse «Sí señor?» (estado de voz/amarillo) y luego se abre la escucha de la instrucción (verde). Al terminar una instrucción, el estado pasa a azul mientras se consulta al agente; al reproducir la respuesta vuelve a amarillo.

«Descansa» y otras frases reservadas terminan la conversación activa y devuelven el programa a espera de «Jarvis»; no detienen el proceso. También existen frases para solicitar apagado o reinicio, con confirmación hablada. La implementación de las frases está en [core/intents.py](core/intents.py), y las acciones de sistema en [system/power_control.py](system/power_control.py). Apagar/reiniciar depende de que el sistema operativo permita `sudo -n` para esos comandos.

### Botón físico de apagado maestro

El botón se sondea independientemente del medidor mediante [system/shutdown_button_monitor.py](system/shutdown_button_monitor.py). El monitor consulta `BUTTON STATUS` al Arduino cada 0,1 segundos; el firmware responde `BUTTON_SHUTDOWN` una sola vez por pulsación estable y `BUTTON_IDLE` en reposo. El antirrebote y la detección de flanco están en [ARDUINO/Main program/main.cs](ARDUINO/Main%20program/main.cs).

Al detectar una pulsación, el monitor activa un evento compartido con [core/conversation.py](core/conversation.py). Un hilo vigilante del orquestador espera ese evento desde el inicio de la conversación, incluso antes de seleccionar Gemini o Vento, mientras se escucha y mientras se procesa una respuesta. El apagado maestro detiene la captura del micrófono, interrumpe la síntesis/reproducción activa de Azure y `aplay`, anuncia «Apagado manual accionado!, apagando sistemas.» y llama a `poweroff`. Las operaciones para interrumpir el audio están en [speech/azure_synthesizer.py](speech/azure_synthesizer.py) y [audio/player.py](audio/player.py).

La solicitud de apagado del sistema depende de que `sudo -n /usr/sbin/poweroff` esté autorizado para el usuario que ejecuta Jarvis. El botón no solicita confirmación hablada.

## Depósito de agua pluvial

### Lectura y cálculo

El medidor Python pide al Arduino `SENSOR DISTANCE` cada **0,5 segundos**. El Arduino mide la distancia con el HC-SR04 y devuelve centímetros; el cálculo del porcentaje lo realiza Python, no Vento ni el navegador.

Los valores de calibración actuales son 80 cm para depósito vacío y 9 cm para lleno. El porcentaje se calcula linealmente entre esos extremos, se redondea a entero y se limita al intervalo 0–100 %. Las mediciones no válidas se descartan. Las lecturas correctas se imprimen en consola y se escriben de forma atómica en `state/rainwater_tank_state.json`.

### Avisos de nivel

El medidor no anuncia cada lectura. Después de la primera lectura, puede encolar un aviso porcentual cuando el nivel cambia al menos cinco puntos respecto al último nivel anunciado y han pasado al menos cinco segundos desde el aviso porcentual anterior. Además, anuncia cruces de umbral direccionales con histéresis:

- Al subir: nivel bueno desde 80 %, casi lleno desde 90 % y lleno desde 100 %.
- Al bajar: nivel bajo al cruzar hacia 20 % o menos, muy bajo al cruzar hacia 10 % o menos y vacío al cruzar por debajo de 5 %.
- Un mismo aviso de umbral se rearma al alejarse tres puntos del umbral correspondiente.

El callback envía texto a un socket Unix local mediante [notifications/announcement_client.py](notifications/announcement_client.py). El componente [notifications/announcement_service.py](notifications/announcement_service.py) consume esos mensajes en orden, usa Azure para hablarlos y activa el indicador de alerta durante la reproducción.

**Límite importante:** `main.py` inicia el cliente y puede encolar avisos, pero no inicia `AnnouncementService`. Ese receptor debe ejecutarse como proceso/servicio independiente para que los avisos se oigan. No se encontró en este repositorio una suscripción Python a alertas entrantes de Vento ni un servicio que conecte esas alertas con el receptor local. El mecanismo de encolado es local y no demuestra por sí mismo una suscripción a Vento.

### Panel web

El servidor HTTP se enlaza por defecto a `0.0.0.0:8765`, de modo que escucha en todas las interfaces de red. Expone el panel en `/` y el nivel actual en `/api/rainwater-tank/current-level`. Un dispositivo de la red puede abrir `http://<IP-de-la-Raspberry>:8765/`, sujeto a conectividad y reglas de red.

El panel muestra el porcentaje, una representación visual del depósito, la distancia y una gráfica seleccionable entre 5 minutos y 24 horas. Consulta la API cada 500 ms. **El histórico de la gráfica se guarda en `localStorage` del navegador de cada dispositivo**, no en el servidor; se pierden sus muestras si se borra el almacenamiento local o se usa otro navegador.

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

El archivo auxiliar [docs/instalar el agent en la rasberry para cuando se desconecta.txt](docs/instalar%20el%20agent%20en%20la%20rasberry%20para%20cuando%20se%20desconecta.txt) describe otro componente: descarga un agente Linux ARM64 y configura funciones de sistema, archivos, comandos y notificaciones, además de `remote_agent_mode: full-access`. Esa configuración permite inferir la intención de dar acceso amplio al agente de dispositivo, pero el repositorio no permite verificar qué proceso está instalado/ejecutándose en la Raspberry ni los permisos efectivos del usuario del sistema. No confundir esa configuración externa con el puente de voz `VentoBridge`.

Ese archivo contiene un valor con forma de clave de dispositivo. No se reproduce aquí. Si corresponde a una clave real o vigente, debe considerarse expuesta y revocarse/rotarse; los secretos deberían mantenerse fuera del repositorio.

## Configuración y credenciales

| Integración | Ruta/valor por defecto | Contenido esperado |
| --- | --- | --- |
| Azure Speech | `~/.config/jarvis-voice/azure.env` | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` |
| Gemini | `~/.config/jarvis-voice/gemini.env` | `GEMINI_API_KEY`, opcionalmente `GEMINI_MODEL` |
| Puente Vento | `state/bridge.env` | `BRIDGE_URL`, `BRIDGE_TOKEN` |
| Modelo Vosk | `models/vosk-model-small-es-0.42` | Archivos del modelo local español |
| Estado del depósito | `state/rainwater_tank_state.json` | Última medida válida, generada por el programa |

Las rutas, dispositivo de audio, puerto serie, modelo Gemini, voz Azure, intervalo de lectura y rutas de socket están centralizados en [config/settings.py](config/settings.py) y en los valores por defecto de sus clases. Este documento no contiene claves ni tokens.

## Diferencias y comprobaciones pendientes en la instalación

Estos puntos afectan a la diferencia entre el repositorio y la instalación descrita; no se han validado en hardware ni en servicios externos:

1. **Capitalización de import Arduino:** el código importa `Arduino.arduino_mega_connection`, pero la carpeta del repositorio se llama `ARDUINO`. Windows normalmente no distingue estas mayúsculas; Linux sí. En una Raspberry Pi, comprobar si el checkout real tiene otra capitalización, un enlace compatible o si el arranque falla por `ModuleNotFoundError`.
2. **Proceso de avisos:** confirmar que `python -m notifications.announcement_service` (o una unidad de servicio equivalente) se inicia junto a Jarvis. `main.py` no lo inicia.
3. **Alertas de Vento:** identificar el proceso/configuración desplegados que reciben notificaciones de Vento y llaman al cliente de avisos. No aparecen en el flujo Python del repositorio inspeccionado.
4. **LED de alerta:** contrastar el montaje físico y la versión desplegada del firmware con la declaración roja de D12.
5. **Parámetros físicos:** confirmar que el sensor está instalado y que 80 cm/9 cm y la capacidad estimada de 1000 litros corresponden al depósito real.
6. **Permisos de apagado/reinicio:** confirmar la unidad de ejecución y las reglas `sudoers`; la presencia del código no prueba que el sistema autorice esas órdenes.
7. **Seguridad de red y credenciales:** revisar si el puerto 8765 está limitado a la LAN deseada; retirar secretos del repositorio y rotar las claves que hayan quedado expuestas. El puente Vento incorpora su token en la URL de petición, por lo que también deben considerarse los registros HTTP del servicio intermedio.

## Mapa de código

- Arranque e integración de dependencias: [main.py](main.py)
- Orquestación, selección del agente y estados: [core/conversation.py](core/conversation.py)
- Comandos reservados: [core/intents.py](core/intents.py)
- Configuración y carga de credenciales: [config/settings.py](config/settings.py)
- Captura y reconocimiento local: [audio/microphone_stream.py](audio/microphone_stream.py), [speech/vosk_recognizer.py](speech/vosk_recognizer.py)
- Puentes Gemini y Vento: [bridge/gemini_bridge.py](bridge/gemini_bridge.py), [bridge/vento_bridge.py](bridge/vento_bridge.py)
- Síntesis Azure y reproducción: [speech/azure_synthesizer.py](speech/azure_synthesizer.py), [audio/player.py](audio/player.py)
- Monitor del botón de apagado maestro: [system/shutdown_button_monitor.py](system/shutdown_button_monitor.py)
- Indicadores y medidor: [Indicators/arduino_rgb_indicator.py](Indicators/arduino_rgb_indicator.py), [Indicators/arduino_alert_client.py](Indicators/arduino_alert_client.py), [Sensors/rainwater_tank_meter.py](Sensors/rainwater_tank_meter.py)
- Panel web y receptor de avisos: [Sensors/rainwater_tank_web_server.py](Sensors/rainwater_tank_web_server.py), [notifications/announcement_service.py](notifications/announcement_service.py)
- Firmware Arduino: [ARDUINO/Main program/main.cs](ARDUINO/Main%20program/main.cs)
- Control de energía: [system/power_control.py](system/power_control.py)

## Alcance de esta descripción

Esta revisión se basa en el código y configuración visibles en el repositorio. No se conectó a la Raspberry, Arduino, Azure, Gemini ni Vento; por tanto, no certifica el estado actual de esos servicios, la red, los periféricos, los procesos externos ni los permisos efectivos.