import pytest

from orchestrator import egress
from orchestrator.egress import EgressPolicy


@pytest.fixture(autouse=True)
def _default_egress_policy(request):
    # RFC-006 §4.1: mantiene la suite existente operativa al sellar el borde en 1.2.
    if request.node.get_closest_marker("no_default_policy"):
        yield
        return

    token = egress.set_policy(EgressPolicy(project="test", sensitivity="internal"))
    try:
        yield
    finally:
        egress._POLICY.reset(token)
