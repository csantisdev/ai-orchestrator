"""Rutas y constantes de la instalación global del orquestador."""

from pathlib import Path

# Carpeta de instalación global: ~/.ai-orchestrator
HOME_DIR = Path.home() / ".ai-orchestrator"

INDEX_PATH = HOME_DIR / "index.yaml"
CONFIG_PATH = HOME_DIR / "config.yaml"

# Nombre del archivo de contexto dentro de cada proyecto
PROJECT_CONTEXT_DIRNAME = ".orchestrator"
PROJECT_CONTEXT_FILENAME = "context.yaml"

PROVIDERS = ("claude", "openai", "deepseek", "gemini")

DB_PATH     = HOME_DIR / "runs.db"
CHROMA_PATH = HOME_DIR / "chroma"
