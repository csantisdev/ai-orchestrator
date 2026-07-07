#!/usr/bin/env python
"""Valida docs/pricing/models.json contra schema.json y reporta hallazgos
de mantenimiento (Decision 0002, Etapa 4).

No hace llamadas de red ni modifica precios — solo lee docs/pricing/ y
orchestrator/costs.py. Pensado para correr en CI (ver
.github/workflows/pricing-catalog.yml) o localmente.

Codigos de salida:
    0 = sin hallazgos
    1 = catalogo invalido contra schema.json (falla dura)
    2 = catalogo valido, pero hay hallazgos de auditoria (--report)

Uso:
    python scripts/validate_pricing_catalog.py
    python scripts/validate_pricing_catalog.py --report
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "docs" / "pricing" / "schema.json"
CATALOG_PATH = ROOT / "docs" / "pricing" / "models.json"

STALE_DAYS_THRESHOLD = 180


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_schema(catalog: dict, schema: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema no está instalado — ejecutá 'pip install jsonschema' antes de correr este script."]

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(catalog), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors]


def find_stale_models(catalog: dict, threshold_days: int = STALE_DAYS_THRESHOLD) -> list[str]:
    today = date.today()
    stale = []
    for provider, provider_data in catalog.get("providers", {}).items():
        for model_id, model_data in provider_data.get("models", {}).items():
            verified_at = model_data.get("verified_at")
            if not verified_at:
                continue
            try:
                verified_date = date.fromisoformat(verified_at)
            except ValueError:
                continue
            age_days = (today - verified_date).days
            if age_days > threshold_days:
                stale.append(f"{provider}/{model_id}: verified_at={verified_at} ({age_days} días)")
    return stale


def find_default_pricing_gaps(catalog: dict) -> dict:
    sys.path.insert(0, str(ROOT))
    from orchestrator.costs import DEFAULT_PRICING

    catalog_model_ids = {
        model_id
        for provider_data in catalog.get("providers", {}).values()
        for model_id in provider_data.get("models", {})
    }
    default_ids = set(DEFAULT_PRICING)
    return {
        "missing_in_catalog": sorted(default_ids - catalog_model_ids),
        "missing_in_default": sorted(catalog_model_ids - default_ids),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", action="store_true",
        help="Agrega auditoria de staleness (verified_at) y consistencia con DEFAULT_PRICING.",
    )
    args = parser.parse_args()

    schema = _load_json(SCHEMA_PATH)
    catalog = _load_json(CATALOG_PATH)

    errors = validate_schema(catalog, schema)
    if errors:
        print("ERRORES DE SCHEMA:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"OK: {CATALOG_PATH} valida contra schema.json")

    if not args.report:
        return 0

    stale = find_stale_models(catalog)
    gaps = find_default_pricing_gaps(catalog)
    found_something = bool(stale or gaps["missing_in_catalog"] or gaps["missing_in_default"])

    if stale:
        print(f"\nModelos con verified_at > {STALE_DAYS_THRESHOLD} días:")
        for s in stale:
            print(f"  - {s}")
    if gaps["missing_in_catalog"]:
        print("\nModelos en DEFAULT_PRICING (costs.py) sin entrada en el catálogo:")
        for m in gaps["missing_in_catalog"]:
            print(f"  - {m}")
    if gaps["missing_in_default"]:
        print("\nModelos en el catálogo sin entrada de fallback en DEFAULT_PRICING:")
        for m in gaps["missing_in_default"]:
            print(f"  - {m}")
    if not found_something:
        print("\nSin hallazgos de auditoría.")

    return 2 if found_something else 0


if __name__ == "__main__":
    sys.exit(main())
