# Plan: instrucciones de sistema para Gemini en Jarvis

## Objetivo

Hacer que Gemini reciba un texto base de instrucciones al iniciar la conversación, para que siempre responda con el comportamiento esperado de Jarvis: español, tono de voz, límites de seguridad, reglas de servicio, y manejo del contexto del asistente doméstico.

## Investigación rápida

### 1) Cómo se integra Gemini en este proyecto ahora

El puente actual en [bridge/gemini_bridge.py](../bridge/gemini_bridge.py) construye una llamada REST a:

```python
https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
```

y envía el payload con:

```python
{
  "contents": [...],
  "generationConfig": {"temperature": 0.7}
}
```

Esto significa que la lógica de instrucciones no está integrada todavía; el modelo recibe solo la conversación actual y el mensaje nuevo.

### 2) Cómo se pasa la instrucción de sistema

La documentación oficial de Gemini indica que la forma recomendada de fijar comportamiento global es usar la instrucción del sistema. En la API moderna se suele ver como `system_instruction`, y en el payload REST de la API `generateContent` suele ir como `systemInstruction` (campo con formato de partes).

La forma práctica es:

```json
{
  "systemInstruction": {
    "parts": [{"text": "...instrucciones de comportamiento..."}]
  },
  "contents": [
    {"role": "user", "parts": [{"text": "Hola"}]}
  ],
  "generationConfig": {
    "temperature": 0.7
  }
}
```

Esto aplica a la misma conversación actual y se mantiene para cada turno sin meterlo repetidamente en el prompt del usuario.

### 3) Qué conviene usar aquí

Para este proyecto, la decisión más simple y robusta es:

- usar un fichero de texto con nombre `system.md` o `agent.md`
- cargarlo al arrancar la app
- inyectarlo en `GeminiBridge` como `systemInstruction` del payload
- mantener el historial de chat como ahora, sin sobrecargar cada mensaje con la misma instrucción

## Recomendación de diseño

### Archivo base para las instrucciones

Crear un archivo como:

- `config/system.md` (recomendado para la personalidad del asistente)
- o `config/agent.md` (si se quiere un nombre más general)

Contenido tipo:

```md
# Sistema de Jarvis

Eres Jarvis, un asistente de voz para un hogar inteligente.

Reglas:
- Responde siempre en español.
- Habla de manera natural, breve y clara.
- Si el usuario te pregunta por algo físico o de electrónica, responde con sentido común y precisión.
- Antes de ejecutar acciones críticas, confirma si el usuario lo desea.
- Si no sabes algo, dilo de forma honesta y ofrece una ayuda útil.
- No menciones que eres un modelo o una IA a menos que te lo pidan.
- Mantén un tono cercano, respetuoso y con cierta personalidad "señor".
```

Este fichero no debe ser texto de usuario; es la cromada del comportamiento del agente.

## Plan de integración en el código

### Fase 1: crear la fuente de instrucciones

- Añadir un archivo `config/system.md` o `config/agent.md` con las instrucciones base.
- Dejarlo dentro de la estructura de configuración para que sea fácil versionarlo.
- Añadir una pequeña función de carga que lea el archivo y devuelva su contenido limpio.

Ejemplo de acceso:

```python
from pathlib import Path

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system.md"

def load_system_prompt() -> str:
    if not SYSTEM_PROMPT_PATH.exists():
        return ""
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
```

### Fase 2: inyectarlo en el puente Gemini

Modificar [bridge/gemini_bridge.py](../bridge/gemini_bridge.py) para que el constructor reciba el texto del system prompt.

Pseudocódigo:

```python
class GeminiBridge(AssistantBridge):
    def __init__(self, credentials: GeminiCredentials, history_limit: int,
                 timeout_seconds: int = 130, system_prompt: str = ""):
        self._credentials = credentials
        self._history_limit = history_limit
        self._timeout_seconds = timeout_seconds
        self._system_prompt = system_prompt.strip()
```

Y en `ask()`:

```python
payload = {
    "contents": contents,
    "generationConfig": {"temperature": 0.7},
}

if self._system_prompt:
    payload["systemInstruction"] = {
        "parts": [{"text": self._system_prompt}]
    }
```

### Fase 3: conectar la carga desde arranque

En [main.py](../main.py) o en la fábrica de puentes, pasar el contenido del archivo al constructor de `GeminiBridge`:

```python
from config.settings import load_gemini_credentials
from config.system_prompt import load_system_prompt


def build_bridge(model: str):
    if model == "gemini":
        return GeminiBridge(
            load_gemini_credentials(),
            settings.MAX_HISTORY_ITEMS,
            system_prompt=load_system_prompt(),
        )
```

Esta solución mantiene la política del sistema separada del código y hace que el prompt sea editable sin tocar la lógica del puente.

### Fase 4: mantenerlo escalable

Se recomienda dejar una estructura tipo:

```text
config/
  system.md
  agent.md
  system_prompt.py
```

Y definir claramente:

- `system.md`: personalidad y comportamiento del asistente
- `agent.md`: límite operativo, estilo de respuesta y reglas de conversación
- `system_prompt.py`: loader y validación

## Consideración importante del proyecto actual

El proyecto ya mantiene un historial manual en `history`, así que no conviene duplicar la instrucción del sistema en cada turno del historial. La mejor integración es:

- dejar el `history` como está
- añadir `systemInstruction` una sola vez por petición
- mantener el archivo de instrucciones como fuente de verdad del comportamiento global

Esto es más estable que concatenar el texto del prompt en cada `message` como si fuera una pregunta del usuario.

## Fases recomendadas de implementación

### Fase A: primer prototipo

- crear `config/system.md`
- añadir `load_system_prompt()`
- propagar el valor a `GeminiBridge`
- validar con una prueba corta de conversación

### Fase B: estabilizar comportamiento

- definir políticas claras para preguntas críticas
- ajustar tono, longitud y reglas de voz
- añadir fallbacks si el archivo falta o está vacío

### Fase C: preparación para más agentes

- separar prompts por agente (`jarvis`, `guardian`, `assistant`, etc.)
- permitir selección del prompt según el modelo o el modo del sistema
- documentar qué comportamiento se controla en cada fichero

## Recomendación final

Para este proyecto, usar `system.md` como archivo principal y un loader desde `config/` es la opción más limpia. La integración real es simple, no rompe la arquitectura del proyecto, y encaja bien con el patrón actual de `settings.py` + `GeminiBridge` + `main.py`.

## Cambio propuesto para la implementación real

1. Crear `config/system.md`
2. Añadir `config/system_prompt.py`
3. Hacer que `GeminiBridge` reciba `system_prompt`
4. Incluir `systemInstruction` en el payload REST
5. Cargar el texto al iniciar la sesión
6. Probar con una frase de bienvenida y una orden crítica

## Ejemplo final del payload

```json
{
  "systemInstruction": {
    "parts": [{
      "text": "Eres Jarvis, un asistente de voz para un hogar inteligente. Responde siempre en español. Habla breve y natural. Antes de acciones críticas confirma la operación."
    }]
  },
  "contents": [
    {"role": "user", "parts": [{"text": "Enciende la luz del salón"}]}
  ],
  "generationConfig": {"temperature": 0.7}
}
```

Esto es el punto exacto que permitiría que Gemini se comporte según el prompt base sin tener que repetirlo en cada mensaje del usuario.
