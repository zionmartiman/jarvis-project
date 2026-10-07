# COMANDOS

Ruta real: /home/jarvis/jarvis-voice/COMANDOS.md
Ruta relativa del Desktop Agent: jarvis-voice/COMANDOS.md

## Volver de root a jarvis

Comprueba el usuario:
```bash
whoami
```
Si aparece root:
```bash
exit
```
También puedes entrar directamente:
```bash
sudo -iu jarvis
cd /home/jarvis/jarvis-voice
```

## Entorno Python

```bash
cd /home/jarvis/jarvis-voice
source .venv/bin/activate
```
Para salir: `deactivate`.

## Recargar el servicio

Úsalo si modificas el fichero `.service`:
```bash
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user daemon-reload
```

## Reiniciar Jarvis

Úsalo tras modificar el script Python o su configuración:
```bash
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user restart jarvis-voice
```

## Estado y conversación en directo

```bash
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user status jarvis-voice
tail -f /home/jarvis/jarvis-voice/jarvis-voice.log
```
Salir de `tail`: Ctrl+C. Esto no detiene Jarvis.

## Audio

```bash
arecord -l
aplay -l
arecord -D plughw:2,0 -d 5 -f cd prueba.wav
aplay -D plughw:1,0 prueba.wav
```

## Corregir TabError de Python

Si aparece `TabError: inconsistent use of tabs and spaces in indentation`, muestra el contexto:

```bash
nl -ba /home/jarvis/jarvis-voice/jarvis_voice_conversation.py | sed -n '640,675p'
```

Abre directamente la línea indicada (por ejemplo, la 647):

```bash
nano +647 /home/jarvis/jarvis-voice/jarvis_voice_conversation.py
```

En nano también puedes pulsar Ctrl+_ (en algunos teclados Ctrl+Shift+-), escribir el número de línea y pulsar Enter. Revisa que la sangría use espacios de forma consistente.

Valida la sintaxis antes de reiniciar:

```bash
/home/jarvis/jarvis-voice/.venv/bin/python -m py_compile /home/jarvis/jarvis-voice/jarvis_voice_conversation.py
```

Si no muestra ningún mensaje, la sintaxis es correcta. Entonces reinicia el servicio:

```bash
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user restart jarvis-voice
```

Si vuelve a fallar:

```bash
tail -n 50 /home/jarvis/jarvis-voice/jarvis-voice.log
```

## Detener e iniciar

```bash
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user stop jarvis-voice
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user start jarvis-voice
```

## Reiniciar o apagar

```bash
sudo reboot
sudo poweroff
```

No ejecutes el script manual y el servicio a la vez: competirían por el micrófono.
