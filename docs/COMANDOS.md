# COMANDOS

Ruta real: /home/jarvis/jarvis-project/docs/COMANDOS.md
Ruta relativa del Desktop Agent: jarvis-project/docs/COMANDOS.md

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
cd /home/jarvis/jarvis-project
```

## Entorno Python

```bash
cd /home/jarvis/jarvis-project
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
tail -f /home/jarvis/jarvis-project/jarvis-voice.log
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

Si aparece `TabError: inconsistent use of tabs and spaces in indentation`, el traceback del log indica el fichero y la línea. Muestra el contexto (por ejemplo, la línea 647 de `main.py`):

```bash
nl -ba /home/jarvis/jarvis-project/main.py | sed -n '640,675p'
```

Abre directamente esa línea:

```bash
nano +647 /home/jarvis/jarvis-project/main.py
```

En nano también puedes pulsar Ctrl+_ (en algunos teclados Ctrl+Shift+-), escribir el número de línea y pulsar Enter. Revisa que la sangría use espacios de forma consistente.

Valida la sintaxis de todo el código antes de reiniciar:

```bash
/home/jarvis/jarvis-project/.venv/bin/python -m compileall -q /home/jarvis/jarvis-project/jarvis /home/jarvis/jarvis-project/main.py
```

Si no muestra ningún mensaje, la sintaxis es correcta. Entonces reinicia el servicio:

```bash
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user restart jarvis-voice
```

Si vuelve a fallar:

```bash
tail -n 50 /home/jarvis/jarvis-project/jarvis-voice.log
```

## Servicio de avisos

`main.py` no inicia el receptor de avisos; se ejecuta aparte (idealmente como otra unidad de systemd):

```bash
python -m jarvis.services.announcement_service
```

Para encolar un aviso desde otro proceso:

```bash
python -m jarvis.cli.announce --base64 "$(echo -n 'Prueba de aviso' | base64)"
```

Los módulos antiguos `notifications.announcement_service` y `notifications.announcement_client` siguen existiendo como shims deprecados hasta que la unidad de la Raspberry y el llamador de alertas de Vento usen los módulos `jarvis.*`.

## Tests en el PC de desarrollo

```bash
python -m unittest discover -s tests -t .
python -m compileall -q jarvis main.py
```

## Detener e iniciar

```bash
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user stop jarvis-voice
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user start jarvis-voice
```

## Sincronizar con la Raspberry

Traer los cambios de la Raspberry al PC (Windows). Sobrescribe los ficheros locales con el mismo nombre, así que ejecútalo con el árbol de trabajo limpio (`git status`):

```bash
scp -r jarvis@raspberrypi.local:/home/jarvis/jarvis-project/* "C:\Repositories\jarvis-project"
```

El mismo comando está en `scripts/hacer pull desde la raspberry.bat`. La ruta remota coincide con la carpeta del proyecto en la Raspberry (`/home/jarvis/jarvis-project`); el servicio de systemd y las credenciales en `~/.config/jarvis-voice/` conservan el nombre `jarvis-voice`.

## Reiniciar o apagar

```bash
sudo reboot
sudo poweroff
```

No ejecutes el script manual y el servicio a la vez: competirían por el micrófono.
