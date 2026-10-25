# Jarvis Voice ↔ Vento: checklist de diagnóstico

Fecha: 2026-09-11

> **Nota (refactor):** el código se reorganizó en el paquete `jarvis/`. El programa se arranca con `main.py` (antes `jarvis_voice.py`), el puente con Vento es `jarvis/infrastructure/assistants/vento.py` (`VentoAssistant`, lee `state/bridge.env`) y el script `test_bridge_inspect.py` ya no existe: la prueba aislada se hace con el fragmento de «Diagnóstico del puente de texto». La carpeta del proyecto en la Raspberry es `/home/jarvis/jarvis-project`; el servicio sigue llamándose `jarvis-voice`.

Objetivo: Raspberry Pi 3B como interfaz de voz del agente `jarvis_home`.

## Flujo que funciona

```
Micrófono USB
  → Vosk local (palabra «Jarvis» + transcripción)
  → main.py (jarvis/)
  → puente Vento autenticado
  → jarvis_home
  → respuesta de texto
  → Azure Speech
  → auriculares USB
```

El audio del micrófono se procesa localmente. Solo se envía a Vento el texto ya transcrito. Azure Speech recibe el texto de la respuesta para sintetizarlo.

## Ubicaciones importantes

- Aplicación: `/home/jarvis/jarvis-project/main.py` (código en `/home/jarvis/jarvis-project/jarvis/`)
- Puente de Vento: `/home/jarvis/jarvis-project/jarvis/infrastructure/assistants/vento.py`
- Servicio de usuario: `/home/jarvis/.config/systemd/user/jarvis-voice.service`
- Credenciales/configuración privada: `/home/jarvis/jarvis-project/state/bridge.env`
- Configuración privada de Azure: `/home/jarvis/.config/jarvis-voice/azure.env`

No copiar, mostrar ni subir el contenido de los archivos `.env`.

## Antes de probar

1. Detener el servicio si se va a ejecutar el script manualmente:

   ```bash
   systemctl --user stop jarvis-voice
   ```

2. Entrar como usuario normal y activar el entorno Python:

   ```bash
   sudo -iu jarvis
   cd /home/jarvis/jarvis-project
   source .venv/bin/activate
   ```

3. Confirmar que se usa el Python aislado:

   ```bash
   which python
   which pip
   ```

   Ambos deben apuntar a `/home/jarvis/jarvis-project/.venv/bin/`.

## Diagnóstico del puente de texto

Ejecutar primero la prueba sin micrófono ni síntesis de voz:

```bash
cd /home/jarvis/jarvis-project
source .venv/bin/activate
python - <<'EOF'
from pathlib import Path
from jarvis.config.credentials import load_vento_credentials
from jarvis.domain.conversation import ConversationContext
from jarvis.infrastructure.assistants.vento import VentoAssistant

credentials = load_vento_credentials(Path("state/bridge.env"))
print(VentoAssistant(credentials, history_limit=6).ask("¿Qué hora es?", ConversationContext()))
EOF
```

Debe imprimir una respuesta legible de Jarvis; si falla, la excepción incluye el código HTTP. Si no funciona, conservar el código HTTP y el cuerpo de respuesta, pero ocultar siempre tokens y claves.

## Problemas encontrados y solución

| Síntoma | Causa real | Solución |
|---|---|---|
| `Invalid number of channels` al abrir el micro | `sounddevice` usa su propia numeración PortAudio; el número ALSA 2 no era el dispositivo de entrada | Usar `device=1` para los Plantronics actuales. Confirmar con `python -c "import sounddevice as sd; print(sd.query_devices())"`. |
| La alarma de Vento no sonaba en auriculares USB | El sistema usaba otra salida predeterminada | El script debe reproducir explícitamente con `aplay -D plughw:1,0`. |
| `externally-managed-environment` al usar pip | Se ejecutó pip global, fuera de `.venv` | Activar el entorno y usar `python -m pip install ...`; nunca usar `--break-system-packages`. |
| Piper era demasiado lento | La Pi 3B tarda en cargar/sintetizar modelos locales | Se sustituyó la salida de voz por Azure Speech. |
| Error 404 al descargar una voz Piper | Se asumió un nombre de modelo inexistente | Consultar voces disponibles antes de descargar. |
| El servicio decía «he tenido un problema» | El cliente esperaba JSON, pero el puente podía devolver texto plano | Aceptar respuesta de texto plano o JSON (hoy lo hace `vento_reply_parser.py`). |
| HTTP 200 sin respuesta útil | La autenticación/configuración del puente no era la misma que en la prueba funcional | Usar exactamente el archivo privado `state/bridge.env` que usa `VentoAssistant`. |
| Dudas sobre si era imposible hablar con Jarvis | Se confundieron una ruta no autenticada y el contrato real del puente | Validar siempre con la prueba aislada antes de concluir que una integración no existe. |

## Ejecutar Jarvis en primer plano

```bash
sudo -iu jarvis
cd /home/jarvis/jarvis-project
source .venv/bin/activate
python main.py
```

Decir «Jarvis», esperar la confirmación y hablar. Detener con `Ctrl+C`.

## Volver al arranque automático

Cuando la prueba manual funcione:

```bash
systemctl --user enable --now jarvis-voice
systemctl --user status jarvis-voice
sudo loginctl enable-linger jarvis
```

Para ver registros:

```bash
journalctl --user -u jarvis-voice -f
```

## Al cambiar micro o altavoces

1. Conectar el nuevo hardware.
2. Ejecutar:

   ```bash
   arecord -l
   aplay -l
   python -c "import sounddevice as sd; print(sd.query_devices())"
   ```

3. Actualizar solo el dispositivo de entrada de `sounddevice` y la salida de `aplay`.
4. Probar grabación y reproducción antes de iniciar Jarvis.
5. Reiniciar el servicio.

## Regla de depuración

Cambiar una sola capa cada vez: audio → Vosk → puente de texto → Azure Speech → servicio. Nunca depurar todas juntas.
