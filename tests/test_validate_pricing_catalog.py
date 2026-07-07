"""Tests del script de mantenimiento del catalogo publico (Decision 0002, Etapa 4)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.validate_pricing_catalog as v


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_real_catalog_validates_clean():
    schema = v._load_json(v.SCHEMA_PATH)
    catalog = v._load_json(v.CATALOG_PATH)

    errors = v.validate_schema(catalog, schema)

    assert errors == []


def test_real_catalog_has_no_default_pricing_gaps():
    catalog = v._load_json(v.CATALOG_PATH)
    gaps = v.find_default_pricing_gaps(catalog)

    assert gaps["missing_in_catalog"] == []
    assert gaps["missing_in_default"] == []


def test_validate_schema_reports_missing_required_field():
    schema = v._load_json(v.SCHEMA_PATH)
    broken = {
        "schema_version": "1.0",
        "currency": "USD",
        "unit": "per_1m_tokens",
        # falta "updated_at" y "providers"
    }

    errors = v.validate_schema(broken, schema)

    assert errors
    assert any("updated_at" in e or "providers" in e for e in errors)


def test_find_stale_models_detects_old_verified_at():
    catalog = {
        "providers": {
            "fake": {
                "display_name": "Fake",
                "models": {
                    "old-model": {"verified_at": "2020-01-01"},
                    "fresh-model": {"verified_at": "2026-07-01"},
                },
            }
        }
    }

    stale = v.find_stale_models(catalog, threshold_days=180)

    assert any("old-model" in s for s in stale)
    assert not any("fresh-model" in s for s in stale)


def test_main_exit_code_1_on_schema_error(tmp_path, monkeypatch):
    schema_path = tmp_path / "schema.json"
    catalog_path = tmp_path / "models.json"
    _write(schema_path, v._load_json(v.SCHEMA_PATH))
    broken = v._load_json(v.CATALOG_PATH)
    del broken["currency"]
    _write(catalog_path, broken)

    monkeypatch.setattr(v, "SCHEMA_PATH", schema_path)
    monkeypatch.setattr(v, "CATALOG_PATH", catalog_path)
    monkeypatch.setattr(sys, "argv", ["validate_pricing_catalog.py"])

    assert v.main() == 1


def test_main_exit_code_0_when_clean(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["validate_pricing_catalog.py"])
    assert v.main() == 0


def test_main_exit_code_2_when_report_finds_gap(tmp_path, monkeypatch):
    schema_path = tmp_path / "schema.json"
    catalog_path = tmp_path / "models.json"
    _write(schema_path, v._load_json(v.SCHEMA_PATH))
    catalog = v._load_json(v.CATALOG_PATH)
    # agrega un modelo nuevo al catalogo que no existe en DEFAULT_PRICING
    catalog["providers"]["anthropic"]["models"]["claude-modelo-nuevo"] = {
        "id": "claude-modelo-nuevo", "provider": "anthropic", "status": "active",
        "pricing": {"input": 1.0, "output": 1.0},
        "source_url": "https://example.com", "verified_at": "2026-07-01",
    }
    _write(catalog_path, catalog)

    monkeypatch.setattr(v, "SCHEMA_PATH", schema_path)
    monkeypatch.setattr(v, "CATALOG_PATH", catalog_path)
    monkeypatch.setattr(sys, "argv", ["validate_pricing_catalog.py", "--report"])

    assert v.main() == 2
