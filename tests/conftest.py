import threading

import pytest

from orchestrator import egress
from orchestrator.egress import EgressPolicy


@pytest.fixture(scope="session", autouse=True)
def _isolated_test_db(tmp_path_factory):
    import orchestrator.db as db_module
    import orchestrator.paths as paths_module

    original_home = paths_module.HOME_DIR
    original_db = paths_module.DB_PATH
    test_home = tmp_path_factory.mktemp("ai-orchestrator-db")
    paths_module.HOME_DIR = test_home
    paths_module.DB_PATH = test_home / "runs.db"
    db_module._local = threading.local()
    db_module.init_db()
    try:
        yield
    finally:
        conn = getattr(db_module._local, "conn", None)
        if conn is not None:
            conn.close()
        db_module._local = threading.local()
        paths_module.HOME_DIR = original_home
        paths_module.DB_PATH = original_db


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
