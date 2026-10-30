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

## Memoria en grafo

La base de datos es `state/knowledge_graph.sqlite3` y se crea al arrancar Jarvis. Con `MemorySettings.storage` en `MemorySource.GRAPH` o `BOTH` (en `jarvis/config/settings.py`, como está ahora: `BOTH`) Jarvis extrae cada intercambio por su cuenta; estas CLI sirven para importar el historial y para corregir el grafo a mano. Si `storage` no incluye el grafo, Jarvis no encola nada ni llama a Gemini. `MemorySettings.retrieval` decide de dónde recupera Gemini (`CONVERSATION_LOG`, `GRAPH`, `BOTH` o `NONE`); tras cambiar cualquiera de las dos hay que reiniciar el servicio. Se ejecutan desde la carpeta del proyecto con el entorno activado:

```bash
cd /home/jarvis/jarvis-project
source .venv/bin/activate
```

Encolar el último resumen y los intercambios de `state/conversation.jsonl` y procesarlos ya (una llamada a Gemini por elemento):

```bash
python -m jarvis.cli.rebuild_graph --process
```

Sin `--process` solo se encolan: Jarvis los procesará cuando la extracción esté activada. Otras opciones:

- `--reset`: guarda una copia en `state/knowledge_graph.sqlite3.<fecha>.bak` y empieza un grafo vacío. Detén antes el servicio para que Jarvis no escriba a la vez.
- `--retry-failed`: vuelve a poner como pendientes las tareas que fallaron cinco veces, sin volver a encolar el JSONL. Se combina con `--process`.

Fusionar una entidad duplicada en otra (por clave o alias); muestra los eventos que genera:

```bash
python -m jarvis.cli.merge_entities ana_garcia ana
```

Ver el grafo en directo en el navegador (cualquier equipo de la red):

```text
http://<IP-de-la-Raspberry>:8765/memoria
```

Inicio: `/`; depósito: `/deposito`. Por línea de comandos: `curl http://localhost:8765/api/memory/graph` (snapshot), `curl "http://localhost:8765/api/memory/events?since=0&limit=100"` (eventos) y `curl -N http://localhost:8765/api/memory/stream?since=0` (SSE; Ctrl+C para salir). El grafo cambia en la página mientras `rebuild_graph --process` o Jarvis escriben en la base de datos (los cambios de otro proceso tardan hasta 1 s en verse).

### Copia de seguridad y medidas

Copia consistente de la base de datos (usa la API de backup de SQLite, válida con Jarvis en marcha):

```bash
cd /home/jarvis/jarvis-project
source .venv/bin/activate
python -c "import sqlite3; s=sqlite3.connect('state/knowledge_graph.sqlite3'); d=sqlite3.connect('/tmp/kg.bak'); s.backup(d)"
```

Medidas de la Fase 6 (tras unos días con la extracción activada):

```bash
# Memoria (RSS en KB) del proceso de Jarvis
ps -o rss,cmd -C python
# Tamaño de la base de datos y sus ficheros -wal y -shm
ls -l state/knowledge_graph.sqlite3*
# Entidades, relaciones vigentes y tareas de la cola por estado
python -c "import sqlite3; c=sqlite3.connect('state/knowledge_graph.sqlite3'); print(c.execute('SELECT COUNT(*) FROM entities').fetchone(), c.execute('SELECT status, COUNT(*) FROM extraction_queue GROUP BY status').fetchall())"
# Latencia de cada extracción (INFO: "Knowledge extraction took …s, +N events")
grep "Knowledge extraction took" jarvis-voice.log | tail
```

### Despliegue por fases en la Raspberry (Fase 6)

Las dos llaves (`storage` y `retrieval`, en `MemorySettings` de `jarvis/config/settings.py`) se activan una a una, cada una con un commit del propietario; abajo, «extraction» es `storage` incluyendo el grafo y «retrieval» es `retrieval` incluyendo el grafo:

1. Con ambos a `False`: arrancar el servicio, comprobar que el log no tiene errores y que `/`, `/deposito` y `/memoria` responden.
2. `python -m jarvis.cli.rebuild_graph --process`; revisar el grafo en `/memoria` y fusionar duplicados con `merge_entities`.
3. `storage=MemorySource.BOTH` (o `GRAPH`). Probar «mi hermana se llama Ana y vive en Valencia» y después «Ana se ha mudado a Madrid»; la relación antigua debe salir discontinua en `/memoria`.
4. `retrieval=MemorySource.BOTH` (o `GRAPH`). Preguntar «¿dónde vive mi hermana?» y comprobar los hechos enviados con el logger `jarvis.application.knowledge` a nivel DEBUG (Valencia ya no debe enviarse tras la mudanza).
5. Tomar las medidas de arriba y decidir `extraction_thinking` y si se puede omitir el resumen JSONL cuando hay hechos del grafo.

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
