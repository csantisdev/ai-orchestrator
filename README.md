# ai-orchestrator

Orquestador local de agentes IA. Rutea tareas entre Claude, OpenAI y DeepSeek según el
contexto del proyecto, con dashboard en vivo, tracking de costo y seguimiento de sesiones
de Claude Code.

## Arquitectura

```
C:\Fuentes\ai-orchestrator\          ← instalación global (no vive en cada repo)
├── orchestrator/
│   ├── cli.py          ← comandos Typer
│   ├── router.py       ← decide proveedor (router liviano + similitud semántica)
│   ├── db.py           ← persistencia SQLite (runs, costos, estado)
│   ├── similarity.py   ← búsqueda semántica (ChromaDB) con fallback FTS5
│   ├── watcher.py      ← importa sesiones de Claude Code
│   ├── dashboard.py    ← HTML del panel web
│   ├── sse.py          ← Server-Sent Events (actualizaciones en tiempo real)
│   ├── background.py   ← worker threads para runs asincrónicos
│   ├── costs.py        ← cálculo de costo USD por run
│   └── providers/      ← claude.py · openai.py · deepseek.py
├── config.example.yaml
├── requirements.txt
└── pyproject.toml

~/.ai-orchestrator/                  ← datos runtime (no versionados)
├── config.yaml                      ← API keys, modelos, pricing, budgets
├── index.yaml                       ← alias → path de cada proyecto
├── runs.db                          ← SQLite: historial completo de runs
└── chroma/                          ← índice vectorial (si ChromaDB instalado)

# Dentro de cada proyecto (versionado en su propio repo):
mi-proyecto/
└── .orchestrator/
    └── context.yaml                 ← stack, convenciones, reglas de ruteo
```

## Instalación

```powershell
cd C:\Fuentes\ai-orchestrator
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Copiar y completar la configuración:

```powershell
cp config.example.yaml $env:USERPROFILE\.ai-orchestrator\config.yaml
```

Ver [`docs/api-keys.md`](docs/api-keys.md) para obtener cada API key.

### Búsqueda vectorial (opcional)

```powershell
pip install chromadb
```

Si no está instalado, el router usa FTS5 (SQLite full-text search) como fallback automático.

## Comandos

### Gestión de proyectos

```powershell
# Registrar un proyecto
ai-orchestrator add mi-proyecto --path "C:\ruta\al\proyecto"

# Listar proyectos registrados
ai-orchestrator list

# Quitar un proyecto del índice
ai-orchestrator remove mi-proyecto
```

### Ejecutar tareas

```powershell
# El router decide el proveedor automáticamente
ai-orchestrator run --project mi-proyecto --task "revisar el endpoint de login"

# Forzar un modelo específico
ai-orchestrator run --project mi-proyecto --task "..." --model claude

# Usar Claude Opus para investigación profunda
ai-orchestrator run --project mi-proyecto --task "..." --research
```

### Historial

```powershell
# Ver los últimos 20 runs con costo
ai-orchestrator history

# Filtrar por proyecto
ai-orchestrator history --project mi-proyecto --last 50
```

### Dashboard web

```powershell
# Lanza el panel en http://127.0.0.1:8080 (abre el browser automáticamente)
ai-orchestrator serve

# Puerto alternativo sin abrir el browser
ai-orchestrator serve --port 9090 --no-open
```

El dashboard incluye:
- Tabla de runs en tiempo real vía SSE (sin auto-refresh)
- Formulario embebido para enviar tareas desde el browser
- Panel de detalle con la respuesta completa al hacer click en una fila
- Gauge de presupuesto diario por proyecto
- Indicadores de costo USD y % de cache hit por run

En VS Code: `Ctrl+Shift+P` → **Tasks: Run Task** → **Orchestrator: Dashboard**

### Tracking de Claude Code

```powershell
# Importa sesiones nuevas de Claude Code al historial del orquestador
ai-orchestrator sync-cc
```

Esto parsea `~/.claude/projects/` y agrega cada sesión al DB con tokens, costo estimado
y proyecto detectado por el `cwd`.

**Para sincronización automática al terminar cada sesión de Claude Code,** agregar en
`~/.claude/settings.json`:

```json
"hooks": {
  "Stop": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "C:\\Fuentes\\ai-orchestrator\\.venv\\Scripts\\ai-orchestrator.exe sync-cc --quiet"
        }
      ]
    }
  ]
}
```

## Configuración

Ver [`config.example.yaml`](config.example.yaml) para la plantilla completa, incluyendo
las secciones `pricing` (costo por modelo) y `budgets` (presupuesto diario por proyecto).

## Formato de `context.yaml`

Ver [`docs/context-schema.md`](docs/context-schema.md) para el esquema completo de campos
y reglas de ruteo.

## Licencia

MIT
