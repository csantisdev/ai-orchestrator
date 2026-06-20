# ai-orchestrator

Orquestador local de agentes IA. Rutea tareas de desarrollo entre múltiples
proveedores (Claude, OpenAI/Codex, DeepSeek) según el contexto del proyecto
y el contenido de la tarea, usando un modelo "router" liviano para decidir
automáticamente qué motor conviene en cada caso.

## Arquitectura

```
~/.ai-orchestrator/                    ← instalación global (no vive en cada repo)
├── index.yaml                         ← alias → path de cada proyecto
├── config.yaml                        ← API keys, modelo router por defecto
└── orchestrator/
    ├── cli.py                         ← comandos Typer (run, add, list, remove)
    ├── router.py                      ← consulta al modelo router liviano
    ├── context.py                     ← lee el context.yaml del proyecto
    └── providers/
        ├── claude.py
        ├── openai.py
        └── deepseek.py

# Dentro de cada proyecto (versionado en su propio repo):
mi-proyecto/
└── .orchestrator/
    └── context.yaml                   ← stack, convenciones, reglas de ruteo
```

**Principio de diseño:** el orquestador es una herramienta global, instalada
una sola vez. Cada proyecto aporta su propio `context.yaml` versionado junto
al código, así viaja con el repo y cualquiera que lo clone entiende el
contexto sin pasos adicionales.

## Instalación

```bash
git clone git@github.com:csantisdev/ai-orchestrator.git ~/.ai-orchestrator
cd ~/.ai-orchestrator
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

Copiá `config.example.yaml` a `config.yaml` y completá tus API keys:

```bash
cp config.example.yaml ~/.ai-orchestrator/config.yaml
```

Ver [`docs/api-keys.md`](docs/api-keys.md) para el paso a paso de cómo
obtener cada key (Anthropic, OpenAI, DeepSeek) y la configuración mínima
si no usás todos los proveedores.

## Uso

### Registrar un proyecto

```bash
ai-orchestrator add mi-proyecto --path "/ruta/a/mi-proyecto"
```

Esto crea el índice en `~/.ai-orchestrator/index.yaml` y, si no existe,
genera un `.orchestrator/context.yaml` base dentro del proyecto.

### Ejecutar una tarea

```bash
ai-orchestrator run --project mi-proyecto --task "revisar este endpoint y sugerir refactor"
```

El router decide automáticamente el modelo más adecuado según las reglas
definidas en el `context.yaml` del proyecto y el contenido de la tarea.

### Forzar un modelo (override manual)

```bash
ai-orchestrator run --project mi-proyecto --task "..." --model claude
```

### Listar proyectos registrados

```bash
ai-orchestrator list
```

## Formato de `context.yaml`

Ver [`docs/context-schema.md`](docs/context-schema.md) para el detalle
completo de campos y reglas de ruteo soportadas.

## Roadmap

- [ ] Historial de ejecuciones en SQLite (costo, modelo usado, resultado)
- [ ] Integración como Task de VS Code (`tasks.json`)
- [ ] Soporte multi-step (cadenas de tareas entre proveedores)

## Licencia

MIT
