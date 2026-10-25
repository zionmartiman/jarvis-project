# Jarvis

Asistente de voz para una Raspberry Pi 3B con un Arduino Mega. Escucha en local con Vosk,
envía el texto a un asistente de IA (Gemini por defecto, Vento como alternativa), responde en voz
con Azure Speech y vigila un depósito de agua pluvial con un sensor ultrasónico.

Contexto completo del sistema: [docs/CONTEXTO_DEL_PROYECTO.md](docs/CONTEXTO_DEL_PROYECTO.md).
Comandos de uso en la Raspberry: [docs/COMANDOS.md](docs/COMANDOS.md).

## Arquitectura

Todo el código está en el paquete `jarvis/`, organizado por capas. Las dependencias van de fuera
hacia dentro y nunca al revés:

```text
bootstrap  ->  infrastructure  ->  ports  <-  application  ->  domain
                      +----------------------------------->  domain
```

| Capa | Contenido |
| --- | --- |
| `jarvis/domain/` | Python puro: estados, intenciones, frases habladas, reglas del depósito. |
| `jarvis/ports/` | Interfaces (`ABC`) que necesita la aplicación: micrófono, reconocedor, sintetizador, asistente, luces, botones, sensor, energía, memoria, avisos. |
| `jarvis/application/` | Casos de uso: conversación, monitor del depósito, monitor de botones, memoria. Solo importa `domain` y `ports`. |
| `jarvis/infrastructure/` | Implementaciones concretas: Vosk, Azure, Gemini, Vento, Arduino, sockets Unix, servidor web, ficheros. |
| `jarvis/bootstrap/` | Único lugar que conoce las clases concretas y lee la configuración (`build_application`). |
| `jarvis/config/` | Rutas, ajustes y carga de credenciales. |
| `jarvis/services/`, `jarvis/cli/` | Receptor de avisos y su CLI, ejecutables como procesos independientes. |

Otros directorios: `main.py` (entrada), `prompts/system.md` (prompt de sistema de Gemini),
`ARDUINO/main.cs` (firmware, solo para flashear la placa), `models/` (modelo de Vosk), `state/`
(credenciales y estado local, fuera de Git), `docs/` y `tests/`.

## Instalación

```bash
cd /home/jarvis/jarvis-project
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Ficheros privados que hay que crear en cada equipo (no están en Git):

| Fichero | Contenido |
| --- | --- |
| `~/.config/jarvis-voice/azure.env` | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` |
| `~/.config/jarvis-voice/gemini.env` | `GEMINI_API_KEY` (opcional `GEMINI_MODEL`) |
| `state/bridge.env` | `BRIDGE_URL`, `BRIDGE_TOKEN` (plantilla: `state/bridge.env.example`) |

El modelo de Vosk va en `models/vosk-model-small-es-0.42/`.

## Ejecución

```bash
python main.py
```

Di «Jarvis», espera el «Dime» y habla. «Cambiar de modelo» alterna entre Gemini y Vento; «descansa»
vuelve a la espera. El apagado y el reinicio por voz (y el botón físico) usan `sudo -n` para
`poweroff`/`reboot`, así que el usuario que ejecuta Jarvis necesita esa regla en `sudoers`.

Los avisos hablados del depósito necesitan el receptor, que se ejecuta aparte:

```bash
python -m jarvis.services.announcement_service
python -m jarvis.cli.announce --base64 "$(echo -n 'Prueba de aviso' | base64)"
```

## Tests

Se ejecutan en el PC de desarrollo (no necesitan `vosk`, `sounddevice`, `azure` ni `serial`):

```bash
python -m unittest discover -s tests -t .
python -m compileall -q jarvis main.py
```

`tests/unit/test_import_case.py` comprueba que los imports coinciden con los nombres reales de
fichero distinguiendo mayúsculas, porque Windows no lo hace y Linux sí.

## Añadir un proveedor nuevo

Para cambiar, por ejemplo, la síntesis de voz:

1. Crea una clase en `jarvis/infrastructure/` que herede del puerto de `jarvis/ports/` (aquí
   `SpeechSynthesizer` o `PlaybackAwareSynthesizer`, en `jarvis/ports/speech.py`) e implemente sus
   métodos.
2. En `jarvis/bootstrap/app.py` (`build_application`), construye la clase nueva en lugar de
   `AzureSpeechSynthesizer`.
3. Añade tests en `tests/unit/infrastructure/` con un doble de la librería externa.

La capa de aplicación no cambia: solo conoce el puerto. Lo mismo vale para el reconocedor, el
asistente de IA (`AssistantBridge`), los botones o el sensor de distancia. Para un asistente nuevo,
añade además su valor a `AssistantModel` (`jarvis/domain/assistant_model.py`) y su construcción en
`jarvis/bootstrap/assistants.py`.
