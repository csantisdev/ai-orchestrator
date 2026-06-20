# Obtención de API Keys

El orquestador necesita hasta tres API keys, una por proveedor. Solo son
obligatorias las de los proveedores que vayas a usar. El mínimo funcional
es tener **DeepSeek** (para el router) + **al menos un proveedor destino**.

---

## 1. Anthropic (Claude)

**Por qué:** proveedor principal para razonamiento complejo, arquitectura,
revisiones de seguridad y tareas que requieren contexto largo.

**Pasos:**

1. Ir a <https://console.anthropic.com>
2. Crear cuenta o iniciar sesión.
3. En el menú izquierdo, ir a **API Keys**.
4. Click en **Create Key** → darle un nombre (ej. `ai-orchestrator-local`).
5. Copiar la key inmediatamente — solo se muestra una vez.
6. (Opcional) Ir a **Billing → Add Credits** si la cuenta es nueva.

**Forma de la key:** `sk-ant-api03-...`

**Modelo recomendado en config.yaml:** `claude-sonnet-4-6`

**Costo aproximado:** ~$3 / millón de tokens de entrada (Sonnet).
Ideal para tareas complejas donde la calidad importa más que el costo.

---

## 2. OpenAI

**Por qué:** alternativa sólida para generación de código, completions y
tareas donde GPT-4o tiene ventaja o el precio es relevante.

**Pasos:**

1. Ir a <https://platform.openai.com>
2. Crear cuenta o iniciar sesión.
3. Click en el ícono de perfil (arriba a la derecha) → **Your profile**.
4. En el menú izquierdo, ir a **API keys**.
5. Click en **Create new secret key** → darle un nombre descriptivo.
6. Copiar la key inmediatamente — no se vuelve a mostrar.
7. Asegurarse de tener crédito en **Billing → Add payment method**.

**Forma de la key:** `sk-proj-...` o `sk-...`

**Modelo recomendado en config.yaml:** `gpt-4o`

**Costo aproximado:** ~$2.50 / millón de tokens de entrada (GPT-4o).

---

## 3. DeepSeek

**Por qué:** modelo muy económico usado como **router** (decide a qué
proveedor mandar cada tarea). También puede ser proveedor destino para
tareas de código rutinarias donde el costo importa.

**Pasos:**

1. Ir a <https://platform.deepseek.com>
2. Crear cuenta o iniciar sesión (puede requerir número de teléfono).
3. En el menú izquierdo, ir a **API Keys**.
4. Click en **Create new API key** → darle un nombre.
5. Copiar la key que aparece en pantalla.
6. Ir a **Top Up** para cargar crédito si es necesario (mínimo ~$2 USD).

**Forma de la key:** `sk-...`

**Modelos disponibles:**

| Modelo | Input (cache miss) | Output | Uso recomendado |
|---|---|---|---|
| `deepseek-v4-flash` | $0.14 / M tokens | $0.28 / M tokens | Router + tareas simples |
| `deepseek-v4-pro` | $0.435 / M tokens | $0.87 / M tokens | Razonamiento complejo |

**Modelo recomendado en config.yaml:** `deepseek-v4-flash`

> ⚠️ El alias `deepseek-chat` fue deprecado el 24 de julio de 2026.
> Usar siempre el nombre explícito `deepseek-v4-flash` o `deepseek-v4-pro`.

**Costo aproximado:** $0.14 / millón de tokens (V4-Flash, cache miss).
Con cache activo baja a $0.0028 / M — prácticamente gratis para el router.

---

## Configurar las keys

Una vez obtenidas las keys, editá `~/.ai-orchestrator/config.yaml`:

```yaml
providers:
  claude:
    api_key: "sk-ant-api03-TU_KEY_AQUI"
    model: "claude-sonnet-4-6"

  openai:
    api_key: "sk-proj-TU_KEY_AQUI"
    model: "gpt-4o"

  deepseek:
    api_key: "sk-TU_KEY_AQUI"
    model: "deepseek-v4-flash"

router:
  provider: "deepseek"
  fallback_provider: "claude"

defaults:
  default_provider: "claude"
```

> `config.yaml` vive en `~/.ai-orchestrator/` y **nunca se versiona**.
> Está excluido del repo por `.gitignore`. El archivo `config.example.yaml`
> en el repo es la plantilla de referencia, sin valores reales.

---

## Configuración mínima (sin OpenAI)

Si solo tenés Claude + DeepSeek, dejá el bloque `openai` con una key vacía
o eliminalo. El router no va a rutear hacia OpenAI si no está configurado:

```yaml
providers:
  claude:
    api_key: "sk-ant-api03-TU_KEY_AQUI"
    model: "claude-sonnet-4-6"

  deepseek:
    api_key: "sk-TU_KEY_AQUI"
    model: "deepseek-v4-flash"

router:
  provider: "deepseek"
  fallback_provider: "claude"

defaults:
  default_provider: "claude"
```

---

## Verificar que todo funciona

```bash
# Activar el venv primero
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/Mac

# Test rápido: debe mostrar la tabla de comandos sin errores de config
ai-orchestrator --help

# Test de keys: registrar un proyecto y correr una tarea simple
ai-orchestrator add test --path "C:\ruta\a\cualquier\carpeta"
ai-orchestrator run --project test --task "decime hola"
```

Si el router no puede conectarse a DeepSeek, cae automáticamente al
`fallback_provider` definido en `config.yaml` (por defecto, Claude).
