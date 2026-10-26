# Comandos: instalación en la Raspberry y memoria en grafo (SQLite)

Chuleta con los comandos que se han usado para instalar el entorno y para trabajar con la base de datos `state/knowledge_graph.sqlite3`. Todos se ejecutan en la Raspberry salvo que se indique lo contrario. Para el resto de comandos (servicio, audio, logs) ver [COMANDOS.md](COMANDOS.md).

## 1. Instalación del entorno (tras copiar la carpeta)

### 1.1 Paquetes del sistema (con `sudo`, cualquier usuario con permisos)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip libportaudio2 alsa-utils
```

### 1.2 Comprobar Python y SQLite

```bash
python3 --version
python3 -c "import sqlite3; print(sqlite3.sqlite_version)"
```

El módulo `sqlite3` viene con Python, no hace falta instalarlo aparte.

### 1.3 Entorno virtual (como usuario `jarvis`, sin `sudo`)

```bash
sudo -iu jarvis
cd /home/jarvis/jarvis-project
rm -rf .venv                  # por si se copió una .venv de otro equipo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

No usar `pip install --break-system-packages`. Si la `.venv` se creó con `sudo`, bórrala y créala como `jarvis`.

### 1.4 Comprobar que las librerías cargan

```bash
python -c "import sqlite3, sounddevice, vosk, serial, azure.cognitiveservices.speech; print('OK')"
```

### 1.5 Tests (opcional, recomendado tras instalar)

```bash
cd /home/jarvis/jarvis-project
source .venv/bin/activate
python -m unittest discover -s tests -t .
```

### 1.6 Ficheros privados (no van en Git)

```bash
ls -l ~/.config/jarvis-voice/ state/
```

Deben existir `azure.env`, `gemini.env` y `state/bridge.env`. El modelo de Vosk debe estar en `models/vosk-model-small-es-0.42/`.

## 2. Parar y arrancar el servicio

```bash
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user stop jarvis-voice
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user start jarvis-voice
sudo -u jarvis XDG_RUNTIME_DIR=/run/user/$(id -u jarvis) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u jarvis)/bus systemctl --user restart jarvis-voice
```

Parar el servicio antes de usar `--reset` o de restaurar `conversation.jsonl`.

## 3. Memoria en grafo: CLI (`rebuild_graph` y `merge_entities`)

Desde la raíz del proyecto, con el entorno activado:

```bash
cd /home/jarvis/jarvis-project
source .venv/bin/activate
```

### 3.1 Encolar el JSONL y procesarlo

```bash
python -m jarvis.cli.rebuild_graph --process
```

Encola el resumen y los intercambios de `state/conversation.jsonl` y los procesa (una llamada a Gemini por elemento). Sin `--process` solo los encola.

### 3.2 Empezar con un grafo limpio

```bash
python -m jarvis.cli.rebuild_graph --reset --process
```

Guarda el grafo actual como `state/knowledge_graph.sqlite3.<fecha>.bak` y reconstruye desde el JSONL. Parar el servicio antes.

### 3.3 Reintentar tareas fallidas

```bash
python -m jarvis.cli.rebuild_graph --retry-failed --process
```

Vuelve a poner como pendientes las tareas que fallaron cinco veces. No vuelve a encolar el JSONL.

### 3.4 Fusionar una entidad duplicada

```bash
python -m jarvis.cli.merge_entities ana_garcia ana
```

Fusiona `ana_garcia` en `ana` (por clave o alias) y muestra los eventos generados.

## 4. Consultar la base de datos (SQLite)

Desde la raíz del proyecto, con el entorno activado.

### 4.1 Entidades y relaciones

```bash
python -c "import sqlite3; c=sqlite3.connect('state/knowledge_graph.sqlite3'); print(c.execute('SELECT id,key,name,type FROM entities').fetchall()); print(c.execute('SELECT source_id,type,target_id,fact_text,valid_to FROM relations').fetchall())"
```

### 4.2 Últimos eventos (versión, fecha, operación y datos)

```bash
python -c "import sqlite3; c=sqlite3.connect('state/knowledge_graph.sqlite3'); [print(r) for r in c.execute('SELECT version, ts, op, payload_json FROM events ORDER BY version DESC LIMIT 10')]"
```

### 4.3 Recuento de entidades y estado de la cola

```bash
python -c "import sqlite3; c=sqlite3.connect('state/knowledge_graph.sqlite3'); print(c.execute('SELECT COUNT(*) FROM entities').fetchone(), c.execute('SELECT status, COUNT(*) FROM extraction_queue GROUP BY status').fetchall())"
```

### 4.4 Copia de seguridad consistente

Usa la API de backup de SQLite, válida con Jarvis en marcha. No copies el fichero a mano.

```bash
python -c "import sqlite3; s=sqlite3.connect('state/knowledge_graph.sqlite3'); d=sqlite3.connect('state/knowledge_graph.sqlite3.copia.bak'); s.backup(d)"
```

Para la copia de `docs/COMANDOS.md` se usa `/tmp/kg.bak`; aquí se deja dentro de `state/` para que quede en el mismo disco.

### 4.5 Tamaño y medidas

```bash
ls -l state/knowledge_graph.sqlite3*
ps -o rss,cmd -C python
grep "Knowledge extraction took" jarvis-voice.log | tail
```

## 5. Historial de conversación (`state/conversation.jsonl`)

### 5.1 Ver cuántas entradas tiene y su inicio

```bash
wc -l state/conversation.jsonl
head -c 3000 state/conversation.jsonl
```

### 5.2 Restaurar el historial desde Git (en el PC, PowerShell o Git Bash)

El fichero se quitó del índice en el commit `7e46e0f`; su última versión está en el commit anterior.

```bash
git show 7e46e0f^:state/conversation.jsonl > conversation_recuperado.jsonl
scp conversation_recuperado.jsonl jarvis@raspberrypi.local:/home/jarvis/jarvis-project/state/
```

La versión de `conversation.jsonl.bak` del mismo commit se puede recuperar igual (`git show 7e46e0f^:state/conversation.jsonl.bak`), pero el principal ya contiene el resumen más reciente.

### 5.3 Importar el historial al grafo limpio (en la Raspberry, con el servicio parado)

```bash
cd /home/jarvis/jarvis-project
source .venv/bin/activate
cp state/conversation.jsonl state/conversation.jsonl.actual      # copia de seguridad de lo actual
mv state/conversation_recuperado.jsonl state/conversation.jsonl
python -m jarvis.cli.rebuild_graph --reset --process
```

Si ha habido conversaciones desde que se copió la carpeta, están en `conversation.jsonl.actual`; no se pierden, pero hay que volver a importarlas a mano.

## 6. Orden recomendado para una instalación nueva

1. Sección 1 (instalar el entorno y comprobar las librerías).
2. Sección 2 (parar el servicio si está en marcha).
3. Sección 5.3 (restaurar el historial e importarlo con `--reset`), cuando se quiera el grafo con datos.
4. Sección 2 (arrancar el servicio) y revisar `/memoria` en `http://<IP-de-la-Raspberry>:8765/memoria`.
