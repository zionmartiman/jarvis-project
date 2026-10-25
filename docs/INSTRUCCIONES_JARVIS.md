# Instrucciones de Jarvis

## Acceso por SSH

```bash
ssh jarvis@raspberrypi.local
```

La contraseña del usuario `jarvis` no se guarda en el repositorio.

## Uso de recursos

```bash
htop
```

## Servicio

```bash
jarvis-service daemon-reload
jarvis-service restart jarvis-voice
jarvis-service start jarvis-voice
jarvis-service stop jarvis-voice
jarvis-service status jarvis-voice
```

## Ver logs

```bash
tail -f /home/jarvis/jarvis-voice/jarvis-voice.log
```

## Frases reservadas

La lista autoritativa está en [core/intents.py](../core/intents.py). Se comparan sin mayúsculas, tildes ni signos.

**Dejar de escuchar** (vuelve a esperar «Jarvis»):
«buenas noches», «pausar», «pausate», «pausar conversacion», «espera», «esperate», «descansa».

**Reiniciar la Raspberry** (pide confirmación):
«reinicia la raspberry», «reiniciar la raspberry», «reinicia el sistema», «reiniciar el sistema», «reiniciate», «reinicia».

**Apagar la Raspberry** (pide confirmación):
«apaga la raspberry», «apagar la raspberry», «apaga el sistema», «apagar el sistema», «apagate», «apagar».

**Confirmaciones**:
«si», «dale», «confirmo», «confirmar», «adelante», «claro».

**Cambiar de agente**:
«cambiar de modelo» (alterna entre Gemini y Vento).
