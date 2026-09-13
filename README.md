# Jarvis Voice

Asistente de voz para Raspberry Pi: escucha localmente con Vosk,
envía el texto al puente de Vento, y convierte la respuesta en voz
con Azure Speech, reproduciéndola en streaming.

Este proyecto es la versión reestructurada del script original de un
solo fichero (`jarvis_voice_conversation.py`). El *comportamiento* es
exactamente el mismo; lo que cambia es cómo está organizado el
código.

## Estructura del proyecto

```
jarvis-voice/
├── main.py                      # Punto de entrada (necesita sudo, ver abajo)
├── requirements.txt
├── config/
│   └── settings.py              # Rutas, constantes y carga de credenciales
├── core/
│   ├── interfaces.py            # Los 4 "contratos" del sistema (ver abajo)
│   ├── intents.py               # Detección de órdenes ("apaga la raspberry"...)
│   └── conversation.py          # El orquestador: la lógica de la conversación
├── audio/
│   ├── microphone_stream.py     # Captura de audio (sounddevice + cola)
│   └── player.py                # Reproducción PCM en streaming vía aplay
├── speech/
│   ├── vosk_recognizer.py       # Implementación de SpeechRecognizer con Vosk
│   └── azure_synthesizer.py     # Implementación de SpeechSynthesizer con Azure
├── bridge/
│   └── vento_bridge.py          # Implementación de AssistantBridge con Vento
├── system/
│   └── power_control.py         # Implementación de SystemController (poweroff/reboot)
├── models/                      # Aquí va el modelo de Vosk (como antes)
└── state/                       # Aquí va bridge.env (como antes)
```

Las credenciales de Azure siguen leyéndose de
`~/.config/jarvis-voice/azure.env` (fuera del proyecto, igual que
antes). No ha cambiado ningún formato de configuración.

## La idea central: interfaces + inyección de dependencias

Python no tiene `interface` como C#, pero tiene un equivalente casi
directo: una clase abstracta (`ABC`) con métodos marcados
`@abstractmethod`. Eso es exactamente lo que hay en
`core/interfaces.py`:

- `SpeechRecognizer` — voz del micrófono → texto
- `SpeechSynthesizer` — texto → voz reproducida
- `AssistantBridge` — texto → respuesta del asistente de IA
- `SystemController` — apagar / reiniciar

`core/conversation.py` (el orquestador) solo conoce estas cuatro
interfaces. No importa `vosk`, no importa `azure`, no sabe que existe
Vento. Recibe las cuatro implementaciones ya construidas en su
constructor — eso es "inyección de dependencias", solo que en Python
no hace falta un contenedor de DI como en .NET: simplemente se
construyen los objetos a mano y se pasan, en `main.py`. A eso se le
llama el **composition root**: es el único fichero que conoce todas
las clases concretas a la vez, igual que tu `Program.cs`.

### Cómo cambiar de proveedor (el caso que mencionabas)

Si mañana quieres dejar Azure Speech y usar otro servicio:

1. Crea `speech/otro_proveedor.py` con una clase que herede de
   `SpeechSynthesizer` e implemente `speak(self, text: str) -> None`.
2. En `main.py`, cambia estas líneas:
   ```python
   from speech.azure_synthesizer import AzureSpeechSynthesizer
   ...
   synthesizer = AzureSpeechSynthesizer(...)
   ```
   por:
   ```python
   from speech.otro_proveedor import OtroProveedorSynthesizer
   ...
   synthesizer = OtroProveedorSynthesizer(...)
   ```

Nada más cambia. `core/conversation.py` sigue funcionando sin tocarlo,
porque solo conoce la interfaz `SpeechSynthesizer`, no la clase
concreta. Lo mismo aplica para cambiar Vosk, Vento, o la forma de
apagar la Raspberry.

Esto también significa que puedes probar `ConversationOrchestrator`
con implementaciones falsas (sin micrófono, sin gastar cuota de
Azure). Es justo lo que hice para verificar el refactor: le pasé un
`FakeRecognizer` que devuelve frases fijas y un `FakeSynthesizer` que
solo las anota en una lista, y comprobé que el flujo de apagado,
reinicio y cierre de conversación se comporta igual que en el
original.

## Otras decisiones de Python que quizá te choquen viniendo de .NET

- **`dataclass`** (`config/settings.py`): es lo más parecido a un
  `record` de C#. `AzureCredentials` y `BridgeCredentials` son POCOs
  inmutables (`frozen=True`).
- **`from __future__ import annotations`**: al principio de varios
  ficheros. Permite usar anotaciones de tipo modernas (`list[dict]`,
  `Exception | None`) sin que Python las evalúe en tiempo de
  ejecución, lo que mantiene el código compatible con Raspberry Pi OS
  aunque lleve una versión de Python algo más antigua.
- No hay `namespace`: cada carpeta con un `__init__.py` es un paquete,
  y los imports son por ruta (`from speech.vosk_recognizer import
  VoskSpeechRecognizer`), similar a un `using MiApp.Speech;` pero
  atado a la estructura de carpetas real.
- Los métodos "privados" de una clase se marcan por convención con un
  guion bajo (`self._microphone`), no hay `private` real como en C#;
  es una convención que todo el mundo respeta pero que el intérprete
  no obliga.

## Permisos de sudo (tu pregunta sobre el fichero con permisos)

**El fichero que debe tener el permiso especial ahora es `main.py`.**

Antes todo el código —incluida la llamada a `sudo poweroff`— estaba en
un único fichero, así que la regla de `sudoers` (o el servicio de
systemd) apuntaba a ese fichero. Ahora esa misma llamada vive en
`system/power_control.py`, pero **se ejecuta como parte del mismo
proceso que arranca `main.py`**, así que el permiso sigue
concediéndose sobre el proceso que lanza `main.py`, no sobre un
fichero suelto.

Dos casos típicos, según cómo lo tengas montado:

- Si tienes una entrada en `/etc/sudoers` (o en
  `/etc/sudoers.d/jarvis`) del tipo:
  ```
  pi ALL=(ALL) NOPASSWD: /usr/sbin/poweroff, /usr/sbin/reboot
  ```
  no depende de la ruta del script en absoluto, sino del usuario que
  lo ejecuta — no hay que tocar nada.

- Si en tu unidad de systemd (`ExecStart=`) apuntabas directamente al
  fichero antiguo, actualiza esa línea para que apunte a
  `/ruta/al/proyecto/jarvis-voice/main.py`.

## Puesta en marcha

```bash
cd jarvis-voice
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Coloca aquí el modelo de Vosk, como antes:
#   models/vosk-model-small-es-0.42/

# Credenciales de Azure, como antes:
#   ~/.config/jarvis-voice/azure.env
#     AZURE_SPEECH_KEY=...
#     AZURE_SPEECH_REGION=...

# Credenciales del puente de Vento, como antes:
#   state/bridge.env
#     BRIDGE_URL=...
#     BRIDGE_TOKEN=...

python3 main.py
```

## Cuando llegue Arduino

Cuando añadas los sensores, te recomiendo seguir el mismo patrón: una
carpeta `sensors/` con una interfaz `SensorReader` (o una por tipo de
sensor) en `core/interfaces.py`, y una implementación concreta que
hable con Arduino (por serie, I2C, lo que uses). El orquestador
(`ConversationOrchestrator`, o uno nuevo si los sensores no tienen que
ver con la conversación) recibiría esa interfaz igual que recibe hoy
`SpeechRecognizer` o `AssistantBridge`. Así el "monstruo" no vuelve:
cada pieza nueva entra como una implementación más de un contrato
conocido, no como código pegado al resto.
