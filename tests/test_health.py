"""Salud de componentes opcionales (spec §7, estado degradado) y su endpoint."""

import pytest

from orchestrator import api_v1, health
from orchestrator.api_v1 import Request


@pytest.fixture(autouse=True)
def clean():
    health.reset()
    yield
    health.reset()


def test_unknown_until_checked_then_ok_or_degraded_with_a_fixed_effect():
    assert health.snapshot()["chroma"] == {"state": "unknown", "checked_at": None, "effect": None}
    health.report("chroma", False)
    degraded = health.snapshot()["chroma"]
    assert degraded["state"] == "degraded"
    assert degraded["effect"] == health.EFFECTS["chroma"]
    health.report("chroma", True)
    assert health.snapshot()["chroma"]["state"] == "ok"
    assert health.snapshot()["chroma"]["effect"] is None


def test_unknown_components_are_rejected():
    with pytest.raises(ValueError):
        health.report("otro", True)


def test_endpoint_returns_the_snapshot():
    api_v1.discover()
    health.report("chroma", False)
    status, payload = api_v1.dispatch(Request("GET", "/api/v1/meta/health"))
    assert status == 200
    assert payload["components"]["chroma"]["state"] == "degraded"
