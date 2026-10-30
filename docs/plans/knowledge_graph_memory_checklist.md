# Checklist: modelos por fase y comprobaciones previas

Guía rápida para ejecutar [knowledge_graph_memory_technical_plan.md](knowledge_graph_memory_technical_plan.md). Una fase por sesión, en orden: **0 → 1 → 2 → 3 → 4 → 5 → 6**.

## Modelos y esfuerzo por fase

| Fase | Contenido | Modelo | Esfuerzo | Necesita antes |
|---|---|---|---|---|
| 0 | Comprobaciones previas (sección de abajo) | Ninguno (lo haces tú en la Pi) | – | – |
| 1 | Dominio, puerto y almacén SQLite | `claude-opus-5-5` | alto | Pasos 1 de la Fase 0 |
| 2 | Extracción y worker | `claude-opus-5-5` | alto | Fase 1 + pasos 3 y 4 de la Fase 0 |
| 3 | Sitio web con inicio y menú | `claude-sonnet-5-5` | medio | Nada |
| 4 | Visualizador en directo | `claude-sonnet-5-5` | alto | Fases 2 y 3 |
| 5 | Recuperación hacia Gemini | `claude-sonnet-5-5` | medio | Fase 2 |
| 6 | Despliegue y documentación | `claude-sonnet-5-5` | medio | Todas |

Cambiar de modelo: `/model` en Claude Code. El esfuerzo se ajusta con el selector, no desde la conversación.

**Paralelo permitido (solo estas parejas, cada una en su `git worktree`):**
- 1 y 3.
- 4 y 5.

**Nunca juntas:** 2 con 1, 4 con 3, 4 sin 2.

**Por fase:**
1. Rama nueva.
2. Sesión nueva con el modelo de la tabla.
3. Pedir: «implementa la Fase N de `knowledge_graph_memory_technical_plan.md`».
4. Tests en verde: `python -m unittest discover -s tests -t .`
5. Documentación actualizada (`CLAUDE.md`).
6. Fila de la fase actualizada en la tabla «Seguimiento de la implementación» (§12 del plan técnico): qué se hizo, qué queda pendiente (también lo arrastrado de la fase anterior) y qué deben tener en cuenta las fases siguientes.
7. Confirmar y hacer commit.

## Comprobaciones previas

### Paso 0 (PC): línea base

```bash
git switch -c feature/knowledge-graph
python -m unittest discover -s tests -t .
```

Debe dar **229 tests, 5 omitidos**.

### Paso 1 (Pi): versiones. Bloquea la Fase 1

```bash
ssh jarvis@raspberrypi.local
cd /home/jarvis/jarvis-project && source .venv/bin/activate
python --version
python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

Requisitos: Python **3.11 o superior**, SQLite **3.24 o superior**. Si Python es anterior a 3.11, avisar antes de empezar.

### Paso 2 (Pi): arranque del código refactorizado. Recomendado antes de la Fase 1

- `systemctl --user status jarvis-voice` (comando en [COMANDOS.md](../COMANDOS.md)).
- `tail -n 50 jarvis-voice.log` sin errores.
- Decir «Jarvis» y hacer una pregunta.

### Paso 3 (Pi): llamada real a Gemini con el esquema de extracción. Bloquea la Fase 2

Script de una sola vez, fuera del repositorio. No imprime la clave:

```bash
python - <<'EOF'
import json, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from jarvis.config.env_file import read_env_file

env = read_env_file(Path.home() / ".config/jarvis-voice/gemini.env")
model = env.get("GEMINI_MODEL", "gemini-2.5-flash")
S = {"type": "STRING"}
def lista(**campos):
    return {"type": "ARRAY", "items": {"type": "OBJECT", "properties": campos, "required": list(campos)}}
schema = {"type": "OBJECT", "required": ["entities", "relations", "invalidations"], "properties": {
    "entities": lista(key=S, name=S, aliases={"type": "ARRAY", "items": S},
        type={"type": "STRING", "enum": ["persona", "lugar", "proyecto", "dispositivo", "preferencia", "tarea", "evento", "concepto"]}),
    "relations": lista(source=S, target=S, type=S, fact=S),
    "invalidations": lista(source=S, target=S, type=S, reason=S)}}
payload = {
    "contents": [{"role": "user", "parts": [{"text": "Extrae el grafo de conocimiento (el usuario es la key 'usuario').\nUsuario: mi hermana se llama Ana y vive en Valencia\nAsistente: Anotado."}]}],
    "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json", "responseSchema": schema},
}
request = urllib.request.Request(
    f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model, safe='-_.')}:generateContent",
    data=json.dumps(payload).encode(), method="POST",
    headers={"Content-Type": "application/json", "x-goog-api-key": env["GEMINI_API_KEY"]})
start = time.time()
try:
    body = json.load(urllib.request.urlopen(request, timeout=60))
    print(f"modelo={model} tiempo={time.time() - start:.1f}s")
    print(json.dumps(json.loads(body["candidates"][0]["content"]["parts"][0]["text"]), ensure_ascii=False, indent=1))
except urllib.error.HTTPError as e:
    print(f"modelo={model} HTTP {e.code}: {e.read().decode()[:600]}")
EOF
```

| Resultado | Qué hacer |
|---|---|
| JSON con `ana` y las relaciones `hermana_de` y `vive_en` | Bien. Anotar el tiempo. |
| HTTP 400 mencionando `temperature` | Quitar `temperature` del extractor. |
| HTTP 400 mencionando `responseSchema` | Cambiar el formato del esquema. |
| HTTP 404 | Modelo no disponible para la cuenta: elegir otro (3.5 Flash-Lite o 3.8 Flash). |
| HTTP 429 | Cuota agotada: revisar límites antes de activar la extracción. |

Si el modelo es de la familia 2.5, repetir añadiendo `"thinkingConfig": {"thinkingBudget": 0}` dentro de `generationConfig` y comparar tiempos.

### Paso 4 (AI Studio): límites de cuota. Bloquea la Fase 2

- Anotar los límites de peticiones por minuto y por día del proyecto.
- Estimar: una llamada para conversar + una para extraer por turno, más una compactación cada cinco turnos aprox.
- Si el uso diario se acerca al límite, empezar con la extracción desactivada.

### Paso 5 (no bloquea): texto de la página de inicio

Se redacta en la Fase 3 a partir de `CONTEXTO_DEL_PROYECTO.md` y lo revisa el propietario en el navegador.

### Paso 6 (no bloquea): force-graph

No requiere acción. Se descarga en la Fase 4 y se verifica el SHA-256 anotado en el plan técnico (`f59db59b…a629`, versión 1.52.0).

## Antes de pasar a la siguiente fase

- [ ] Tests en verde.
- [ ] `python -m compileall -q jarvis main.py` sin errores.
- [ ] `CLAUDE.md` cumplido: `CONTEXTO_DEL_PROYECTO.md` actualizado.
- [ ] Tabla de seguimiento (§12 del plan técnico) actualizada.
- [ ] Confirmado por el propietario antes del commit.
